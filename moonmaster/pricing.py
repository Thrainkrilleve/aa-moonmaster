"""
Pricing service for Moon Master.

Supports three price sources:
  - ESI      : /markets/prices/ — adjusted price (same source the game uses)
  - Fuzzwork : https://market.fuzzwork.co.uk/aggregates/ — buy/sell per type_id
  - Janice   : https://janice.e-351.com/api/rest/v2/pricer — sell price for fuel/gas, buy price for ore

Call ``update_all_prices(type_ids, source)`` to refresh the OrePrice table.
Call ``get_prices(type_ids)`` to retrieve a {type_id: Decimal} mapping from cache.

To enable Janice add ``MOONMASTER_JANICE_API_KEY = "<your-key>"`` to your
Django ``local.py``.  When that setting is present the periodic price task
will automatically use Janice instead of Fuzzwork.
"""

import logging
from decimal import Decimal
from typing import Dict, Iterable, List

import requests

from .constants import (
    MOON_ORE_NAMES,
    PRICE_SOURCE_ESI,
    PRICE_SOURCE_FUZZWORK,
    PRICE_SOURCE_JANICE,
)

logger = logging.getLogger(__name__)

# Names for fuel/gas types used by Janice's name-based lookup.
# MOON_ORE_NAMES is populated from django-eveonline-sde at startup; fuel names
# below are stable and kept as a hardcoded fallback (SDE also queried at call
# time via get_item_names() so any rename is picked up automatically).
_FUEL_NAMES_FALLBACK: Dict[int, str] = {
    4051:  "Nitrogen Fuel Block",
    4246:  "Hydrogen Fuel Block",
    4247:  "Helium Fuel Block",
    4312:  "Oxygen Fuel Block",
    81143: "Magmatic Gas",
}

# ---------------------------------------------------------------------------
# ESI
# ---------------------------------------------------------------------------

ESI_PRICES_URL = "https://esi.evetech.net/latest/markets/prices/?datasource=tranquility"
ESI_TYPES_URL = "https://esi.evetech.net/latest/universe/types/{type_id}/?datasource=tranquility"

# Request timeout (seconds)
_TIMEOUT = 30


