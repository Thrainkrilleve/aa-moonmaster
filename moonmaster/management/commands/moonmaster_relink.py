"""
Management command: relink unlinked Metenox/Athanor structures to their moons.

Usage:
    python manage.py moonmaster_relink
    python manage.py moonmaster_relink --all   # retry even already-linked structures
"""
import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Re-link Metenox/Athanor structures that have no moon set"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Retry linking for all structures, not just unlinked ones",
        )

    def handle(self, *args, **options):
        from moonmaster.models import Structure
        from moonmaster.providers import (
            find_moon_by_number,
            find_moon_for_position,
            get_or_create_moon,
            get_structure_info,
            get_valid_token,
            refresh_token,
            SCOPE_UNIVERSE,
        )
        import re

        _INT_TO_ROMAN = {
            1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII",
            8: "VIII", 9: "IX", 10: "X", 11: "XI", 12: "XII", 13: "XIII",
            14: "XIV", 15: "XV", 16: "XVI", 17: "XVII", 18: "XVIII",
        }
        _ROMAN_TO_INT = {v: k for k, v in _INT_TO_ROMAN.items()}

        qs = Structure.objects.filter(structure_type__in=["metenox", "athanor"]).select_related("owner__character", "owner__corporation")
        if not options["all"]:
            qs = qs.filter(moon__isnull=True)

        total = qs.count()
        self.stdout.write(f"Processing {total} structure(s)...")

        linked = 0
        for structure in qs:
            name = structure.name or ""
            owner = structure.owner
            system_id = None

            if not owner or not owner.character:
                self.stdout.write(self.style.WARNING(
                    f"  [skip] {name!r} — no owner character"
                ))
                continue

            char_id = owner.character.character_id
            corp_id = owner.corporation.corporation_id

            # Try to get system_id from ESI (if we have the universe scope)
            token = get_valid_token(char_id, [SCOPE_UNIVERSE])
            if token and refresh_token(token):
                info = get_structure_info(structure.structure_id, token)
                if info:
                    system_id = info.get("solar_system_id")
                    pos = info.get("position", {})
                    moon_id = find_moon_for_position(
                        system_id,
                        float(pos.get("x", 0)),
                        float(pos.get("y", 0)),
                        float(pos.get("z", 0)),
                    )
                    if moon_id:
                        moon, _ = get_or_create_moon(moon_id)
                        structure.moon = moon
                        structure.save(update_fields=["moon"])
                        self.stdout.write(self.style.SUCCESS(
                            f"  [position] {name!r} → {moon}"
                        ))
                        linked += 1
                        continue

            # Get system_id from owner's last known corporation structures via DB
            # Fall back to name-based parsing + ESI system_id lookup
            # We need system_id — try getting it from owner corporation
            if not system_id and owner:
                from moonmaster.providers import esi_authed_get, SCOPE_STRUCTURES
                corp_token = get_valid_token(char_id, [SCOPE_STRUCTURES])
                if corp_token and refresh_token(corp_token):
                    try:
                        structs = esi_authed_get(
                            f"/corporations/{corp_id}/structures/",
                            corp_token,
                        )
                        for s in structs:
                            if s.get("structure_id") == structure.structure_id:
                                system_id = s.get("system_id")
                                break
                    except Exception:
                        pass

            if not system_id:
                self.stdout.write(self.style.WARNING(
                    f"  [skip] {name!r} — could not determine system_id"
                ))
                continue

            # Roman numeral planet: "System - VIII.7"
            m = re.match(r'^(.+?)\s*-\s*([IVXivx]+)\.(\d+)\s*$', name)
            if m:
                planet_n = _ROMAN_TO_INT.get(m.group(2).upper())
                moon_n = int(m.group(3))
                if planet_n:
                    moon_id = find_moon_by_number(system_id, planet_n, moon_n)
                    if moon_id:
                        moon, _ = get_or_create_moon(moon_id)
                        structure.moon = moon
                        structure.save(update_fields=["moon"])
                        self.stdout.write(self.style.SUCCESS(
                            f"  [roman] {name!r} → {moon}"
                        ))
                        linked += 1
                        continue

            # Decimal planet: "System - 7-12"
            m = re.match(r'^(.+?)\s*-\s*(\d+)-(\d+)\s*$', name)
            if m:
                planet_n = int(m.group(2))
                moon_n = int(m.group(3))
                moon_id = find_moon_by_number(system_id, planet_n, moon_n)
                if moon_id:
                    moon, _ = get_or_create_moon(moon_id)
                    structure.moon = moon
                    structure.save(update_fields=["moon"])
                    self.stdout.write(self.style.SUCCESS(
                        f"  [decimal] {name!r} → {moon}"
                    ))
                    linked += 1
                    continue

            self.stdout.write(self.style.WARNING(
                f"  [fail] {name!r} — no matching moon found"
            ))

        self.stdout.write(f"\nDone. Linked {linked}/{total} structure(s).")
