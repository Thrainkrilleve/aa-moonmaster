"""
Celery tasks for Moon Master.

Schedule (suggested via Django-Q or AA's built-in crontab):
  - update_prices        : every 12 hours
  - update_all_structures: every 1 hour
  - update_extractions   : every 10 minutes
  - send_alerts          : every 10 minutes
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Price refresh
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="moonmaster.tasks.update_prices")
def update_prices(self):
    """
    Refresh OrePrice table for all ore types present in Moon compositions
    plus the Metenox fuel types.
    """
    try:
        from .models import Moon, OrePrice
        from .constants import (
            PRICE_SOURCE_ESI,
            ESI_TYPE_ID_NITROGEN_FUEL_BLOCK,
            ESI_TYPE_ID_HYDROGEN_FUEL_BLOCK,
            ESI_TYPE_ID_HELIUM_FUEL_BLOCK,
            ESI_TYPE_ID_OXYGEN_FUEL_BLOCK,
            ESI_TYPE_ID_MAGMATIC_GAS,
        )
        from .pricing import update_all_prices

        type_id_set = set()
        for moon in Moon.objects.all():
            for tid_str in moon.ore_composition.keys():
                type_id_set.add(int(tid_str))

        # Always include fuel types
        type_id_set.update([
            ESI_TYPE_ID_NITROGEN_FUEL_BLOCK,
            ESI_TYPE_ID_HYDROGEN_FUEL_BLOCK,
            ESI_TYPE_ID_HELIUM_FUEL_BLOCK,
            ESI_TYPE_ID_OXYGEN_FUEL_BLOCK,
            ESI_TYPE_ID_MAGMATIC_GAS,
        ])

        updated = update_all_prices(list(type_id_set), source=PRICE_SOURCE_ESI)
        logger.info("moonmaster.update_prices: updated %d price records.", updated)
    except Exception as exc:
        logger.exception("moonmaster.update_prices failed: %s", exc)
        raise self.retry(exc=exc, countdown=300, max_retries=3)


# ---------------------------------------------------------------------------
# Structure / fuel sync
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="moonmaster.tasks.update_all_structures")
def update_all_structures(self):
    """
    Pull current fuel expiry and goo-bay fill percentage for all tracked
    Metenox structures via ESI.
    """
    try:
        from .models import StructureOwner, Structure
        from .constants import STRUCTURE_TYPE_METENOX

        for owner in StructureOwner.objects.filter(is_active=True):
            _sync_owner_structures(owner)
    except Exception as exc:
        logger.exception("moonmaster.update_all_structures failed: %s", exc)
        raise self.retry(exc=exc, countdown=60, max_retries=3)


def _sync_owner_structures(owner):
    """Pull ESI /corporations/{id}/structures/ and upsert Structure records."""
    from django.utils.dateparse import parse_datetime

    from .constants import STRUCTURE_TYPE_ATHANOR, STRUCTURE_TYPE_METENOX
    from .models import Structure
    from .providers import (
        ATHANOR_TYPE_ID,
        METENOX_TYPE_ID,
        MOON_STRUCTURE_TYPE_IDS,
        SCOPE_STRUCTURES,
        get_valid_token,
        refresh_token,
        esi_authed_get,
        structure_is_online,
    )

    if not owner.character:
        logger.warning("StructureOwner %s has no ESI character set — skipping.", owner)
        return

    token = get_valid_token(owner.character.character_id, [SCOPE_STRUCTURES])
    if not token:
        msg = f"No valid ESI token with scope {SCOPE_STRUCTURES} for {owner.character}."
        logger.warning(msg)
        owner.sync_error = msg
        owner.last_sync = timezone.now()
        owner.save(update_fields=["last_sync", "sync_error"])
        return

    if not refresh_token(token):
        msg = f"Token for {owner.character} is expired/invalid."
        logger.warning(msg)
        owner.sync_error = msg
        owner.last_sync = timezone.now()
        owner.save(update_fields=["last_sync", "sync_error"])
        return

    corp_id = owner.corporation.corporation_id
    try:
        structures = esi_authed_get(f"/corporations/{corp_id}/structures/", token)
    except Exception as exc:
        msg = f"ESI structures fetch failed for {owner}: {exc}"
        logger.exception(msg)
        owner.sync_error = msg
        owner.last_sync = timezone.now()
        owner.save(update_fields=["last_sync", "sync_error"])
        return

    updated = 0
    for s in structures:
        type_id = s.get("type_id")
        if type_id not in MOON_STRUCTURE_TYPE_IDS:
            continue

        structure_type = (
            STRUCTURE_TYPE_METENOX if type_id == METENOX_TYPE_ID else STRUCTURE_TYPE_ATHANOR
        )
        fuel_str = s.get("fuel_expires")
        fuel_expires = parse_datetime(fuel_str) if fuel_str else None
        is_online = structure_is_online(s.get("state", ""))
        system_id = s.get("system_id")

        obj, _ = Structure.objects.update_or_create(
            structure_id=s["structure_id"],
            defaults={
                "owner": owner,
                "name": s.get("name", ""),
                "structure_type": structure_type,
                "is_online": is_online,
                "fuel_expires": fuel_expires,
            },
        )
        if obj.moon_id is None:
            _try_link_structure_to_moon(obj, system_id, token)
        updated += 1

    logger.info("_sync_owner_structures: %s — updated %d structure(s).", owner, updated)
    owner.last_sync = timezone.now()
    owner.sync_error = ""
    owner.save(update_fields=["last_sync", "sync_error"])


# ---------------------------------------------------------------------------
# Extraction sync
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="moonmaster.tasks.update_extractions")
def update_extractions(self):
    """
    Fetch upcoming moon extraction events from ESI for all active owners
    and update/create Extraction records.
    """
    try:
        from .models import StructureOwner

        for owner in StructureOwner.objects.filter(is_active=True):
            _sync_owner_extractions(owner)
    except Exception as exc:
        logger.exception("moonmaster.update_extractions failed: %s", exc)
        raise self.retry(exc=exc, countdown=60, max_retries=3)


def _sync_owner_extractions(owner):
    """Pull ESI /corporations/{id}/mining/extractions/ and upsert Extraction records."""
    from django.utils.dateparse import parse_datetime

    from .constants import STRUCTURE_TYPE_ATHANOR
    from .models import Extraction, Structure
    from .providers import (
        SCOPE_MINING,
        get_valid_token,
        refresh_token,
        esi_authed_get,
        get_or_create_moon,
    )

    if not owner.character:
        logger.warning("StructureOwner %s has no ESI character set — skipping.", owner)
        return

    token = get_valid_token(owner.character.character_id, [SCOPE_MINING])
    if not token:
        msg = f"No valid ESI token with scope {SCOPE_MINING} for {owner.character}."
        logger.warning(msg)
        owner.sync_error = msg
        owner.last_sync = timezone.now()
        owner.save(update_fields=["last_sync", "sync_error"])
        return

    if not refresh_token(token):
        msg = f"Token for {owner.character} is expired/invalid."
        logger.warning(msg)
        owner.sync_error = msg
        owner.last_sync = timezone.now()
        owner.save(update_fields=["last_sync", "sync_error"])
        return

    corp_id = owner.corporation.corporation_id
    try:
        extractions = esi_authed_get(f"/corporations/{corp_id}/mining/extractions/", token)
    except Exception as exc:
        msg = f"ESI extractions fetch failed for {owner}: {exc}"
        logger.exception(msg)
        owner.sync_error = msg
        owner.last_sync = timezone.now()
        owner.save(update_fields=["last_sync", "sync_error"])
        return

    now = timezone.now()
    updated = 0
    for ext in extractions:
        moon_id = ext.get("moon_id")
        structure_id = ext.get("structure_id")
        if not moon_id or not structure_id:
            continue

        moon, _ = get_or_create_moon(moon_id)

        structure, _ = Structure.objects.get_or_create(
            structure_id=structure_id,
            defaults={
                "owner": owner,
                "moon": moon,
                "structure_type": STRUCTURE_TYPE_ATHANOR,
            },
        )
        # Backfill moon if it was created without one (from structures sync)
        if structure.moon is None:
            structure.moon = moon
            structure.save(update_fields=["moon"])

        chunk_arrival = parse_datetime(ext["chunk_arrival_time"])
        status = (
            Extraction.Status.READY
            if chunk_arrival and chunk_arrival <= now
            else Extraction.Status.SCHEDULED
        )

        Extraction.objects.update_or_create(
            structure=structure,
            extraction_start_time=parse_datetime(ext["extraction_start_time"]),
            defaults={
                "chunk_arrival_time": chunk_arrival,
                "natural_decay_time": parse_datetime(ext["natural_decay_time"]),
                "status": status,
            },
        )
        updated += 1

    logger.info("_sync_owner_extractions: %s — updated %d extraction(s).", owner, updated)
    owner.last_sync = timezone.now()
    owner.sync_error = ""
    owner.save(update_fields=["last_sync", "sync_error"])


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="moonmaster.tasks.send_alerts")
def send_alerts(self):
    """
    Check for alert conditions and dispatch Discord webhook notifications:
      - Metenox fuel expiring within 24 h
      - Goo bay above 80% full
      - Extraction chunk arriving within 1 h
    """
    try:
        from .models import Structure, Extraction
        from .constants import STRUCTURE_TYPE_METENOX

        now = timezone.now()
        soon = now + timedelta(hours=24)
        very_soon = now + timedelta(hours=1)

        # --- Fuel low ---
        low_fuel = Structure.objects.filter(
            structure_type=STRUCTURE_TYPE_METENOX,
            fuel_expires__lte=soon,
            is_online=True,
        )
        for structure in low_fuel:
            _send_discord_alert(
                structure.owner,
                f"⛽ **Fuel Low** — {structure} fuel expires "
                f"{structure.fuel_expires.strftime('%Y-%m-%d %H:%M')} UTC",
            )

        # --- Goo bay filling ---
        full_bay = Structure.objects.filter(
            structure_type=STRUCTURE_TYPE_METENOX,
            goo_bay_fill_pct__gte=80,
            is_online=True,
        )
        for structure in full_bay:
            _send_discord_alert(
                structure.owner,
                f"🪣 **Goo Bay {structure.goo_bay_fill_pct:.0f}% Full** — {structure}",
            )

        # --- Extraction ready ---
        due_extractions = Extraction.objects.filter(
            status=Extraction.Status.SCHEDULED,
            chunk_arrival_time__lte=very_soon,
        ).select_related("structure__owner")
        for extraction in due_extractions:
            _send_discord_alert(
                extraction.structure.owner,
                f"⛏️ **Extraction Ready** — {extraction.structure.moon} chunk arrives "
                f"{extraction.chunk_arrival_time.strftime('%Y-%m-%d %H:%M')} UTC",
            )

    except Exception as exc:
        logger.exception("moonmaster.send_alerts failed: %s", exc)
        raise self.retry(exc=exc, countdown=60, max_retries=3)


def _send_discord_alert(owner, message: str):
    """
    POST a Discord webhook message for the given StructureOwner.

    The webhook URL is stored in a (future) DiscordWebhookConfig model
    or in Django settings as MOONMASTER_DISCORD_WEBHOOK_URL.
    """
    import requests
    from django.conf import settings

    webhook_url = getattr(settings, "MOONMASTER_DISCORD_WEBHOOK_URL", None)
    if not webhook_url:
        logger.debug("No MOONMASTER_DISCORD_WEBHOOK_URL configured; skipping alert: %s", message)
        return

    try:
        resp = requests.post(
            webhook_url,
            json={"content": message},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Discord alert failed for owner %s: %s", owner, exc)


# ---------------------------------------------------------------------------
# Moon survey import (async — avoids HTTP gateway timeouts)
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="moonmaster.tasks.process_survey")
def process_survey(self, raw: str, user_id: int):
    """
    Parse and import a raw moon drill scan export in the background.
    Sends the requesting user an AA notification on completion.
    """
    try:
        from .providers import get_or_create_moon
        from .constants import MOON_ORE_RARITY, RARITY_UBIQUITOUS

        created = updated = 0
        errors: list = []
        moon_rows: dict = {}

        for lineno, line in enumerate(raw.splitlines(), 1):
            line = line.rstrip("\r")
            if not line.strip():
                continue
            cols = line.split("\t")
            # Skip header and moon-name rows (non-empty first column)
            if cols[0].strip():
                continue
            if len(cols) < 7:
                errors.append(f"Line {lineno}: expected 7 columns, got {len(cols)}")
                continue
            try:
                moon_id = int(cols[6])    # MoonID
                type_id = int(cols[3])    # Ore TypeID
                quantity = float(cols[2]) # Quantity / fraction
            except (ValueError, IndexError) as exc:
                errors.append(f"Line {lineno}: {exc}")
                continue
            if moon_id not in moon_rows:
                moon_rows[moon_id] = {"composition": {}}
            moon_rows[moon_id]["composition"][str(type_id)] = quantity

        _rank = {"ubiquitous": 0, "common": 1, "uncommon": 2, "rare": 3, "exceptional": 4}

        def _infer_rarity(composition):
            best = RARITY_UBIQUITOUS
            for tid_str in composition:
                rarity = MOON_ORE_RARITY.get(int(tid_str))
                if rarity and _rank.get(rarity, 0) > _rank.get(best, 0):
                    best = rarity
            return best

        for moon_id, data in moon_rows.items():
            moon, was_created = get_or_create_moon(moon_id)
            total = sum(data["composition"].values())
            normed = (
                {k: v / total for k, v in data["composition"].items()}
                if total > 0 else data["composition"]
            )
            moon.ore_composition = normed
            moon.rarity_class = _infer_rarity(normed)
            moon.save(update_fields=["ore_composition", "rarity_class"])
            if was_created:
                created += 1
            else:
                updated += 1

        # Notify the requesting user via AA's notification system
        try:
            from django.contrib.auth.models import User
            from allianceauth.notifications import notify

            user = User.objects.get(pk=user_id)
            error_summary = (
                f" ({len(errors)} line(s) skipped)" if errors else ""
            )
            notify(
                user=user,
                title="Moon Survey Import Complete",
                message=(
                    f"Import finished: {created} moon(s) created, "
                    f"{updated} updated{error_summary}."
                ),
                level="success" if not errors else "warning",
            )
        except Exception:
            pass  # notification failure shouldn't fail the task

        logger.info(
            "process_survey: created=%d updated=%d errors=%d",
            created, updated, len(errors),
        )

    except Exception as exc:
        logger.exception("moonmaster.process_survey failed: %s", exc)
        raise self.retry(exc=exc, countdown=60, max_retries=2)


# ---------------------------------------------------------------------------
# Per-owner on-demand sync
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="moonmaster.tasks.sync_owner")
def sync_owner(self, owner_id: int):
    """Sync structures and extractions for a single StructureOwner on demand."""
    try:
        from .models import StructureOwner
        owner = StructureOwner.objects.get(pk=owner_id)
        _sync_owner_structures(owner)
        _sync_owner_extractions(owner)
    except Exception as exc:
        logger.exception("moonmaster.sync_owner(%d) failed: %s", owner_id, exc)
        raise self.retry(exc=exc, countdown=30, max_retries=3)


def _try_link_structure_to_moon(structure, system_id, token):
    """
    Attempt to discover which moon a Structure sits on, trying:
      1. ESI /universe/structures/{id}/ (needs esi-universe.read_structures.v1)
      2. Name-substring match against known Moon records (fallback)
    Sets structure.moon and saves when a match is found.
    """
    from .providers import (
        SCOPE_UNIVERSE,
        get_valid_token,
        refresh_token,
        get_structure_info,
        find_moon_for_position,
        get_or_create_moon,
    )
    from .models import Moon

    # --- Attempt 1: position-based lookup via universe scope ---
    uni_token = get_valid_token(token.character_id, [SCOPE_UNIVERSE])
    if uni_token and refresh_token(uni_token):
        info = get_structure_info(structure.structure_id, uni_token)
        if info:
            ss_id = info.get("solar_system_id") or system_id
            pos = info.get("position", {})
            moon_id = find_moon_for_position(
                ss_id,
                float(pos.get("x", 0)),
                float(pos.get("y", 0)),
                float(pos.get("z", 0)),
            )
            if moon_id:
                moon, _ = get_or_create_moon(moon_id)
                structure.moon = moon
                structure.save(update_fields=["moon"])
                logger.info(
                    "Linked structure %s → %s via position lookup",
                    structure.structure_id, moon,
                )
                return

    # --- Attempt 2: name-substring match against known Moon records ---
    if structure.name:
        for moon in Moon.objects.all():
            if moon.name and moon.name in structure.name:
                structure.moon = moon
                structure.save(update_fields=["moon"])
                logger.info(
                    "Linked structure %s → %s via name heuristic",
                    structure.structure_id, moon,
                )
                return

    logger.debug(
        "Could not link structure %s (id=%s) to any moon.",
        structure, structure.structure_id,
    )
