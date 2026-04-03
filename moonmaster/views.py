import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from esi.decorators import token_required

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from .calculator import MoonProfitCalculator
from .models import Extraction, Moon, Structure, StructureOwner, TaxConfig
from .constants import PRICE_SOURCE_ESI, STRUCTURE_TYPE_METENOX


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


# ---------------------------------------------------------------------------
# Main views
# ---------------------------------------------------------------------------

@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def dashboard(request):
    context = {
        "moon_count": Moon.objects.count(),
        "structure_count": Structure.objects.count(),
        "metenox_count": Structure.objects.filter(structure_type=STRUCTURE_TYPE_METENOX).count(),
        "upcoming_extractions": Extraction.objects.filter(
            status__in=[Extraction.Status.SCHEDULED, Extraction.Status.READY]
        ).select_related("structure__moon").order_by("chunk_arrival_time")[:10],
        "low_fuel_structures": Structure.objects.filter(
            structure_type=STRUCTURE_TYPE_METENOX,
            is_online=True,
        ).select_related("moon").order_by("fuel_expires")[:10],
    }
    return render(request, "moonmaster/dashboard.html", context)


@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def moon_list(request):
    moons = Moon.objects.all().order_by("solar_system_name", "name")
    context = {"moons": moons}
    return render(request, "moonmaster/moon_list.html", context)


@login_required
@permission_required("moonmaster.basic_access", raise_exception=True)
def moon_detail(request, moon_id):
    moon = get_object_or_404(Moon, pk=moon_id)
    tax_config = _get_tax_config(request.user)
    fleet_share_pct = float(request.GET.get("fleet_share", 0.0))

    calculator = MoonProfitCalculator(
        moon=moon,
        tax_config=tax_config,
        fleet_share_pct=fleet_share_pct,
    )
    table = calculator.comparison_table()

    context = {
        "moon": moon,
        "structures": moon.structures.select_related("owner__corporation"),
        "extractions": moon.structures.prefetch_related(
            "extractions"
        ),
        "table": table,
        "fleet_share_pct": fleet_share_pct,
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
