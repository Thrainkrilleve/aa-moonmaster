"""
Celery tasks for Moon Master.

Schedule (suggested via Django-Q or AA's built-in crontab):
  - update_prices        : every 12 hours
  - update_all_structures: every 1 hour
  - update_extractions   : every 10 minutes
  - send_alerts          : every 10 minutes
  - sync_mining_ledger   : every 1 hour
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

    Price source is chosen automatically:
      1. Janice   — if ``MOONMASTER_JANICE_API_KEY`` is set in Django settings
      2. Fuzzwork — fallback when no Janice key is configured
    """
    try:
        from django.conf import settings
        from .models import Moon, OrePrice
        from .constants import (
            PRICE_SOURCE_JANICE,
            PRICE_SOURCE_FUZZWORK,
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

        # Auto-select Janice when an API key is configured; otherwise Fuzzwork
        if getattr(settings, "MOONMASTER_JANICE_API_KEY", ""):
            source = PRICE_SOURCE_JANICE
        else:
            source = PRICE_SOURCE_FUZZWORK

        updated = update_all_prices(list(type_id_set), source=source)
        logger.info("moonmaster.update_prices: updated %d price records from %s.", updated, source)
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

    from .constants import STRUCTURE_TYPE_ATHANOR, STRUCTURE_TYPE_METENOX, SERVICE_MODULE_FUEL_PER_HOUR
    from .models import Structure
    from .providers import (
        ATHANOR_TYPE_ID,
        METENOX_TYPE_ID,
        MOON_STRUCTURE_TYPE_IDS,
        SCOPE_STRUCTURES,
        esi_authed_get,
        structure_is_online,
    )

    token = owner.get_token([SCOPE_STRUCTURES])
    if not token:
        msg = f"No valid ESI token with scope {SCOPE_STRUCTURES} for {owner}."
        logger.warning("_sync_owner_structures: %s", msg)
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

        # Sum fuel blocks/hr from all online service modules
        services = s.get("services", [])
        fuel_per_hr = float(sum(
            SERVICE_MODULE_FUEL_PER_HOUR.get(svc.get("name", ""), 0)
            for svc in services
            if svc.get("state") == "online"
        ))

        # Reinforce / state fields
        raw_state = s.get("state", "unknown")
        state_timer_end_str = s.get("state_timer_end")
        state_timer_end = parse_datetime(state_timer_end_str) if state_timer_end_str else None
        unanchors_at_str = s.get("unanchors_at")
        unanchors_at = parse_datetime(unanchors_at_str) if unanchors_at_str else None

        obj, _ = Structure.objects.update_or_create(
            structure_id=s["structure_id"],
            defaults={
                "owner": owner,
                "name": s.get("name", ""),
                "structure_type": structure_type,
                "is_online": is_online,
                "fuel_expires": fuel_expires,
                "fuel_blocks_per_hour": fuel_per_hr,
                "state": raw_state,
                "state_timer_end": state_timer_end,
                "reinforce_hour": s.get("reinforce_hour"),
                "reinforce_weekday": s.get("reinforce_weekday"),
                "services_raw": services,
                "unanchors_at": unanchors_at,
            },
        )
        if obj.moon_id is None and structure_type in ("metenox", "athanor"):
            _try_link_structure_to_moon(obj, system_id, owner)
        updated += 1

    # Sync goo bay fill % for Metenox structures (requires assets scope)
    _sync_metenox_bays(owner)

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
        esi_authed_get,
        get_or_create_moon,
    )

    token = owner.get_token([SCOPE_MINING])
    if not token:
        msg = f"No valid ESI token with scope {SCOPE_MINING} for {owner}."
        logger.warning("_sync_owner_extractions: %s", msg)
        owner.sync_error = msg
        owner.last_sync = timezone.now()
        owner.save(update_fields=["last_sync", "sync_error"])
        return

    corp_id = owner.corporation.corporation_id
    try:
        extractions = esi_authed_get(f"/corporation/{corp_id}/mining/extractions/", token)
    except Exception as exc:
        msg = f"ESI extractions fetch failed for {owner}: {exc}"
        logger.exception(msg)
        owner.sync_error = msg
        owner.last_sync = timezone.now()
        owner.save(update_fields=["last_sync", "sync_error"])
        return

    now = timezone.now()
    updated = 0
    active_keys = set()  # (structure_id, extraction_start_time) for active ESI extractions
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
        start_time = parse_datetime(ext["extraction_start_time"])
        status = (
            Extraction.Status.READY
            if chunk_arrival and chunk_arrival <= now
            else Extraction.Status.SCHEDULED
        )

        Extraction.objects.update_or_create(
            structure=structure,
            extraction_start_time=start_time,
            defaults={
                "chunk_arrival_time": chunk_arrival,
                "natural_decay_time": parse_datetime(ext["natural_decay_time"]),
                "status": status,
            },
        )
        active_keys.add((structure_id, start_time))
        updated += 1

    # Mark extractions that disappeared from ESI as FIRED or CANCELLED.
    # Any SCHEDULED/READY extraction for this owner that is no longer in the
    # active_keys set has either been fired (chunk_arrival_time in the past)
    # or cancelled (chunk_arrival_time still in the future).
    owned_structure_ids = list(
        Structure.objects.filter(owner=owner).values_list("structure_id", flat=True)
    )
    stale_qs = Extraction.objects.filter(
        structure__structure_id__in=owned_structure_ids,
        status__in=[Extraction.Status.SCHEDULED, Extraction.Status.READY],
    )
    fired_ids = []
    cancelled_ids = []
    for ext_obj in stale_qs.select_related("structure"):
        key = (ext_obj.structure.structure_id, ext_obj.extraction_start_time)
        if key in active_keys:
            continue
        if ext_obj.chunk_arrival_time and ext_obj.chunk_arrival_time <= now:
            fired_ids.append(ext_obj.pk)
        else:
            cancelled_ids.append(ext_obj.pk)

    if fired_ids:
        Extraction.objects.filter(pk__in=fired_ids).update(status=Extraction.Status.FIRED)
        logger.info(
            "_sync_owner_extractions: %s — marked %d extraction(s) as FIRED.", owner, len(fired_ids)
        )
    if cancelled_ids:
        Extraction.objects.filter(pk__in=cancelled_ids).update(status=Extraction.Status.CANCELLED)
        logger.info(
            "_sync_owner_extractions: %s — marked %d extraction(s) as CANCELLED.", owner, len(cancelled_ids)
        )

    logger.info("_sync_owner_extractions: %s — updated %d extraction(s).", owner, updated)
    owner.last_sync = timezone.now()
    owner.sync_error = ""
    owner.save(update_fields=["last_sync", "sync_error"])


