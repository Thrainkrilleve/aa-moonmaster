"""
ESI client helpers for Moon Master.

All authenticated calls follow the same pattern:
  1. Retrieve a valid Token via ``get_valid_token()``
  2. Call ``refresh_token()`` to ensure the access token is fresh
  3. Pass the token to ``esi_authed_get()``

Public (unauthenticated) universe lookups use ``esi_public_get()``.
``get_or_create_moon()`` combines public lookups with local DB writes.
"""

import logging
from typing import Any, List, Optional, Tuple

import requests

from esi.errors import TokenExpiredError, TokenInvalidError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_SCOPES: List[str] = [
    "esi-corporations.read_structures.v1",
    "esi-industry.read_corporation_mining.v1",
]

SCOPE_STRUCTURES = "esi-corporations.read_structures.v1"
SCOPE_MINING     = "esi-industry.read_corporation_mining.v1"
SCOPE_ASSETS     = "esi-assets.read_corporation_assets.v1"

# EVE type IDs for moon-mining structures
ATHANOR_TYPE_ID  = 35835
METENOX_TYPE_ID  = 81826
MOON_STRUCTURE_TYPE_IDS = frozenset([ATHANOR_TYPE_ID, METENOX_TYPE_ID])

# Structure states that mean the structure is NOT operationally online
_OFFLINE_STATES = frozenset([
    "anchoring",
    "unanchoring",
    "asset_safety_deliver",
    "offline",
])

ESI_BASE = "https://esi.evetech.net/latest"
ESI_DATASOURCE = "tranquility"
ESI_TIMEOUT = 30
_USER_AGENT = "aa-moonmaster/0.1.0 (Alliance Auth plugin)"


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def get_valid_token(character_id: int, scopes: Optional[List[str]] = None):
    """
    Return the first valid, refreshable ESI Token for ``character_id`` that
    has all ``scopes``.  Returns ``None`` if no suitable token exists.
    """
    from esi.models import Token

    if scopes is None:
        scopes = REQUIRED_SCOPES

    return (
        Token.objects
        .filter(character_id=character_id)
        .require_scopes(scopes)
        .require_valid()
        .first()
    )


def refresh_token(token) -> bool:
    """
    Ensure the token's access token is current.  Returns ``True`` on success.
    If the token is expired / invalid it is deleted and ``False`` is returned.
    """
    try:
        token.refresh()
        return True
    except (TokenExpiredError, TokenInvalidError):
        logger.warning(
            "Token for character %s is invalid or expired — removing.",
            getattr(token, "character_name", token.character_id),
        )
        token.delete()
        return False


# ---------------------------------------------------------------------------
# ESI HTTP helpers
# ---------------------------------------------------------------------------

