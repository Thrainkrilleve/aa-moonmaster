from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    Extraction,
    MiningLedgerEntry,
    Moon,
    OrePrice,
    OwnerCharacter,
    Structure,
    StructureOwner,
    TaxConfig,
)


class TaxConfigInline(admin.StackedInline):
    model = TaxConfig
    extra = 0
    can_delete = False


class OwnerCharacterInline(admin.TabularInline):
    model = OwnerCharacter
    extra = 1
    fields = ("character", "is_primary", "added_at")
    readonly_fields = ("added_at",)


class StructureInline(admin.TabularInline):
    model = Structure
    extra = 0
    fields = ("structure_id", "name", "structure_type", "is_online", "fuel_expires", "goo_bay_fill_pct")
    readonly_fields = ("updated_at",)


@admin.register(StructureOwner)
class StructureOwnerAdmin(admin.ModelAdmin):
    list_display = ("corporation", "character", "is_active", "last_sync")
    list_filter = ("is_active",)
    inlines = [OwnerCharacterInline, TaxConfigInline, StructureInline]
    readonly_fields = ("last_sync", "sync_error")


@admin.register(Moon)
class MoonAdmin(admin.ModelAdmin):
    list_display = ("name", "solar_system_name", "region_name", "rarity_class", "updated_at")
    list_filter = ("rarity_class", "region_name")
    search_fields = ("name", "solar_system_name", "region_name")
    readonly_fields = ("updated_at",)
    fieldsets = (
        (None, {
            "fields": ("moon_id", "name", "solar_system_id", "solar_system_name", "region_name", "rarity_class"),
        }),
        (_("Ore Composition"), {
            "fields": ("ore_composition",),
            "description": _(
                "JSON dict mapping ore type_id (string key) to fractional abundance (0–1). "
                "Values must sum to 1.0."
            ),
        }),
        (_("Notes"), {"fields": ("notes",)}),
    )


class ExtractionLedgerInline(admin.TabularInline):
    model = MiningLedgerEntry
    extra = 0
    fields = ("character", "ore_type_name", "quantity", "recorded_date")
    readonly_fields = ("ore_type_name",)


@admin.register(Extraction)
class ExtractionAdmin(admin.ModelAdmin):
    list_display = (
        "structure", "chunk_arrival_time", "natural_decay_time",
        "status", "estimated_value_isk", "updated_at",
    )
    list_filter = ("status", "structure__owner__corporation")
    search_fields = ("structure__name", "structure__moon__name")
    readonly_fields = ("created_at", "updated_at", "estimated_value_isk")
    inlines = [ExtractionLedgerInline]


@admin.register(OrePrice)
class OrePriceAdmin(admin.ModelAdmin):
    list_display = ("type_id", "type_name", "avg_price", "reprocessed_value", "source", "updated_at")
    list_filter = ("source",)
    search_fields = ("type_id", "type_name")
    readonly_fields = ("updated_at",)
