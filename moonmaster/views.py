import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from esi.decorators import token_required

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from .calculator import MoonProfitCalculator
from .models import Extraction, Moon, Structure, StructureOwner, TaxConfig
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
    sorted by fraction descending.  Each dict has: name, type_id, fraction, rarity, tier.
    """
    from .constants import MOON_ORE_NAMES, MOON_ORE_RARITY, RARITY_TIER_LABEL
    rows = []
    for tid_str, frac in moon.ore_composition.items():
        tid = int(tid_str)
        rarity = MOON_ORE_RARITY.get(tid, "")
        rows.append({
            "name": MOON_ORE_NAMES.get(tid, f"Unknown ({tid})"),
            "type_id": tid,
            "fraction": frac,
            "rarity": rarity,
            "tier": RARITY_TIER_LABEL.get(rarity, ""),
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
        moon_rows.append({
            "moon": moon,
            "drill_net": int(tbl.drill.net_isk_per_month) if tbl.drill else 0,
            "metenox_net": int(tbl.metenox.net_isk_per_month) if tbl.metenox else 0,
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
    qs = Extraction.objects.select_related(
        "structure__moon", "structure__owner__corporation"
    ).order_by("-chunk_arrival_time")
    context = {"extractions": qs[:200]}
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
        "corporation", "character"
    ).order_by("corporation__corporation_name")
    context = {"owners": owners}
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
        # Update the registered character if a new person re-registered
        owner.character = char
        owner.is_active = True
        owner.save(update_fields=["character", "is_active"])

    # Ensure a TaxConfig exists
    TaxConfig.objects.get_or_create(owner=owner)

    action = "registered" if created else "updated"
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