def esi_public_get(path: str, params: Optional[dict] = None) -> Any:
    """Unauthenticated ESI GET.  Returns parsed JSON (dict or list)."""
    base = {"datasource": ESI_DATASOURCE}
    if params:
        base.update(params)
    resp = requests.get(
        f"{ESI_BASE}{path}",
        params=base,
        headers={"User-Agent": _USER_AGENT},
        timeout=ESI_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def esi_authed_get(path: str, token, params: Optional[dict] = None) -> list:
    """
    Authenticated, paginated ESI GET.  Combines all pages and returns a
    flat list.  Caller must have already called ``refresh_token(token)``
    before invoking this function.

    Raises ``requests.RequestException`` on HTTP errors.
    """
    base = {"datasource": ESI_DATASOURCE}
    if params:
        base.update(params)

    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    }
    url = f"{ESI_BASE}{path}"

    resp = requests.get(url, headers=headers, params={**base, "page": 1}, timeout=ESI_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    total_pages = int(resp.headers.get("X-Pages", 1))
    for page in range(2, total_pages + 1):
        r = requests.get(url, headers=headers, params={**base, "page": page}, timeout=ESI_TIMEOUT)
        r.raise_for_status()
        data.extend(r.json())

    return data


# ---------------------------------------------------------------------------
# Moon helpers
# ---------------------------------------------------------------------------

def get_or_create_moon(moon_id: int) -> Tuple:
    """
    Ensure a ``Moon`` record exists for the given EVE ``moon_id``, fetching
    name and location info from ESI if it needs to be created.
    Returns ``(moon, created)`` — same convention as Django's ``get_or_create``.
    """
    from .models import Moon

    try:
        return Moon.objects.get(moon_id=moon_id), False
    except Moon.DoesNotExist:
        pass

    # --- fetch moon data ---
    moon_name = f"Moon {moon_id}"
    solar_system_id = 0
    solar_system_name = ""
    region_name = ""

    try:
        moon_data = esi_public_get(f"/universe/moons/{moon_id}/")
        moon_name = moon_data.get("name", moon_name)
        solar_system_id = int(moon_data.get("system_id", 0))
    except requests.RequestException as exc:
        logger.warning("ESI moon lookup failed for %d: %s", moon_id, exc)

    if solar_system_id:
        try:
            sys_data = esi_public_get(f"/universe/systems/{solar_system_id}/")
            solar_system_name = sys_data.get("name", "")
            const_id = sys_data.get("constellation_id")
        except requests.RequestException:
            const_id = None

        if const_id:
            try:
                const_data = esi_public_get(f"/universe/constellations/{const_id}/")
                region_id = const_data.get("region_id")
            except requests.RequestException:
                region_id = None

            if region_id:
                try:
                    region_data = esi_public_get(f"/universe/regions/{region_id}/")
                    region_name = region_data.get("name", "")
                except requests.RequestException:
                    pass

    moon = Moon.objects.create(
        moon_id=moon_id,
        name=moon_name,
        solar_system_id=solar_system_id,
        solar_system_name=solar_system_name,
        region_name=region_name,
        ore_composition={},
    )
    logger.info("Created Moon %d — %s (%s)", moon_id, moon_name, solar_system_name)
    return moon, True


def structure_is_online(esi_state: str) -> bool:
    """Return whether an ESI structure state string represents an online structure."""
    return esi_state not in _OFFLINE_STATES


# ---------------------------------------------------------------------------
# Structure / moon position helpers  (require esi-universe.read_structures.v1)
# ---------------------------------------------------------------------------

SCOPE_UNIVERSE = "esi-universe.read_structures.v1"


def get_structure_info(structure_id: int, token) -> Optional[dict]:
    """
    Return ESI structure detail dict (keys: solar_system_id, position {x,y,z})
    for a player-owned structure.  Requires SCOPE_UNIVERSE on the token.
    Returns None on any error.
    """
    try:
        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        resp = requests.get(
            f"{ESI_BASE}/universe/structures/{structure_id}/",
            headers=headers,
            params={"datasource": ESI_DATASOURCE},
            timeout=ESI_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("get_structure_info(%d): %s", structure_id, exc)
        return None


def find_moon_for_position(
    solar_system_id: int, sx: float, sy: float, sz: float
) -> Optional[int]:
    """
    Return the moon_id in solar_system_id whose co-ordinates are closest to
    (sx, sy, sz) using public ESI.  Structures are anchored at their moon so
    the closest moon at distance near-zero is the correct match.
    Returns None if no moons are found.
    """
    try:
        sys_data = esi_public_get(f"/universe/systems/{solar_system_id}/")
    except Exception as exc:
        logger.warning("find_moon_for_position: system %d: %s", solar_system_id, exc)
        return None

    moon_ids: List[int] = []
    for planet in sys_data.get("planets", []):
        moon_ids.extend(planet.get("moons", []))

    if not moon_ids:
        return None

    best_id: Optional[int] = None
    best_dist_sq = float("inf")

    for moon_id in moon_ids[:60]:  # cap to avoid overwhelming ESI in large systems
        try:
            moon_data = esi_public_get(f"/universe/moons/{moon_id}/")
            pos = moon_data.get("position", {})
            mx = float(pos.get("x", 0))
            my = float(pos.get("y", 0))
            mz = float(pos.get("z", 0))
            dist_sq = (sx - mx) ** 2 + (sy - my) ** 2 + (sz - mz) ** 2
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_id = moon_id
        except Exception:
            continue

    return best_id
