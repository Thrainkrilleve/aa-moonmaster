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

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["moon__solar_system_name", "moon__name"]
        verbose_name = _("Structure")
        verbose_name_plural = _("Structures")

    def __str__(self):
        moon_label = str(self.moon) if self.moon_id else "(no moon)"
        return self.name or f"Structure {self.structure_id} on {moon_label}"


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
