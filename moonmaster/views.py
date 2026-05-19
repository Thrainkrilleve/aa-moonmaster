import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from esi.decorators import token_required

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from .calculator import MoonProfitCalculator
from .models import (
    DrillOwnership, DrillTaxPaymentConfig, DrillTaxRecord,
    Extraction, Moon, OwnerCharacter, Structure, StructureOwner, TaxConfig,
)
from .constants import PRICE_SOURCE_ESI, STRUCTURE_TYPE_METENOX, STRUCTURE_TYPE_ATHANOR, REINFORCE_STATES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_tax_config(user):
    """Return the TaxConfig for the first StructureOwner associated with the user's corp, or None."""
    try:
        owner = StructureOwner.objects.get(
            corporation__corporation_id=user.profile.main_character.corporation_id
        )
        return owner.tax_config
    except Exception:
        return None


def _build_ore_rows(moon):
    """
    Return a list of dicts for the ore composition table on moon_detail,
    sorted by fraction descending.  Each dict has: name, type_id, fraction,
    rarity, tier, quantity (units per 30-day Athanor drill month).
    """
    from .constants import (
        MOON_ORE_NAMES, MOON_ORE_RARITY, RARITY_TIER_LABEL,
        MOON_ORE_VOLUME_M3, MOON_ORE_VOLUME_DEFAULT_M3,
        MOONMINING_VOLUME_PER_DAY, MOONMINING_DAYS_PER_MONTH,
    )
    total_monthly_m3 = MOONMINING_VOLUME_PER_DAY * MOONMINING_DAYS_PER_MONTH
    rows = []
    for tid_str, frac in moon.ore_composition.items():
        tid = int(tid_str)
        rarity = MOON_ORE_RARITY.get(tid, "")
        ore_vol = MOON_ORE_VOLUME_M3.get(tid, MOON_ORE_VOLUME_DEFAULT_M3)
        quantity = int(frac * total_monthly_m3 / ore_vol) if ore_vol else 0
        rows.append({
            "name": MOON_ORE_NAMES.get(tid, f"Unknown ({tid})"),
            "type_id": tid,
            "fraction": frac,
            "rarity": rarity,
            "tier": RARITY_TIER_LABEL.get(rarity, ""),
            "quantity": quantity,
        })
    rows.sort(key=lambda r: -r["fraction"])
    return rows


# ---------------------------------------------------------------------------
# Main views
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def dashboard(request):
    reinforce_list = list(
        Structure.objects.filter(state__in=list(REINFORCE_STATES))
        .select_related("moon", "owner__corporation")
        .order_by("state")  # hull_reinforce sorts before armor_reinforce alphabetically
    )
    fuel_critical = list(
        Structure.objects.filter(
            fuel_expires__isnull=False,
            fuel_expires__lte=timezone.now() + timedelta(hours=48),
        ).select_related("moon", "owner__corporation").order_by("fuel_expires")
    )
    context = {
        "moon_count": Moon.objects.count(),
        "structure_count": Structure.objects.count(),
        "metenox_count": Structure.objects.filter(structure_type=STRUCTURE_TYPE_METENOX).count(),
        "reinforce_count": len(reinforce_list),
        "reinforce_structures": reinforce_list,
        "fuel_critical": fuel_critical,
        "upcoming_extractions": Extraction.objects.filter(
            status__in=[Extraction.Status.SCHEDULED, Extraction.Status.READY]
        ).select_related("structure__moon").order_by("chunk_arrival_time")[:10],
        "low_fuel_structures": Structure.objects.filter(
            structure_type=STRUCTURE_TYPE_METENOX,
            is_online=True,
            fuel_expires__isnull=False,
            fuel_expires__lte=timezone.now() + timedelta(days=7),
        ).select_related("moon").order_by("fuel_expires")[:10],
    }
    return render(request, "moonmaster/dashboard.html", context)