def _fetch_esi_prices() -> Dict[int, Decimal]:
    """
    Return a {type_id: adjusted_price} dict fetched from ESI /markets/prices/.
    Raises requests.RequestException on failure.
    """
    resp = requests.get(ESI_PRICES_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    result: Dict[int, Decimal] = {}
    for entry in resp.json():
        type_id = int(entry["type_id"])
        price = entry.get("adjusted_price") or entry.get("average_price")
        if price is not None:
            result[type_id] = Decimal(str(price))
    return result


def _fetch_esi_type_name(type_id: int) -> str:
    """Fetch the English name for a type from ESI. Returns empty string on failure."""
    try:
        resp = requests.get(ESI_TYPES_URL.format(type_id=type_id), timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("name", "")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Janice
# ---------------------------------------------------------------------------

JANICE_PRICER_URL = "https://janice.e-351.com/api/rest/v2/pricer"
# Jita market id in Janice
JANICE_JITA_MARKET_ID = 2


def _fetch_janice_prices(type_ids: Iterable[int], api_key: str) -> Dict[int, Decimal]:
    """
    Return a {type_id: price} dict from Janice's bulk pricer endpoint.

    Pricing logic:
    - Fuel blocks and Magmatic Gas (input costs) → top-5% average *sell* price,
      because that is what the structure operator pays to buy them off market.
    - Moon ores (output value) → top-5% average *buy* price, because bulk ore
      is realistically sold to buy orders or corp buyback programs.

    Janice does NOT index moon ores by the same type IDs used in the EVE SDE
    (e.g. 45509 resolves to a ship SKIN in Janice's DB, not Cinnabar).  To
    avoid this, we send item *names* instead of IDs and match the response
    back using the returned ``itemType.name`` field.  Any type_id whose name
    we don't know is silently skipped.

    Raises requests.RequestException on failure.
    """
    from .constants import FUEL_BLOCK_TYPE_IDS, ESI_TYPE_ID_MAGMATIC_GAS  # noqa: PLC0415
    _fuel_ids = set(FUEL_BLOCK_TYPE_IDS) | {ESI_TYPE_ID_MAGMATIC_GAS}
    # Build a combined id→name map: moon ores (SDE-backed) + fuel/gas.
    # Try the SDE first for fuel names so any future CCP rename is picked up;
    # fall back to the hardcoded dict if the SDE is unavailable.
    from .sde import get_item_names as _sde_names  # noqa: PLC0415
    fuel_ids = [tid for tid in type_ids if tid not in MOON_ORE_NAMES]
    sde_fuel = _sde_names(fuel_ids) if fuel_ids else {}
    id_to_name: Dict[int, str] = {**MOON_ORE_NAMES, **_FUEL_NAMES_FALLBACK, **sde_fuel}

    # Only query items whose names we know; map name→id for response matching
    name_to_id: Dict[str, int] = {}
    lines: List[str] = []
    for tid in type_ids:
        name = id_to_name.get(tid)
        if name:
            lines.append(name)
            name_to_id[name.lower()] = tid

    if not lines:
        return {}

    body = "\n".join(lines)
    headers = {
        "X-ApiKey": api_key,
        "Content-Type": "text/plain",
        "Accept": "application/json",
    }
    params = {"market": JANICE_JITA_MARKET_ID}
    resp = requests.post(
        JANICE_PRICER_URL, data=body.encode(), headers=headers, params=params, timeout=_TIMEOUT
    )
    resp.raise_for_status()
    result: Dict[int, Decimal] = {}
    for item in resp.json():
        try:
            returned_name = (item.get("itemType") or {}).get("name", "")
            type_id = name_to_id.get(returned_name.lower())
            if type_id is None:
                logger.debug("Janice returned unknown item name %r — skipped.", returned_name)
                continue
            # Fuel/gas → sell price (operator pays this to buy from market).
            # Moon ore → buy price (realistic bulk sale to buy orders/buyback).
            if type_id in _fuel_ids:
                price = (
                    (item.get("top5AveragePrices") or {}).get("sellPrice")
                    or (item.get("immediatePrices") or {}).get("sellPrice")
                    or 0
                )
            else:
                price = (
                    (item.get("top5AveragePrices") or {}).get("buyPrice")
                    or (item.get("immediatePrices") or {}).get("buyPrice")
                    or 0
                )
            result[type_id] = Decimal(str(price))
        except (KeyError, TypeError, ValueError):
            pass
    return result


# ---------------------------------------------------------------------------
# Fuzzwork
# ---------------------------------------------------------------------------

FUZZWORK_AGGREGATES_URL = "https://market.fuzzwork.co.uk/aggregates/"


def _fetch_fuzzwork_prices(type_ids: Iterable[int]) -> Dict[int, Decimal]:
    """
    Return a {type_id: buy_max_price} dict from Fuzzwork's aggregates endpoint.
    Uses the highest buy order price (Jita 4-4) as the valuation.
    Raises requests.RequestException on failure.
    """
    ids_str = ",".join(str(i) for i in type_ids)
    params = {"types": ids_str, "station": 60003760}  # Jita 4-4
    resp = requests.get(FUZZWORK_AGGREGATES_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    result: Dict[int, Decimal] = {}
    for type_id_str, prices in data.items():
        try:
            buy_max = prices.get("buy", {}).get("max", 0)
            result[int(type_id_str)] = Decimal(str(buy_max))
        except (KeyError, TypeError, ValueError):
            pass
    return result


# ---------------------------------------------------------------------------
# Unified update + retrieval
# ---------------------------------------------------------------------------


def update_all_prices(type_ids: List[int], source: str = PRICE_SOURCE_ESI) -> int:
    """
    Fetch prices for the given type_ids and upsert into the OrePrice table.

    Returns the number of records updated/created.
    """
    # Import here to avoid circular imports at module load time
    from .models import OrePrice  # noqa: PLC0415

    if source == PRICE_SOURCE_JANICE:
        from django.conf import settings
        api_key = getattr(settings, "MOONMASTER_JANICE_API_KEY", "")
        if not api_key:
            logger.error("Janice price source selected but MOONMASTER_JANICE_API_KEY is not set.")
            return 0
        try:
            prices = _fetch_janice_prices(type_ids, api_key)
        except requests.RequestException as exc:
            logger.error("Janice price fetch failed: %s", exc)
            return 0
    elif source == PRICE_SOURCE_FUZZWORK:
        try:
            prices = _fetch_fuzzwork_prices(type_ids)
        except requests.RequestException as exc:
            logger.error("Fuzzwork price fetch failed: %s", exc)
            return 0
    else:
        try:
            all_prices = _fetch_esi_prices()
        except requests.RequestException as exc:
            logger.error("ESI price fetch failed: %s", exc)
            return 0
        prices = {tid: all_prices[tid] for tid in type_ids if tid in all_prices}

    updated = 0
    for type_id, price in prices.items():
        obj, created = OrePrice.objects.update_or_create(
            type_id=type_id,
            defaults={
                "avg_price": price,
                "source": source,
            },
        )
        # Back-fill name if missing
        if not obj.type_name:
            name = _fetch_esi_type_name(type_id)
            if name:
                OrePrice.objects.filter(pk=obj.pk).update(type_name=name)
        updated += 1

    logger.info("Updated %d prices from %s.", updated, source)
    return updated


def get_prices(type_ids: Iterable[int]) -> Dict[int, Decimal]:
    """
    Return a {type_id: avg_price} mapping from the OrePrice cache table.
    Missing entries default to Decimal("0").
    """
    from .models import OrePrice  # noqa: PLC0415

    rows = OrePrice.objects.filter(type_id__in=list(type_ids)).values("type_id", "avg_price")
    result: Dict[int, Decimal] = {row["type_id"]: row["avg_price"] or Decimal("0") for row in rows}
    return result
