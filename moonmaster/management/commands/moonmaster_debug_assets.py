"""
Management command: dump ESI corporation assets for a moonmaster owner so you
can see the real location_flag values being returned and diagnose why
goo_bay_fill_pct is always 0%.

Usage:
    python manage.py moonmaster_debug_assets
    python manage.py moonmaster_debug_assets --owner "My Corp Name"
    python manage.py moonmaster_debug_assets --owner "My Corp Name" --flag MoonMaterialBay
    python manage.py moonmaster_debug_assets --owner "My Corp Name" --metenox-only
"""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Dump ESI asset location_flag breakdown for a moonmaster owner (diagnostics)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--owner",
            default=None,
            help=(
                "Corporation name (or substring) of the StructureOwner to check. "
                "If omitted and only one owner exists, that one is used automatically."
            ),
        )
        parser.add_argument(
            "--flag",
            default=None,
            metavar="LOCATION_FLAG",
            help="Print all items with this specific location_flag (e.g. MoonMaterialBay).",
        )
        parser.add_argument(
            "--metenox-only",
            action="store_true",
            help=(
                "Only show items whose location_id matches a known Metenox structure_id "
                "from the database.  Useful to see what is actually stored inside each Metenox."
            ),
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        from moonmaster.models import Structure, StructureOwner
        from moonmaster.providers import SCOPE_ASSETS, esi_authed_get
        from moonmaster.constants import STRUCTURE_TYPE_METENOX

        # ── Resolve owner ──────────────────────────────────────────────
        qs = StructureOwner.objects.all()
        owner_filter = options["owner"]
        if owner_filter:
            qs = qs.filter(corporation__corporation_name__icontains=owner_filter)
        owners = list(qs)
        if not owners:
            raise CommandError(
                "No StructureOwner found"
                + (f" matching '{owner_filter}'" if owner_filter else "")
                + ".  Add an owner via the moonmaster UI first."
            )
        if len(owners) > 1:
            names = ", ".join(str(o) for o in owners)
            raise CommandError(
                f"Multiple owners matched: {names}. Use --owner to narrow down."
            )
        owner = owners[0]
        self.stdout.write(self.style.SUCCESS(f"Owner: {owner}"))

        # ── Get ESI token ──────────────────────────────────────────────
        token = owner.get_token([SCOPE_ASSETS])
        if not token:
            raise CommandError(
                f"No valid ESI token with scope '{SCOPE_ASSETS}' found for {owner}. "
                "Re-add the owner via the UI to grant the assets scope."
            )
        self.stdout.write(f"Token character: {getattr(token, 'character_id', 'unknown')}")

        # ── Fetch all corp assets ──────────────────────────────────────
        corp_id = owner.corporation.corporation_id
        self.stdout.write(f"Fetching /corporations/{corp_id}/assets/ …")
        try:
            assets = esi_authed_get(f"/corporations/{corp_id}/assets/", token)
        except Exception as exc:
            raise CommandError(f"ESI assets fetch failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Total assets returned by ESI: {len(assets)}"))

        if not assets:
            self.stdout.write(self.style.WARNING("ESI returned zero assets — nothing to analyse."))
            return

        # ── Known Metenox structure IDs from DB ────────────────────────
        metenox_sids = set(
            Structure.objects.filter(
                owner=owner, structure_type=STRUCTURE_TYPE_METENOX
            ).values_list("structure_id", flat=True)
        )
        self.stdout.write(f"Known Metenox structure_ids in DB: {sorted(metenox_sids) or '(none)'}")

        # ── Flag breakdown ─────────────────────────────────────────────
        flag_counter: Counter = Counter()
        for a in assets:
            flag_counter[a.get("location_flag", "(missing)")] += 1

        self.stdout.write("\n── location_flag breakdown (all assets) ──")
        for flag, count in flag_counter.most_common():
            marker = " ← CHECK THIS" if "moon" in flag.lower() or "material" in flag.lower() else ""
            self.stdout.write(f"  {flag:<40s}  {count:>6d}{marker}")

        # ── Metenox-scoped items ───────────────────────────────────────
        if metenox_sids:
            metenox_items = [a for a in assets if a.get("location_id") in metenox_sids]
            flag_metenox: Counter = Counter()
            for a in metenox_items:
                flag_metenox[a.get("location_flag", "(missing)")] += 1

            self.stdout.write(
                f"\n── location_flag breakdown for items INSIDE known Metenox structures "
                f"(location_id ∈ {{{', '.join(str(s) for s in sorted(metenox_sids))}}}) ──"
            )
            if flag_metenox:
                for flag, count in flag_metenox.most_common():
                    self.stdout.write(f"  {flag:<40s}  {count:>6d}")
                self.stdout.write(
                    "\n  ↑ These are the location_flag values the task must filter on "
                    "to read the goo bay contents.  If 'MoonMaterialBay' is absent here, "
                    "update the filter in moonmaster/tasks.py → _sync_metenox_bays."
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "  No ESI assets have location_id matching any known Metenox "
                        "structure_id.  This means ESI is NOT placing items inside the "
                        "Metenox by structure_id, OR the structure_ids in the DB do not "
                        "match the item_ids in the ESI assets response.\n"
                        "\n"
                        "  ESI item_ids of any Metenox-type assets in the response:"
                    )
                )
                # Show Metenox-type assets (type_id == 81826) so we can compare item_ids
                # with the structure_ids stored in the DB.
                METENOX_TYPE_ID = 81826
                metenox_asset_rows = [a for a in assets if a.get("type_id") == METENOX_TYPE_ID]
                if metenox_asset_rows:
                    self.stdout.write(f"  {'item_id':<20s} {'location_id':<20s} {'location_flag'}")
                    for a in metenox_asset_rows:
                        self.stdout.write(
                            f"  {a.get('item_id', '?'):<20} "
                            f"{a.get('location_id', '?'):<20} "
                            f"{a.get('location_flag', '?')}"
                        )
                    self.stdout.write(
                        "\n  Compare the item_ids above against the DB structure_ids. "
                        "If they differ, the task's bay_volumes.get(structure_id) lookup "
                        "will always miss."
                    )
                else:
                    self.stdout.write(
                        "  No assets with type_id=81826 (Metenox) found in ESI response."
                    )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\nNo Metenox structures in DB for this owner — run a structure sync first."
                )
            )

        # ── Filter by specific flag ────────────────────────────────────
        target_flag = options["flag"]
        if target_flag:
            flagged = [a for a in assets if a.get("location_flag") == target_flag]
            self.stdout.write(f"\n── Items with location_flag='{target_flag}' ({len(flagged)}) ──")
            if flagged:
                self.stdout.write(f"  {'item_id':<20s} {'type_id':<12s} {'quantity':<10s} {'location_id'}")
                for a in flagged[:100]:  # cap at 100 rows
                    self.stdout.write(
                        f"  {a.get('item_id', '?'):<20} "
                        f"{a.get('type_id', '?'):<12} "
                        f"{a.get('quantity', '?'):<10} "
                        f"{a.get('location_id', '?')}"
                    )
                if len(flagged) > 100:
                    self.stdout.write(f"  … (showing first 100 of {len(flagged)})")
            else:
                self.stdout.write(self.style.WARNING(f"  No items found with that flag."))

        # ── Metenox-only detailed view ─────────────────────────────────
        if options["metenox_only"] and metenox_sids:
            metenox_items = [a for a in assets if a.get("location_id") in metenox_sids]
            self.stdout.write(
                f"\n── All {len(metenox_items)} items inside Metenox structures ──"
            )
            if metenox_items:
                self.stdout.write(
                    f"  {'location_id':<20s} {'item_id':<20s} {'type_id':<12s} "
                    f"{'quantity':<10s} {'location_flag'}"
                )
                for a in sorted(metenox_items, key=lambda x: x.get("location_id", 0)):
                    self.stdout.write(
                        f"  {a.get('location_id', '?'):<20} "
                        f"{a.get('item_id', '?'):<20} "
                        f"{a.get('type_id', '?'):<12} "
                        f"{a.get('quantity', '?'):<10} "
                        f"{a.get('location_flag', '?')}"
                    )
            else:
                self.stdout.write(self.style.WARNING("  No items found inside Metenox structures."))

        self.stdout.write(self.style.SUCCESS("\nDone."))