@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def moon_list(request):
    moons = Moon.objects.prefetch_related("structures").order_by("solar_system_name", "name")
    tax_config = _get_tax_config(request.user)
    moon_rows = []
    for moon in moons:
        calc = MoonProfitCalculator(moon=moon, tax_config=tax_config)
        tbl = calc.comparison_table()
        structure_types = {s.structure_type for s in moon.structures.all()}
        moon_rows.append({
            "moon": moon,
            "drill_net": int(tbl.drill.net_isk_per_month) if tbl.drill else 0,
            "metenox_net": int(tbl.metenox.net_isk_per_month) if tbl.metenox else 0,
            "has_athanor": STRUCTURE_TYPE_ATHANOR in structure_types,
            "has_metenox": STRUCTURE_TYPE_METENOX in structure_types,
        })
    moon_rows.sort(key=lambda r: r["metenox_net"], reverse=True)
    context = {"moon_rows": moon_rows}
    return render(request, "moonmaster/moon_list.html", context)


@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def moon_detail(request, moon_id):
    moon = get_object_or_404(Moon, pk=moon_id)
    tax_config = _get_tax_config(request.user)
    fleet_share_pct = float(request.GET.get("fleet_share", 0.0))

    # Use fuel from linked Athanor structures; fall back to SDE default (5 blocks/hr)
    from .constants import ATHANOR_FUEL_BLOCKS_PER_HOUR_DEFAULT, STRUCTURE_TYPE_ATHANOR
    athanor_fuel = max(
        (s.fuel_blocks_per_hour for s in moon.structures.filter(structure_type=STRUCTURE_TYPE_ATHANOR)
         if s.fuel_blocks_per_hour > 0),
        default=float(ATHANOR_FUEL_BLOCKS_PER_HOUR_DEFAULT),
    )

    calculator = MoonProfitCalculator(
        moon=moon,
        tax_config=tax_config,
        fleet_share_pct=fleet_share_pct,
        price_source="fuzzwork",
        athanor_fuel_blocks_per_hour=athanor_fuel,
    )
    table = calculator.comparison_table()

    context = {
        "moon": moon,
        "structures": moon.structures.select_related("owner__corporation"),
        "extractions": Extraction.objects.filter(
            structure__moon=moon,
        ).select_related("structure__owner__corporation").order_by("-chunk_arrival_time")[:20],
        "table": table,
        "fleet_share_pct": fleet_share_pct,
        "ore_rows": _build_ore_rows(moon),
    }
    return render(request, "moonmaster/moon_detail.html", context)


@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def extractions(request):
    status_filter = request.GET.get("filter", "active")

    qs = Extraction.objects.select_related(
        "structure__moon", "structure__owner__corporation"
    )

    if status_filter == "active":
        qs = qs.filter(
            status__in=[Extraction.Status.SCHEDULED, Extraction.Status.READY]
        ).order_by("chunk_arrival_time")   # soonest first for active view
    else:
        qs = qs.order_by("-chunk_arrival_time")

    owners = StructureOwner.objects.select_related("corporation").order_by(
        "corporation__corporation_name"
    )
    total_count = Extraction.objects.count()
    active_count = Extraction.objects.filter(
        status__in=[Extraction.Status.SCHEDULED, Extraction.Status.READY]
    ).count()

    context = {
        "extractions": qs[:200],
        "owners": owners,
        "status_filter": status_filter,
        "total_count": total_count,
        "active_count": active_count,
    }
    return render(request, "moonmaster/extractions.html", context)


@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def metenox_list(request):
    structures = Structure.objects.filter(
        structure_type=STRUCTURE_TYPE_METENOX
    ).select_related("moon", "owner__corporation").order_by("moon__solar_system_name")
    context = {"structures": structures}
    return render(request, "moonmaster/metenox_list.html", context)


