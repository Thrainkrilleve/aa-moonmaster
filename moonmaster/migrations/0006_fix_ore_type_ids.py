"""
Fix incorrect moon ore type IDs and recalculate moon rarity classes.

Background
----------
The original constants.py had wrong type IDs for R32 (Rare) and R64 (Exceptional)
moon ores.  Specifically:

  Old (wrong) → New (correct EVE SDE)
  ─────────────────────────────────────────────────────────
  45504  "Loparite"  R32  → 45512  Loparite   R64  (Loparite is R64)
  45505  "Monazite"  R32  → 45511  Monazite   R64  (Monazite is R64; 45505 not a moon ore)
  45506  "Xenotime"  R64  → 45510  Xenotime   R64  (Xenotime is 45510; 45506 is Cinnabar R32)
  45507  "Ytterbite" R64  → 45513  Ytterbite  R64  (45507 is a ship SKIN)
  45508  "Pollucite" R64  → 45504  Pollucite  R32  (Pollucite is R32; 45508 is a ship SKIN)
  45509  "Cinnabar"  R64  → 45506  Cinnabar   R32  (Cinnabar is R32; 45509 is a ship SKIN)

Only 45509 (Cinnabar stored under the wrong ID) was found in the live database.
This migration:
  1. Renames ore_composition keys  45509 → 45506 in all Moon records.
  2. Recalculates Moon.rarity_class using the corrected mapping.
  3. Deletes OrePrice rows for the now-invalid SKIN type IDs so they are
     re-fetched correctly on the next scheduled price refresh.
"""

from django.db import migrations

# Old type_id → correct type_id for compositions stored via the wrong key.
# Only the IDs actually found in the database are listed; include all wrong IDs
# so the migration is safe to run on any install.
_OLD_TO_NEW = {
    "45504": "45512",  # "Loparite" R32 → real Loparite 45512 R64
    "45505": "45511",  # "Monazite" R32 → real Monazite 45511 R64
    "45506": "45510",  # "Xenotime" R64 → real Xenotime 45510 R64
    "45507": "45513",  # "Ytterbite" SKIN → real Ytterbite 45513 R64
    "45508": "45504",  # "Pollucite" SKIN → real Pollucite 45504 R32
    "45509": "45506",  # "Cinnabar" SKIN → real Cinnabar 45506 R32
}

# Rarity class values (mirrors the constants — can't import from constants in
# migrations, so hardcoded here).
_RARITY_MAP = {
    45490: "ubiquitous", 45491: "ubiquitous", 45492: "ubiquitous", 45493: "ubiquitous",
    45494: "common",     45495: "common",     45496: "common",     45497: "common",
    45498: "uncommon",   45499: "uncommon",   45500: "uncommon",   45501: "uncommon",
    45502: "rare",       45503: "rare",       45504: "rare",       45506: "rare",
    45510: "exceptional", 45511: "exceptional", 45512: "exceptional", 45513: "exceptional",
}
_RARITY_ORDER = ["ubiquitous", "common", "uncommon", "rare", "exceptional"]


def _fix_compositions(apps, schema_editor):
    Moon = apps.get_model("moonmaster", "Moon")
    OrePrice = apps.get_model("moonmaster", "OrePrice")

    # ── 1. Fix composition key IDs ────────────────────────────────────────
    affected = Moon.objects.filter(
        ore_composition__has_any_keys=list(_OLD_TO_NEW.keys())
    )
    for moon in affected:
        new_comp = {
            _OLD_TO_NEW.get(k, k): v
            for k, v in moon.ore_composition.items()
        }
        moon.ore_composition = new_comp

    # ── 2. Recalculate rarity_class for ALL moons ─────────────────────────
    all_moons = list(Moon.objects.all())
    for moon in all_moons:
        best = ""
        for tid_str in moon.ore_composition:
            rarity = _RARITY_MAP.get(int(tid_str), "")
            if not best or _RARITY_ORDER.index(rarity) > _RARITY_ORDER.index(best):
                best = rarity
        moon.rarity_class = best or moon.rarity_class

    Moon.objects.bulk_update(all_moons, ["ore_composition", "rarity_class"])

    # ── 3. Remove OrePrice rows for SKIN / non-ore type IDs ───────────────
    stale_ids = [45505, 45507, 45508, 45509]
    deleted, _ = OrePrice.objects.filter(type_id__in=stale_ids).delete()
    if deleted:
        import logging
        logging.getLogger(__name__).info(
            "0006_fix_ore_type_ids: removed %d stale OrePrice row(s) for SKIN type IDs.", deleted
        )


class Migration(migrations.Migration):

    dependencies = [
        ("moonmaster", "0005_ownercharacter"),
    ]

    operations = [
        migrations.RunPython(_fix_compositions, migrations.RunPython.noop),
    ]
