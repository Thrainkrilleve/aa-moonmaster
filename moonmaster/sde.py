"""
Helpers for building moon-ore lookup tables from django-eveonline-sde.

Called once from MoonMasterConfig.ready() to populate the live constant dicts in
constants.py.  Any importer that holds a reference to MOON_ORE_NAMES / MOON_ORE_RARITY /
MOON_ORE_VOLUME_M3 will automatically see the SDE-backed data because the dicts are
mutated in-place (not rebound), so module-level imports remain valid.
"""

import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDE group ID → rarity class
# This is the only piece of knowledge that cannot come from the SDE itself —
# it encodes CCP's R-tier convention for each asteroid group.
# ---------------------------------------------------------------------------
MOON_ORE_GROUP_RARITY: Dict[int, str] = {
    1884: "ubiquitous",   # R4  — Ubiquitous Moon Asteroids
    1920: "common",       # R8  — Common Moon Asteroids
    1921: "uncommon",     # R16 — Uncommon Moon Asteroids
    1922: "rare",         # R32 — Rare Moon Asteroids
    1923: "exceptional",  # R64 — Exceptional Moon Asteroids
}

_GROUP_IDS = list(MOON_ORE_GROUP_RARITY.keys())


def build_moon_ore_tables() -> Tuple[Dict[int, str], Dict[int, str], Dict[int, float]]:
    """
    Query django-eveonline-sde and return (names, rarity, volumes) for all base
    moon ores.

    Only uncompressed, base-name ores are returned:
    - ``volume = 10.0 m³``  — excludes compressed variants (0.1 m³)
    - name has no spaces    — excludes quality variants ("Brimful Zeolites" etc.)

    Returns three empty dicts on any failure so the caller can keep its existing
    hardcoded fallback values.
    """
    try:
        from eve_sde.models import ItemType  # noqa: PLC0415

        rows = (
            ItemType.objects
            .filter(group_id__in=_GROUP_IDS, volume=10.0)
            .exclude(name_en__contains=" ")   # quality variants have two-word names
            .values_list("id", "name_en", "volume", "group_id")
        )

        names: Dict[int, str] = {}
        rarity: Dict[int, str] = {}
        volumes: Dict[int, float] = {}

        for type_id, name, volume, group_id in rows:
            names[type_id] = name
            rarity[type_id] = MOON_ORE_GROUP_RARITY[group_id]
            volumes[type_id] = float(volume)

        if names:
            logger.info(
                "Moon Master: loaded %d moon ore types from django-eveonline-sde.",
                len(names),
            )
        else:
            logger.warning(
                "Moon Master: django-eveonline-sde ItemType table is empty — "
                "moon ore tables will use hardcoded fallback values. "
                "Run 'manage.py esde_load_sde' to populate the SDE.",
            )

        return names, rarity, volumes

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Moon Master: could not query django-eveonline-sde (%s) — "
            "using hardcoded moon ore fallback values.",
            exc,
        )
        return {}, {}, {}


def get_item_names(type_ids) -> Dict[int, str]:
    """Return ``{type_id: name_en}`` for the given type IDs from the SDE."""
    try:
        from eve_sde.models import ItemType  # noqa: PLC0415

        return dict(
            ItemType.objects
            .filter(id__in=list(type_ids))
            .values_list("id", "name_en")
        )
    except Exception:  # noqa: BLE001
        return {}