@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def structure_list(request):
    """Unified view of all tracked structures (Athanor + Metenox) with full status."""
    structures = (
        Structure.objects
        .select_related("moon", "owner__corporation")
        .order_by("owner__corporation__corporation_name", "name")
    )
    reinforce_count = sum(1 for s in structures if s.is_reinforced)
    fuel_critical_count = sum(
        1 for s in structures
        if s.fuel_expires and (s.fuel_expires - timezone.now()).total_seconds() < 48 * 3600
    )
    context = {
        "structures": structures,
        "reinforce_count": reinforce_count,
        "fuel_critical_count": fuel_critical_count,
    }
    return render(request, "moonmaster/structure_list.html", context)


@login_required
@permission_required("moonmaster.view_reports", raise_exception=True)
def reports(request):
    moons = Moon.objects.all()
    tax_config = _get_tax_config(request.user)
    rows = []
    for moon in moons:
        calc = MoonProfitCalculator(moon=moon, tax_config=tax_config)
        table = calc.comparison_table()
        rows.append({"moon": moon, "table": table})
    rows.sort(key=lambda r: r["table"].metenox.net_isk_per_month if r["table"].metenox else 0, reverse=True)
    context = {"rows": rows}
    return render(request, "moonmaster/reports.html", context)


# ---------------------------------------------------------------------------
# JSON / AJAX endpoints
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def moon_profitability_api(request, moon_id):
    moon = get_object_or_404(Moon, pk=moon_id)
    fleet_share_pct = float(request.GET.get("fleet_share", 0.0))
    tax_config = _get_tax_config(request.user)
    calc = MoonProfitCalculator(moon=moon, tax_config=tax_config, fleet_share_pct=fleet_share_pct)
    return JsonResponse(calc.to_dict())


@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
@require_POST
def refresh_prices_api(request):
    """Trigger an immediate price refresh (manual override)."""
    from .tasks import update_prices
    update_prices.delay()
    return JsonResponse({"status": "queued"})


# ---------------------------------------------------------------------------
# Owner management
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
def manage_owners(request):
    owners = StructureOwner.objects.select_related(
        "corporation", "character",
    ).prefetch_related(
        "owner_characters__character",
    ).order_by("corporation__corporation_name")

    context = {"owners": owners}

    # Drill ownership management (separate permission)
    if request.user.has_perm("moonmaster.manage_drill_tax"):
        drill_ownerships = (
            DrillOwnership.objects.select_related(
                "structure__moon", "structure__owner__corporation", "character"
            ).order_by("character__character_name", "structure__name")
        )
        # Metenox structures not yet assigned
        assigned_ids = drill_ownerships.values_list("structure_id", flat=True)
        unassigned_metenox = (
            Structure.objects.filter(structure_type=STRUCTURE_TYPE_METENOX)
            .exclude(pk__in=assigned_ids)
            .select_related("moon", "owner__corporation")
            .order_by("name")
        )
        all_metenox = Structure.objects.filter(
            structure_type=STRUCTURE_TYPE_METENOX
        ).select_related("moon", "owner__corporation").order_by("name")
        eve_characters = EveCharacter.objects.order_by("character_name")
        payment_configs = DrillTaxPaymentConfig.objects.select_related(
            "owner__corporation"
        ).order_by("owner__corporation__corporation_name")
        context.update({
            "drill_ownerships": drill_ownerships,
            "unassigned_metenox": unassigned_metenox,
            "all_metenox": all_metenox,
            "eve_characters": eve_characters,
            "payment_configs": payment_configs,
            "corp_owners": StructureOwner.objects.select_related("corporation").order_by(
                "corporation__corporation_name"
            ),
        })

    return render(request, "moonmaster/manage_owners.html", context)


