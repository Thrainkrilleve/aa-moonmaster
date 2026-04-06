from django.db import models
from django.utils.translation import gettext_lazy as _

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCorporationInfo, EveCharacter

from .constants import (
    STRUCTURE_TYPE_CHOICES,
    STRUCTURE_TYPE_ATHANOR,
    RARITY_CHOICES,
    PRICE_SOURCE_CHOICES,
    PRICE_SOURCE_ESI,
)


class Moon(models.Model):
    """A scannable moon with an ore composition."""

    # EVE type_id for the moon itself (from ESI universe/moons)
    moon_id = models.PositiveBigIntegerField(unique=True, verbose_name=_("Moon ID"))
    name = models.CharField(max_length=100, verbose_name=_("Name"))

    # Solar system name for display (denormalised for speed)
    solar_system_id = models.PositiveBigIntegerField(verbose_name=_("Solar System ID"))
    solar_system_name = models.CharField(max_length=100, verbose_name=_("Solar System"))
    region_name = models.CharField(max_length=100, blank=True, verbose_name=_("Region"))

    # Ore composition stored as {type_id: fraction, ...}  (fractions sum to 1.0)
    ore_composition = models.JSONField(
        default=dict,
        verbose_name=_("Ore Composition"),
        help_text=_("Dict mapping ore type_id (str) to fractional abundance (0–1)."),
    )

    rarity_class = models.CharField(
        max_length=20,
        choices=RARITY_CHOICES,
        blank=True,
        verbose_name=_("Rarity Class"),
    )

    notes = models.TextField(blank=True, verbose_name=_("Notes"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["solar_system_name", "name"]
        verbose_name = _("Moon")
        verbose_name_plural = _("Moons")
        permissions = [
            ("basic_access", "Can access Moon Master"),
            ("manage_moons", "Can add / edit moons and structures"),
            ("view_reports", "Can view profitability reports"),
        ]

    def __str__(self):
        return f"{self.name} ({self.solar_system_name})"


class StructureOwner(models.Model):
    """
    A corporation whose ESI token is used to pull structure / extraction data.
    """

    corporation = models.OneToOneField(
        EveCorporationInfo,
        on_delete=models.CASCADE,
        related_name="moonmaster_owner",
        verbose_name=_("Corporation"),
    )
    character = models.ForeignKey(
        EveCharacter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("ESI Character"),
        help_text=_("Character whose token is used for ESI pulls."),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    last_sync = models.DateTimeField(null=True, blank=True, verbose_name=_("Last Sync"))
    sync_error = models.TextField(blank=True, verbose_name=_("Last Sync Error"))

    class Meta:
        verbose_name = _("Structure Owner")
        verbose_name_plural = _("Structure Owners")

    def __str__(self):
        return f"{self.corporation.corporation_name}"

    def get_token(self, scopes):
        """
        Return the first valid, refreshed ESI token from any registered
        manager character.  Tries OwnerCharacter rows (primary first, then
        oldest-added), then falls back to the legacy ``character`` field.
        Returns None if no usable token is found.
        """
        from .providers import get_valid_token, refresh_token

        for oc in self.owner_characters.order_by("-is_primary", "id").select_related("character"):
            tok = get_valid_token(oc.character.character_id, scopes)
            if tok and refresh_token(tok):
                return tok

        # Legacy fallback — keeps working if OwnerCharacter table is empty
        if self.character_id:
            tok = get_valid_token(self.character.character_id, scopes)
            if tok and refresh_token(tok):
                return tok

        return None


class OwnerCharacter(models.Model):
    """
    A manager character registered for a StructureOwner corporation.
    Multiple characters can be registered per corporation so that ESI
    calls can fall back to another manager's token if the primary is
    expired or invalid.
    """

    owner = models.ForeignKey(
        StructureOwner,
        on_delete=models.CASCADE,
        related_name="owner_characters",
        verbose_name=_("Owner"),
    )
    character = models.ForeignKey(
        EveCharacter,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("Character"),
    )
    is_primary = models.BooleanField(
        default=False,
        verbose_name=_("Primary"),
        help_text=_("Primary character — tried first on every sync."),
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Added"))

    class Meta:
        unique_together = [("owner", "character")]
        ordering = ["-is_primary", "id"]
        verbose_name = _("Owner Character")
        verbose_name_plural = _("Owner Characters")

    def __str__(self):
        return f"{self.character.character_name} ({self.owner.corporation.corporation_name})"


class Structure(models.Model):
    """An Athanor or Metenox structure anchored on a moon."""

    owner = models.ForeignKey(
        StructureOwner,
        on_delete=models.CASCADE,
        related_name="structures",
        verbose_name=_("Owner"),
    )
    moon = models.ForeignKey(
        Moon,
        on_delete=models.CASCADE,
        related_name="structures",
        null=True,
        blank=True,
        verbose_name=_("Moon"),
    )
    structure_id = models.PositiveBigIntegerField(unique=True, verbose_name=_("Structure ID"))
    name = models.CharField(max_length=150, blank=True, verbose_name=_("Structure Name"))
    structure_type = models.CharField(
        max_length=20,
        choices=STRUCTURE_TYPE_CHOICES,
        default=STRUCTURE_TYPE_ATHANOR,
        verbose_name=_("Structure Type"),
    )
    is_online = models.BooleanField(default=True, verbose_name=_("Online"))

    # Metenox-specific fields
    fuel_expires = models.DateTimeField(null=True, blank=True, verbose_name=_("Fuel Expires"))
    goo_bay_fill_pct = models.FloatField(
        null=True, blank=True, verbose_name=_("Goo Bay Fill %"),
        help_text=_("Percentage of the moon material bay that is currently filled."),
    )

    # Fuel cost derived from fitted service modules (synced from ESI services)
    fuel_blocks_per_hour = models.FloatField(
        default=0.0,
        verbose_name=_("Fuel Blocks/hr"),
        help_text=_("Sum of fuel blocks/hour consumed by all online service modules. "
                    "Derived from ESI structure services."),
    )

    # Reinforcement / structure state fields (synced from ESI)
    state = models.CharField(
        max_length=60, default="unknown", verbose_name=_("State"),
        help_text=_("Raw ESI structure state string."),
    )
    state_timer_end = models.DateTimeField(
        null=True, blank=True, verbose_name=_("State Timer End"),
        help_text=_("When the current reinforce or vulnerability timer expires."),
    )
    reinforce_hour = models.IntegerField(
        null=True, blank=True, verbose_name=_("Reinforce Hour (UTC)"),
        help_text=_("Hour of day (0-23 UTC) when the vulnerability window starts."),
    )
    reinforce_weekday = models.IntegerField(
        null=True, blank=True, verbose_name=_("Reinforce Weekday"),
        help_text=_("0=Monday … 6=Sunday. Null if no specific day is set."),
    )
    services_raw = models.JSONField(
        default=list, verbose_name=_("Services"),
        help_text=_("Fitted service modules from ESI: [{name, state}, …]."),
    )
    unanchors_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Unanchors At"),
    )

    # Detailed bay contents snapshot — list of {type_id, name, quantity, volume_m3}
    goo_bay_contents = models.JSONField(
        default=list,
        verbose_name=_("Goo Bay Contents"),
        help_text=_("Snapshot of processed moon materials in the bay: [{type_id, name, quantity, volume_m3}, …]."),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["moon__solar_system_name", "moon__name"]
        verbose_name = _("Structure")
        verbose_name_plural = _("Structures")

    def __str__(self):
        moon_label = str(self.moon) if self.moon_id else "(no moon)"
        return self.name or f"Structure {self.structure_id} on {moon_label}"

    # ------------------------------------------------------------------
    # Computed properties (no DB queries)
    # ------------------------------------------------------------------

    @property
    def is_reinforced(self) -> bool:
        from .constants import REINFORCE_STATES
        return self.state in REINFORCE_STATES

    @property
    def reinforce_type(self):
        """Return 'armor', 'hull', or None."""
        if self.state == "armor_reinforce":
            return "armor"
        if self.state == "hull_reinforce":
            return "hull"
        return None

    @property
    def state_label(self) -> dict:
        """Return {'text': '...', 'cls': 'success|warning|danger|secondary'} for template."""
        from .constants import STRUCTURE_STATE_LABELS
        text, cls = STRUCTURE_STATE_LABELS.get(self.state, ("Unknown", "secondary"))
        return {"text": text, "cls": cls}

    @property
    def services_parsed(self) -> list:
        """Return list of dicts with display name + online flag for each fitted service."""
        from .constants import SERVICE_DISPLAY_NAMES
        result = []
        for svc in (self.services_raw or []):
            name = svc.get("name", "")
            result.append({
                "name": name,
                "display": SERVICE_DISPLAY_NAMES.get(name, name.replace("_", " ").title()),
                "state": svc.get("state", "offline"),
                "online": svc.get("state") == "online",
            })
        return result

    @property
    def reinforce_schedule(self) -> str:
        """Return human-readable reinforce window, e.g. 'Fri 14:00 UTC'."""
        if self.reinforce_hour is None:
            return ""
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day = f"{days[self.reinforce_weekday]} " if self.reinforce_weekday is not None else ""
        return f"{day}{self.reinforce_hour:02d}:00 UTC"

    @property
    def fuel_days_remaining(self):
        """Return whole days until fuel_expires, or None if not set."""
        if not self.fuel_expires:
            return None
        from django.utils import timezone
        delta = self.fuel_expires - timezone.now()
        return max(0, int(delta.total_seconds() // 86400))

    @property
    def fuel_hours_remaining(self):
        """Return whole hours until fuel_expires, or None if not set."""
        if not self.fuel_expires:
            return None
        from django.utils import timezone
        delta = self.fuel_expires - timezone.now()
        return max(0, int(delta.total_seconds() // 3600))


class Extraction(models.Model):
    """An Athanor drill-cycle extraction event."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", _("Scheduled")
        READY = "ready", _("Ready to Fire")
        FIRED = "fired", _("Fired")
        CANCELLED = "cancelled", _("Cancelled")

    structure = models.ForeignKey(
        Structure,
        on_delete=models.CASCADE,
        related_name="extractions",
        verbose_name=_("Structure"),
    )
    chunk_arrival_time = models.DateTimeField(verbose_name=_("Chunk Arrival"))
    natural_decay_time = models.DateTimeField(verbose_name=_("Auto-Fire Time"))
    extraction_start_time = models.DateTimeField(verbose_name=_("Extraction Start"))

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        verbose_name=_("Status"),
    )

    # Snapshot of ore amounts at time of pull {type_id: volume_m3}
    ore_volume_json = models.JSONField(
        default=dict,
        verbose_name=_("Ore Volumes (m³)"),
    )

    # Estimated ISK value cached at last price update
    estimated_value_isk = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        verbose_name=_("Estimated Value (ISK)"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-chunk_arrival_time"]
        verbose_name = _("Extraction")
        verbose_name_plural = _("Extractions")

    def __str__(self):
        return f"Extraction {self.structure} @ {self.chunk_arrival_time:%Y-%m-%d %H:%M}"


class MiningLedgerEntry(models.Model):
    """A single character's mining contribution during an extraction cycle."""

    extraction = models.ForeignKey(
        Extraction,
        on_delete=models.CASCADE,
        related_name="ledger_entries",
        null=True, blank=True,
        verbose_name=_("Extraction"),
    )
    character = models.ForeignKey(
        EveCharacter,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Character"),
    )
    ore_type_id = models.PositiveIntegerField(verbose_name=_("Ore Type ID"))
    ore_type_name = models.CharField(max_length=100, blank=True, verbose_name=_("Ore Type"))
    quantity = models.PositiveBigIntegerField(verbose_name=_("Quantity"))
    recorded_date = models.DateField(verbose_name=_("Recorded Date"))

    class Meta:
        ordering = ["-recorded_date", "character__character_name"]
        verbose_name = _("Mining Ledger Entry")
        verbose_name_plural = _("Mining Ledger Entries")
        unique_together = [("extraction", "character", "ore_type_id", "recorded_date")]

    def __str__(self):
        char_name = self.character.character_name if self.character else "Unknown"
        return f"{char_name} mined {self.quantity}× {self.ore_type_name or self.ore_type_id}"


class TaxConfig(models.Model):
    """Tax / charge rates associated with a StructureOwner."""

    owner = models.OneToOneField(
        StructureOwner,
        on_delete=models.CASCADE,
        related_name="tax_config",
        verbose_name=_("Owner"),
    )

    # Rates expressed as fractions (0.0–1.0)
    alliance_tax = models.FloatField(
        default=0.0,
        verbose_name=_("Alliance Mining Tax"),
        help_text=_("Fraction of mined ore value paid as alliance tax (e.g. 0.05 = 5%)."),
    )
    corp_tax = models.FloatField(
        default=0.0,
        verbose_name=_("Corp Mining Tax"),
        help_text=_("Fraction of mined ore value paid as corp tax."),
    )
    reprocess_tax = models.FloatField(
        default=0.0,
        verbose_name=_("Structure Reprocessing Tax"),
        help_text=_("Tax taken by structure on reprocessing (fraction of output value)."),
    )

    # Fixed ISK per day (sov upkeep, customs, etc.)
    sov_upkeep_daily_isk = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
        verbose_name=_("Sov / Daily Fixed Cost (ISK)"),
    )

    class Meta:
        verbose_name = _("Tax Configuration")
        verbose_name_plural = _("Tax Configurations")

    def __str__(self):
        return f"Tax Config for {self.owner}"


class OrePrice(models.Model):
    """Cached market price for an ore or mineral type."""

    type_id = models.PositiveIntegerField(unique=True, verbose_name=_("Type ID"))
    type_name = models.CharField(max_length=100, blank=True, verbose_name=_("Type Name"))

    # Raw average (ESI) / adjusted buy price (Fuzzwork)
    avg_price = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        verbose_name=_("Average Price (ISK)"),
    )
    # Implied price after reprocessing to base minerals (for ore types)
    reprocessed_value = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        verbose_name=_("Reprocessed Value (ISK)"),
    )

    source = models.CharField(
        max_length=20,
        choices=PRICE_SOURCE_CHOICES,
        default=PRICE_SOURCE_ESI,
        verbose_name=_("Price Source"),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["type_name"]
        verbose_name = _("Ore Price")
        verbose_name_plural = _("Ore Prices")

    def __str__(self):
        return f"{self.type_name or self.type_id} @ {self.avg_price} ISK ({self.source})"