# ---------------------------------------------------------------------------
# Mining ledger
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="moonmaster.tasks.sync_mining_ledger")
def sync_mining_ledger(self):
    """
    Fetch the corporation mining observer ledger from ESI for all active
    owners, then create/update MiningLedgerEntry records linked to the
    relevant Extraction.
    """
    try:
        from .models import StructureOwner

        for owner in StructureOwner.objects.filter(is_active=True):
            _sync_owner_mining_ledger(owner)
    except Exception as exc:
        logger.exception("moonmaster.sync_mining_ledger failed: %s", exc)
        raise self.retry(exc=exc, countdown=60, max_retries=3)


def _sync_owner_mining_ledger(owner):
    """
    Pull ESI /corporations/{id}/mining/observers/ and each observer's ledger,
    then upsert MiningLedgerEntry rows linked to matching Extraction records.
    """
    from django.utils.dateparse import parse_date

    from allianceauth.eveonline.models import EveCharacter

    from .constants import MOON_ORE_NAMES
    from .models import Extraction, MiningLedgerEntry, Structure
    from .providers import (
        SCOPE_MINING,
        esi_authed_get,
    )

    token = owner.get_token([SCOPE_MINING])
    if not token:
        logger.warning("_sync_owner_mining_ledger: no valid mining token for %s.", owner)
        return

    corp_id = owner.corporation.corporation_id

    try:
        observers = esi_authed_get(f"/corporations/{corp_id}/mining/observers/", token)
    except Exception as exc:
        logger.warning("_sync_owner_mining_ledger: observers fetch failed for %s: %s", owner, exc)
        return

    # Build a map of structure_id → Structure for this owner's Metenox/Athanor
    owned_structure_ids = set(
        Structure.objects.filter(owner=owner).values_list("structure_id", flat=True)
    )

    created_total = 0
    for obs in observers:
        observer_id = obs.get("observer_id")
        if observer_id not in owned_structure_ids:
            continue  # skip observers for structures not in our DB yet

        try:
            structure = Structure.objects.get(structure_id=observer_id)
        except Structure.DoesNotExist:
            continue

        try:
            ledger = esi_authed_get(
                f"/corporations/{corp_id}/mining/observers/{observer_id}/", token
            )
        except Exception as exc:
            logger.warning(
                "_sync_owner_mining_ledger: ledger fetch failed for observer %s: %s",
                observer_id, exc,
            )
            continue

        for entry in ledger:
            char_id = entry.get("character_id")
            type_id = entry.get("type_id")
            quantity = entry.get("quantity", 0)
            recorded_date_str = entry.get("last_updated") or entry.get("recorded_date")
            if not (char_id and type_id and recorded_date_str):
                continue

            recorded_date = parse_date(recorded_date_str)
            if not recorded_date:
                continue

            # Find the Extraction whose window covers recorded_date
            extraction = (
                Extraction.objects.filter(
                    structure=structure,
                    extraction_start_time__date__lte=recorded_date,
                    chunk_arrival_time__date__gte=recorded_date,
                )
                .order_by("-chunk_arrival_time")
                .first()
            )

            character = EveCharacter.objects.filter(character_id=char_id).first()
            ore_name = MOON_ORE_NAMES.get(type_id, "")

            _, created = MiningLedgerEntry.objects.update_or_create(
                extraction=extraction,
                character=character,
                ore_type_id=type_id,
                recorded_date=recorded_date,
                defaults={
                    "quantity": quantity,
                    "ore_type_name": ore_name,
                },
            )
            if created:
                created_total += 1

    logger.info(
        "_sync_owner_mining_ledger: %s — created %d new ledger entry(ies).",
        owner, created_total,
    )


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

    Each alert type per structure is throttled to once per cooldown window:
      - fuel low:      every 4 h
      - goo bay full:  every 4 h
      - extraction:    every 1 h
    """
    try:
        from django.core.cache import cache
        from .models import Structure, Extraction
        from .constants import STRUCTURE_TYPE_METENOX

        now = timezone.now()
        soon = now + timedelta(hours=24)
        very_soon = now + timedelta(hours=1)

        def _already_alerted(key, timeout_seconds):
            if cache.get(key):
                return True
            cache.set(key, 1, timeout=timeout_seconds)
            return False

        # --- Fuel low ---
        low_fuel = Structure.objects.filter(
            structure_type=STRUCTURE_TYPE_METENOX,
            fuel_expires__lte=soon,
            is_online=True,
        )
        for structure in low_fuel:
            cache_key = f"mm_alert_fuel_{structure.pk}"
            if _already_alerted(cache_key, 4 * 3600):
                continue
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
            cache_key = f"mm_alert_goobay_{structure.pk}"
            if _already_alerted(cache_key, 4 * 3600):
                continue
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
            cache_key = f"mm_alert_extraction_{extraction.pk}"
            if _already_alerted(cache_key, 1 * 3600):
                continue
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

        # Type IDs that appear in some probe-scanner exports but are incorrect.
        # 45509 is a ship SKIN; the real Cinnabar (R32) is 45506.
        _BAD_TYPE_IDS = {
            45509: 45506,  # Cinnabar: SKIN id → real ore id
        }

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
            type_id = _BAD_TYPE_IDS.get(type_id, type_id)  # correct known wrong IDs
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


@shared_task(bind=True, name="moonmaster.tasks.process_spreadsheet_survey")
def process_spreadsheet_survey(self, raw: str, user_id: int):
    """
    Parse and import moon composition data from a spreadsheet/CSV export.

    Expected format (tab-separated rows, one moon per row):
      MoonID  [any cols]  OreName  OrePercent  OreName  OrePercent  ...

    Ore names are matched case-insensitively against the known moon ore list.
    Percentages may be "28.30%" or "0.2830" — both are accepted.
    The MoonID must be in column 0. All other columns between and after
    the moon ID are scanned for (OreName, OrePercent) pairs.
    """
    try:
        from .providers import get_or_create_moon
        from .constants import MOON_ORE_NAMES, MOON_ORE_RARITY, RARITY_UBIQUITOUS

        ORE_NAME_TO_ID: dict = {v.lower(): k for k, v in MOON_ORE_NAMES.items()}
        _rank = {"ubiquitous": 0, "common": 1, "uncommon": 2, "rare": 3, "exceptional": 4}

        def _infer_rarity(composition):
            best = RARITY_UBIQUITOUS
            for tid_str in composition:
                rarity = MOON_ORE_RARITY.get(int(tid_str))
                if rarity and _rank.get(rarity, 0) > _rank.get(best, 0):
                    best = rarity
            return best

        created = updated = 0
        errors: list = []

        for lineno, line in enumerate(raw.splitlines(), 1):
            line = line.rstrip("\r")
            if not line.strip():
                continue
            cols = line.split("\t")
            if not cols:
                continue

            # Column 0 must be the numeric Moon ID
            try:
                moon_id = int(cols[0].strip().replace(",", ""))
            except ValueError:
                continue  # skip header rows

            # Scan all columns for (OreName, OrePercent) pairs
            comp: dict = {}
            i = 1
            while i < len(cols) - 1:
                name_str = cols[i].strip().lower()
                if name_str in ORE_NAME_TO_ID:
                    try:
                        pct_str = cols[i + 1].strip().rstrip("%")
                        pct = float(pct_str)
                        if pct > 1.5:          # value is a percentage like 28.30
                            pct = pct / 100.0
                        comp[str(ORE_NAME_TO_ID[name_str])] = pct
                        i += 2
                        continue
                    except (ValueError, IndexError):
                        pass
                i += 1

            if not comp:
                errors.append(f"Line {lineno}: no recognised ore names found")
                continue

            # Normalise fractions to sum to 1.0
            total = sum(comp.values())
            if total > 0:
                comp = {k: round(v / total, 6) for k, v in comp.items()}

            moon, was_created = get_or_create_moon(moon_id)
            moon.ore_composition = comp
            moon.rarity_class = _infer_rarity(comp)
            moon.save(update_fields=["ore_composition", "rarity_class"])
            if was_created:
                created += 1
            else:
                updated += 1

        try:
            from django.contrib.auth.models import User
            from allianceauth.notifications import notify

            user = User.objects.get(pk=user_id)
            error_summary = f" ({len(errors)} line(s) skipped)" if errors else ""
            notify(
                user=user,
                title="Spreadsheet Survey Import Complete",
                message=(
                    f"Import finished: {created} moon(s) created, "
                    f"{updated} updated{error_summary}."
                ),
                level="success" if not errors else "warning",
            )
        except Exception:
            pass

        logger.info(
            "process_spreadsheet_survey: created=%d updated=%d errors=%d",
            created, updated, len(errors),
        )

    except Exception as exc:
        logger.exception("moonmaster.process_spreadsheet_survey failed: %s", exc)
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


def _sync_metenox_bays(owner):
    """
    Fetch corporation assets, sum moon material volumes per Metenox structure,
    and update Structure.goo_bay_fill_pct.

    The MoonMaterialBay holds already-processed moon goo materials (type IDs
    16633-16655, each 0.05 m³/unit), NOT raw ores.  We resolve volumes
    dynamically from the SDE so the calculation is correct regardless of what
    CCP puts in the bay.

    Requires esi-assets.read_corporation_assets.v1.  Silently skipped if the
    owner's character doesn't have that scope.
    """
    from .constants import STRUCTURE_TYPE_METENOX, METENOX_MOON_MATERIAL_BAY_CAPACITY
    from .models import Structure
    from .providers import (
        SCOPE_ASSETS,
        esi_authed_get,
    )

    assets_token = owner.get_token([SCOPE_ASSETS])
    if not assets_token:
        logger.debug("_sync_metenox_bays: no assets token for %s — skipping.", owner)
        return

    corp_id = owner.corporation.corporation_id
    try:
        assets = esi_authed_get(f"/corporations/{corp_id}/assets/", assets_token)
    except Exception as exc:
        logger.warning("_sync_metenox_bays: assets fetch failed for %s: %s", owner, exc)
        return

    # Collect items in MoonMaterialBay and gather their type IDs
    bay_items = [a for a in assets if a.get("location_flag") == "MoonMaterialBay"]

    # Build a volume map: type_id → m³/unit, resolved from SDE with fallback to 0.05
    type_ids = {item.get("type_id", 0) for item in bay_items}
    vol_map: dict = {}
    if type_ids:
        try:
            from eve_sde.models import ItemType as SdeItemType
            for row in SdeItemType.objects.filter(id__in=type_ids).values("id", "volume"):
                vol_map[row["id"]] = float(row["volume"])
        except Exception:
            pass
    # Fall back: moon goo materials are 0.05 m³/unit; raw ores are 10.0 m³/unit
    # Use 0.05 as the default since the Metenox bay holds processed materials.
    GOO_MATERIAL_VOLUME_DEFAULT = 0.05
    from .constants import MOON_ORE_VOLUME_M3  # raw ores still looked up correctly
    for item in bay_items:
        tid = item.get("type_id", 0)
        if tid not in vol_map:
            vol_map[tid] = MOON_ORE_VOLUME_M3.get(tid, GOO_MATERIAL_VOLUME_DEFAULT)

    # Sum volume per structure location
    bay_volumes: dict = {}
    for item in bay_items:
        loc_id = item.get("location_id")
        tid = item.get("type_id", 0)
        quantity = item.get("quantity", 0)
        bay_volumes[loc_id] = bay_volumes.get(loc_id, 0.0) + quantity * vol_map.get(tid, GOO_MATERIAL_VOLUME_DEFAULT)

    # Update matching Metenox Structure records
    metenox_sids = list(
        Structure.objects.filter(
            owner=owner, structure_type=STRUCTURE_TYPE_METENOX
        ).values_list("structure_id", flat=True)
    )
    for structure_id in metenox_sids:
        vol = bay_volumes.get(structure_id, 0.0)
        fill_pct = min(vol / METENOX_MOON_MATERIAL_BAY_CAPACITY * 100.0, 100.0)
        Structure.objects.filter(structure_id=structure_id).update(
            goo_bay_fill_pct=round(fill_pct, 1)
        )
    logger.debug("_sync_metenox_bays: updated bay fill for %d Metenox(es) under %s.", len(metenox_sids), owner)


def _try_link_structure_to_moon(structure, system_id, owner):
    """
    Attempt to discover which moon a Structure sits on, trying:
      1. ESI /universe/structures/{id}/ (needs esi-universe.read_structures.v1)
      2. Name-based planet/moon number lookup via public ESI
      3. Name-substring match against known Moon records (fallback)
    Sets structure.moon and saves when a match is found.
    """
    from .providers import (
        get_structure_info,
        find_moon_for_position,
        find_moon_by_number,
        get_or_create_moon,
        SCOPE_UNIVERSE,
    )
    from .models import Moon

    # --- Attempt 1: position-based lookup via universe scope ---
    uni_token = owner.get_token([SCOPE_UNIVERSE])
    if uni_token:
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

    # --- Attempt 2: Parse structure name → Moon DB name ---
    # Handles:
    #   "NOL-M9 - VIII.7"  (Roman numeral planet)  → "NOL-M9 VIII - Moon 7"
    #   "N-8YET - 7-12"    (decimal planet)         → "N-8YET VII - Moon 12"
    #   "IP6V-X - V.1"     (Roman numeral planet)   → "IP6V-X V - Moon 1"
    if structure.name:
        import re

        _INT_TO_ROMAN = {
            1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII",
            8: "VIII", 9: "IX", 10: "X", 11: "XI", 12: "XII", 13: "XIII",
            14: "XIV", 15: "XV", 16: "XVI", 17: "XVII", 18: "XVIII",
        }

        def _to_roman(n):
            return _INT_TO_ROMAN.get(int(n), str(n))

        # Roman numeral planet: "System - VIII.7"
        m = re.match(r'^(.+?)\s*-\s*([IVXivx]+)\.(\d+)\s*$', structure.name)
        if m:
            candidate = f"{m.group(1).strip()} {m.group(2).upper()} - Moon {m.group(3)}"
            moon_qs = Moon.objects.filter(name=candidate)
            if moon_qs.exists():
                moon = moon_qs.first()
                structure.moon = moon
                structure.save(update_fields=["moon"])
                logger.info("Linked structure %s → %s via name parsing (Roman)", structure.structure_id, moon)
                return
            # Moon record doesn't exist yet — resolve via ESI by planet/moon number
            _ROMAN_TO_INT = {
                "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
                "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13,
                "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18,
            }
            planet_n = _ROMAN_TO_INT.get(m.group(2).upper())
            moon_n = int(m.group(3))
            if planet_n and system_id:
                moon_id = find_moon_by_number(system_id, planet_n, moon_n)
                if moon_id:
                    moon, _ = get_or_create_moon(moon_id)
                    structure.moon = moon
                    structure.save(update_fields=["moon"])
                    logger.info("Linked structure %s → %s via ESI planet/moon lookup (Roman)", structure.structure_id, moon)
                    return

        # Decimal planet: "System - 7-12"
        m = re.match(r'^(.+?)\s*-\s*(\d+)-(\d+)\s*$', structure.name)
        if m:
            candidate = f"{m.group(1).strip()} {_to_roman(m.group(2))} - Moon {m.group(3)}"
            moon_qs = Moon.objects.filter(name=candidate)
            if moon_qs.exists():
                moon = moon_qs.first()
                structure.moon = moon
                structure.save(update_fields=["moon"])
                logger.info("Linked structure %s → %s via name parsing (decimal)", structure.structure_id, moon)
                return
            # Moon record doesn't exist yet — resolve via ESI by planet/moon number
            planet_n = int(m.group(2))
            moon_n = int(m.group(3))
            if system_id:
                moon_id = find_moon_by_number(system_id, planet_n, moon_n)
                if moon_id:
                    moon, _ = get_or_create_moon(moon_id)
                    structure.moon = moon
                    structure.save(update_fields=["moon"])
                    logger.info("Linked structure %s → %s via ESI planet/moon lookup (decimal)", structure.structure_id, moon)
                    return

    # --- Attempt 3: name-substring match against known Moon records ---
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