@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
@token_required(scopes=[
    "esi-corporations.read_structures.v1",
    "esi-industry.read_corporation_mining.v1",
    "esi-universe.read_structures.v1",
    "esi-assets.read_corporation_assets.v1",
])
def add_owner(request, token):
    """
    Receive the ESI token from the SSO flow, derive the corp, and register
    a StructureOwner.  ``@token_required`` injects the saved Token as the
    second positional argument.
    """
    try:
        char = EveCharacter.objects.get_character_by_id(token.character_id)
        if char is None:
            char = EveCharacter.objects.create_character(token.character_id)
        corp_id = char.corporation_id
        try:
            corporation = EveCorporationInfo.objects.get(corporation_id=corp_id)
        except EveCorporationInfo.DoesNotExist:
            corporation = EveCorporationInfo.objects.create_corporation(corp_id)
    except Exception as exc:
        messages.error(
            request,
            f"Could not resolve corporation from ESI token: {exc}",
        )
        return redirect("moonmaster:manage_owners")

    owner, created = StructureOwner.objects.get_or_create(
        corporation=corporation,
        defaults={"character": char, "is_active": True},
    )
    if not created:
        owner.is_active = True
        owner.save(update_fields=["is_active"])

    # Register this character as a fallback manager
    oc, oc_created = OwnerCharacter.objects.get_or_create(
        owner=owner,
        character=char,
        defaults={"is_primary": not owner.owner_characters.filter(is_primary=True).exists()},
    )
    # Keep legacy character field pointing to the most recently used manager
    if owner.character_id != char.pk:
        owner.character = char
        owner.save(update_fields=["character"])

    # Ensure a TaxConfig exists
    TaxConfig.objects.get_or_create(owner=owner)

    if created:
        action = "registered"
    elif oc_created:
        action = "updated — new manager character added"
    else:
        action = "already registered"
    messages.success(
        request,
        f"Corporation {corporation.corporation_name} {action} as a Moon Master owner.",
    )
    return redirect("moonmaster:manage_owners")


@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
@require_POST
def remove_owner(request, owner_id):
    owner = get_object_or_404(StructureOwner, pk=owner_id)
    corp_name = str(owner.corporation.corporation_name)
    owner.delete()
    messages.success(request, f"Removed {corp_name} from Moon Master.")
    return redirect("moonmaster:manage_owners")


@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
@require_POST
def remove_owner_character(request, pk):
    """Remove a single manager character from a corporation's fallback list."""
    oc = get_object_or_404(OwnerCharacter, pk=pk)
    corp_name = str(oc.owner.corporation.corporation_name)
    char_name = str(oc.character.character_name)
    removed_char_pk = oc.character_id
    owner = oc.owner
    oc.delete()
    # Keep legacy character field consistent if we just removed the primary
    if owner.character_id == removed_char_pk:
        remaining = owner.owner_characters.select_related("character").first()
        owner.character = remaining.character if remaining else None
        owner.save(update_fields=["character"])
    messages.success(request, f"Removed {char_name} as manager for {corp_name}.")
    return redirect("moonmaster:manage_owners")


# ---------------------------------------------------------------------------
# On-demand sync controls
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
@require_POST
def sync_owner_now(request, owner_id):
    """Queue an immediate ESI sync for a single StructureOwner."""
    from .tasks import sync_owner
    owner = get_object_or_404(StructureOwner, pk=owner_id)
    sync_owner.delay(owner_id=owner.pk)
    messages.success(request, f"Sync queued for {owner.corporation.corporation_name}.")
    return redirect("moonmaster:manage_owners")


@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
@require_POST
def sync_all_now(request):
    """Queue a full sync for all active StructureOwners."""
    from .tasks import update_all_structures, update_extractions
    update_all_structures.delay()
    update_extractions.delay()
    messages.success(request, "Full sync queued for all active owners.")
    return redirect("moonmaster:manage_owners")


# ---------------------------------------------------------------------------
# Tax configuration
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
@require_POST
def update_tax_config(request, owner_id):
    """Save TaxConfig fields for a StructureOwner."""
    import decimal
    owner = get_object_or_404(StructureOwner, pk=owner_id)
    tax, _ = TaxConfig.objects.get_or_create(owner=owner)
    try:
        tax.alliance_tax = float(request.POST.get("alliance_tax") or 0)
        tax.corp_tax = float(request.POST.get("corp_tax") or 0)
        tax.reprocess_tax = float(request.POST.get("reprocess_tax") or 0)
        tax.sov_upkeep_daily_isk = decimal.Decimal(
            str(request.POST.get("sov_upkeep_daily_isk") or "0")
        )
        tax.full_clean()
        tax.save()
        messages.success(
            request, f"Tax config saved for {owner.corporation.corporation_name}."
        )
    except Exception as exc:
        messages.error(request, f"Could not save tax config: {exc}")
    return redirect("moonmaster:manage_owners")


# ---------------------------------------------------------------------------
# Moon survey import
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.manage_moons", raise_exception=True)
def import_survey(request):
    """
    Import moon composition data.  Supports two formats:
      1. In-game moon drill probe-scanner export (tab-separated, TypeID-based).
      2. Spreadsheet export (tab-separated, ore-name + percentage columns).
    """
    if request.method == "POST":
        import_type = request.POST.get("import_type", "scanner")
        raw = request.POST.get("scan_data", "").strip()
        if not raw:
            messages.warning(request, "No scan data provided.")
            return redirect("moonmaster:import_survey")
        if import_type == "spreadsheet":
            from .tasks import process_spreadsheet_survey
            process_spreadsheet_survey.delay(raw, request.user.pk)
        else:
            from .tasks import process_survey
            process_survey.delay(raw, request.user.pk)
        messages.success(
            request,
            "Survey submitted for processing — you'll receive a notification when it's done.",
        )
        return redirect("moonmaster:moon_list")
    return render(request, "moonmaster/import_survey.html", {})


# ---------------------------------------------------------------------------
# Drill owner tax overview
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.view_reports", raise_exception=True)
def drill_tax_overview(request):
    """
    Summary view showing every Metenox drill owner, their drills, estimated
    monthly tax, and outstanding (unpaid) balance.
    """
    from collections import defaultdict
    from decimal import Decimal

    ownerships = (
        DrillOwnership.objects
        .select_related(
            "structure__moon",
            "structure__owner__corporation",
            "character",
        )
        .order_by("character__character_name", "structure__name")
    )

    by_character: dict = defaultdict(lambda: {"ownerships": [], "total_unpaid": Decimal("0")})

    for ownership in ownerships:
        char = ownership.character
        entry = by_character[char.character_id]
        entry["character"] = char

        # Estimated monthly tax from MoonProfitCalculator (based on ore composition)
        monthly_tax_est = Decimal("0")
        if ownership.structure.moon:
            try:
                tax_config = getattr(ownership.structure.owner, "tax_config", None)
            except TaxConfig.DoesNotExist:
                tax_config = None
            try:
                calc = MoonProfitCalculator(ownership.structure.moon, tax_config)
                metenox_result = calc.metenox_profit_per_month()
                monthly_tax_est = metenox_result.gross_isk_per_month * Decimal(str(ownership.tax_rate))
            except Exception:
                monthly_tax_est = Decimal("0")

        # Outstanding (unpaid) ISK balance for this drill
        unpaid = (
            DrillTaxRecord.objects
            .filter(structure=ownership.structure, character=char, is_paid=False)
            .aggregate(total=Sum("tax_owed_isk"))["total"]
        ) or Decimal("0")

        entry["ownerships"].append({
            "ownership": ownership,
            "monthly_tax_est": monthly_tax_est,
            "unpaid_balance": unpaid,
        })
        entry["total_unpaid"] += unpaid

    rows = sorted(by_character.values(), key=lambda x: x["character"].character_name)
    return render(request, "moonmaster/drill_tax_overview.html", {"rows": rows})


# ---------------------------------------------------------------------------
# Drill ownership CRUD
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.manage_drill_tax", raise_exception=True)
@require_POST
def assign_drill_owner(request):
    """Assign a character as the owner of a Metenox structure."""
    structure_id = request.POST.get("structure_id")
    character_id = request.POST.get("character_id")
    tax_rate_pct = request.POST.get("tax_rate_pct", "10")
    notes = request.POST.get("notes", "").strip()

    structure = get_object_or_404(Structure, pk=structure_id, structure_type=STRUCTURE_TYPE_METENOX)
    character = get_object_or_404(EveCharacter, pk=character_id)

    try:
        tax_rate_pct_f = float(tax_rate_pct)
        if not (0 <= tax_rate_pct_f <= 100):
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, "Tax rate must be a number between 0 and 100.")
        return redirect("moonmaster:manage_owners")

    ownership, created = DrillOwnership.objects.update_or_create(
        structure=structure,
        defaults={
            "character": character,
            "tax_rate": tax_rate_pct_f / 100,
            "notes": notes,
        },
    )
    action = "assigned" if created else "updated"
    messages.success(
        request,
        f"{character.character_name} {action} as owner of {structure.name or structure.structure_id}.",
    )
    return redirect("moonmaster:manage_owners")


@login_required
@permission_required("moonmaster.manage_drill_tax", raise_exception=True)
@require_POST
def remove_drill_ownership(request, pk):
    """Remove a drill owner assignment."""
    ownership = get_object_or_404(DrillOwnership, pk=pk)
    name = str(ownership)
    ownership.delete()
    messages.success(request, f"Drill ownership removed: {name}.")
    return redirect("moonmaster:manage_owners")


@login_required
@permission_required("moonmaster.manage_drill_tax", raise_exception=True)
@require_POST
def update_drill_ownership(request, pk):
    """Update tax rate / notes for an existing ownership."""
    ownership = get_object_or_404(DrillOwnership, pk=pk)
    tax_rate_pct = request.POST.get("tax_rate_pct", "")
    notes = request.POST.get("notes", "").strip()

    try:
        tax_rate_pct_f = float(tax_rate_pct)
        if not (0 <= tax_rate_pct_f <= 100):
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, "Tax rate must be 0–100.")
        return redirect("moonmaster:manage_owners")

    ownership.tax_rate = tax_rate_pct_f / 100
    ownership.notes = notes
    ownership.save(update_fields=["tax_rate", "notes", "updated_at"])
    messages.success(request, f"Drill ownership updated for {ownership.character.character_name}.")
    return redirect("moonmaster:manage_owners")


# ---------------------------------------------------------------------------
# Drill tax records — all-records view (view_drill_tax / manage_drill_tax)
# ---------------------------------------------------------------------------

@login_required
def drill_records(request):
    """
    Combined view: summary by character + detailed records table.
    Accessible to users with view_drill_tax or manage_drill_tax.
    """
    from collections import defaultdict
    from decimal import Decimal

    if not (
        request.user.has_perm("moonmaster.view_drill_tax")
        or request.user.has_perm("moonmaster.manage_drill_tax")
    ):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    filter_paid = request.GET.get("paid", "")      # "1" paid, "0" unpaid, "" all
    filter_char = request.GET.get("character", "")

    records_qs = DrillTaxRecord.objects.select_related(
        "structure__moon", "structure__owner__corporation", "character"
    ).order_by("-period_end", "character__character_name")

    if filter_paid == "1":
        records_qs = records_qs.filter(is_paid=True)
    elif filter_paid == "0":
        records_qs = records_qs.filter(is_paid=False)
    if filter_char:
        records_qs = records_qs.filter(character__character_name__icontains=filter_char)

    # Per-character summary (unfiltered totals for the summary panel)
    ownerships = DrillOwnership.objects.select_related(
        "structure__moon", "structure__owner__corporation", "character"
    ).order_by("character__character_name")

    by_character: dict = defaultdict(lambda: {
        "ownerships": [], "total_unpaid": Decimal("0"), "total_paid": Decimal("0"),
    })
    for ownership in ownerships:
        char = ownership.character
        entry = by_character[char.character_id]
        entry["character"] = char

        monthly_tax_est = Decimal("0")
        if ownership.structure.moon:
            try:
                tax_config = getattr(ownership.structure.owner, "tax_config", None)
            except TaxConfig.DoesNotExist:
                tax_config = None
            try:
                calc = MoonProfitCalculator(ownership.structure.moon, tax_config)
                monthly_tax_est = (
                    calc.metenox_profit_per_month().gross_isk_per_month
                    * Decimal(str(ownership.tax_rate))
                )
            except Exception:
                monthly_tax_est = Decimal("0")

        agg = DrillTaxRecord.objects.filter(
            structure=ownership.structure, character=char
        ).aggregate(
            unpaid=Sum("tax_owed_isk", filter=Q(is_paid=False)),
            paid=Sum("tax_owed_isk", filter=Q(is_paid=True)),
        )
        unpaid = agg["unpaid"] or Decimal("0")
        paid = agg["paid"] or Decimal("0")
        entry["ownerships"].append({
            "ownership": ownership,
            "monthly_tax_est": monthly_tax_est,
            "unpaid_balance": unpaid,
        })
        entry["total_unpaid"] += unpaid
        entry["total_paid"] += paid

    summary_rows = sorted(by_character.values(), key=lambda x: x["character"].character_name)
    all_characters = EveCharacter.objects.filter(
        drill_tax_records__isnull=False
    ).distinct().order_by("character_name")

    return render(request, "moonmaster/drill_records.html", {
        "records": records_qs,
        "summary_rows": summary_rows,
        "filter_paid": filter_paid,
        "filter_char": filter_char,
        "all_characters": all_characters,
        "can_manage": request.user.has_perm("moonmaster.manage_drill_tax"),
    })


# ---------------------------------------------------------------------------
# Create / mark paid — require manage_drill_tax
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.manage_drill_tax", raise_exception=True)
def create_drill_tax_record(request):
    """Create a new billing record for a drill owner."""
    from decimal import Decimal, InvalidOperation

    if request.method == "POST":
        structure_id = request.POST.get("structure_id")
        character_id = request.POST.get("character_id")
        period_start = request.POST.get("period_start")
        period_end = request.POST.get("period_end")
        gross_str = request.POST.get("gross_value_isk", "0")
        tax_rate_pct_str = request.POST.get("tax_rate_pct", "10")
        notes = request.POST.get("notes", "").strip()

        errors = []
        try:
            gross = Decimal(gross_str.replace(",", ""))
        except InvalidOperation:
            errors.append("Gross value must be a number.")
            gross = Decimal("0")
        try:
            tax_rate = Decimal(tax_rate_pct_str) / 100
        except InvalidOperation:
            errors.append("Tax rate must be a number 0–100.")
            tax_rate = Decimal("0.10")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            structure = get_object_or_404(Structure, pk=structure_id)
            character = get_object_or_404(EveCharacter, pk=character_id)
            tax_owed = (gross * tax_rate).quantize(Decimal("0.01"))
            DrillTaxRecord.objects.create(
                structure=structure,
                character=character,
                period_start=period_start,
                period_end=period_end,
                gross_value_isk=gross,
                tax_rate=float(tax_rate),
                tax_owed_isk=tax_owed,
                notes=notes,
            )
            messages.success(
                request,
                f"Billing record created: {character.character_name} owes "
                f"{tax_owed:,.0f} ISK for {period_start} – {period_end}.",
            )
            return redirect("moonmaster:drill_records")

    # GET — pre-fill from query params (e.g. from the manage owners page)
    ownerships = DrillOwnership.objects.select_related(
        "structure__moon", "structure__owner__corporation", "character"
    ).order_by("character__character_name", "structure__name")
    all_structures = Structure.objects.filter(
        structure_type=STRUCTURE_TYPE_METENOX
    ).select_related("moon", "owner__corporation").order_by("name")
    all_chars = EveCharacter.objects.order_by("character_name")

    preselect_char = request.GET.get("character", "")
    return render(request, "moonmaster/create_drill_tax_record.html", {
        "ownerships": ownerships,
        "all_structures": all_structures,
        "all_chars": all_chars,
        "preselect_char": preselect_char,
    })


@login_required
@permission_required("moonmaster.manage_drill_tax", raise_exception=True)
@require_POST
def mark_drill_record_paid(request, pk):
    """Mark a single billing record as paid."""
    record = get_object_or_404(DrillTaxRecord, pk=pk)
    if not record.is_paid:
        record.is_paid = True
        record.paid_at = timezone.now()
        record.save(update_fields=["is_paid", "paid_at"])
        messages.success(request, f"Record #{record.pk} marked as paid.")
    return redirect("moonmaster:drill_records")


@login_required
@permission_required("moonmaster.manage_drill_tax", raise_exception=True)
@require_POST
def mark_drill_record_unpaid(request, pk):
    """Revert a billing record to unpaid."""
    record = get_object_or_404(DrillTaxRecord, pk=pk)
    if record.is_paid:
        record.is_paid = False
        record.paid_at = None
        record.save(update_fields=["is_paid", "paid_at"])
        messages.success(request, f"Record #{record.pk} reverted to unpaid.")
    return redirect("moonmaster:drill_records")


# ---------------------------------------------------------------------------
# Drill tax payment config (ESI scanner settings)
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.manage_drill_tax", raise_exception=True)
@require_POST
def update_drill_tax_payment_config(request):
    """Save or update a DrillTaxPaymentConfig for a StructureOwner."""
    owner_pk = request.POST.get("owner_pk")
    keyword = request.POST.get("payment_keyword", "drilling tax").strip() or "drilling tax"
    is_enabled = request.POST.get("is_enabled") == "1"

    owner = get_object_or_404(StructureOwner, pk=owner_pk)
    config, _ = DrillTaxPaymentConfig.objects.update_or_create(
        owner=owner,
        defaults={"payment_keyword": keyword, "is_enabled": is_enabled},
    )
    messages.success(
        request,
        f"Payment scan config saved for {owner.corporation.corporation_name} "
        f"(keyword: '{keyword}', enabled: {is_enabled}).",
    )
    return redirect("moonmaster:manage_owners")


@login_required
@permission_required("moonmaster.manage_drill_tax", raise_exception=True)
@require_POST
def trigger_drill_payment_sync(request):
    """Manually trigger the ESI wallet payment scan."""
    from .tasks import sync_drill_payments

    config_pk = request.POST.get("config_pk")
    if config_pk:
        sync_drill_payments.delay(config_pk=int(config_pk))
    else:
        sync_drill_payments.delay()
    messages.success(request, "Payment scan queued — results will appear shortly.")
    return redirect("moonmaster:manage_owners")


# ---------------------------------------------------------------------------
# My Drill Records — for individual drill owners
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def my_drill_records(request):
    """
    Personal view for drill owners to see their own billing records.
    Visible to any user with basic_access; shows only their own records.
    """
    from decimal import Decimal

    main = getattr(getattr(request.user, "profile", None), "main_character", None)
    if main is None:
        return render(request, "moonmaster/my_drill_records.html", {
            "records": [], "summary": {}, "no_main": True,
        })

    # Find all EveCharacter objects that belong to this user's linked characters
    try:
        linked_ids = list(
            request.user.character_ownerships.values_list(
                "character__character_id", flat=True
            )
        )
    except Exception:
        linked_ids = [main.character_id]

    records = DrillTaxRecord.objects.filter(
        character__character_id__in=linked_ids
    ).select_related("structure__moon", "structure__owner__corporation", "character").order_by(
        "-period_end", "structure__name"
    )

    agg = records.aggregate(
        total_unpaid=Sum("tax_owed_isk", filter=Q(is_paid=False)),
        total_paid=Sum("tax_owed_isk", filter=Q(is_paid=True)),
    )
    summary = {
        "total_unpaid": agg["total_unpaid"] or Decimal("0"),
        "total_paid": agg["total_paid"] or Decimal("0"),
    }

    return render(request, "moonmaster/my_drill_records.html", {
        "records": records,
        "summary": summary,
        "no_main": False,
    })

