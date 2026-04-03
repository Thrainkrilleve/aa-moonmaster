import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("eveonline", "0017_alliance_and_corp_names_are_not_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="Moon",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("moon_id", models.PositiveBigIntegerField(unique=True, verbose_name="Moon ID")),
                ("name", models.CharField(max_length=100, verbose_name="Name")),
                ("solar_system_id", models.PositiveBigIntegerField(verbose_name="Solar System ID")),
                ("solar_system_name", models.CharField(max_length=100, verbose_name="Solar System")),
                ("region_name", models.CharField(blank=True, max_length=100, verbose_name="Region")),
                ("ore_composition", models.JSONField(default=dict, verbose_name="Ore Composition")),
                ("rarity_class", models.CharField(
                    blank=True, max_length=20,
                    choices=[
                        ("ubiquitous", "Ubiquitous"),
                        ("common", "Common"),
                        ("uncommon", "Uncommon"),
                        ("rare", "Rare"),
                        ("exceptional", "Exceptional"),
                    ],
                    verbose_name="Rarity Class",
                )),
                ("notes", models.TextField(blank=True, verbose_name="Notes")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Moon",
                "verbose_name_plural": "Moons",
                "ordering": ["solar_system_name", "name"],
                "permissions": [
                    ("basic_access", "Can access Moon Master"),
                    ("manage_moons", "Can add / edit moons and structures"),
                    ("view_reports", "Can view profitability reports"),
                ],
            },
        ),
        migrations.CreateModel(
            name="StructureOwner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True, verbose_name="Active")),
                ("last_sync", models.DateTimeField(blank=True, null=True, verbose_name="Last Sync")),
                ("sync_error", models.TextField(blank=True, verbose_name="Last Sync Error")),
                (
                    "corporation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="moonmaster_owner",
                        to="eveonline.evecorporationinfo",
                        verbose_name="Corporation",
                    ),
                ),
                (
                    "character",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="eveonline.evecharacter",
                        verbose_name="ESI Character",
                    ),
                ),
            ],
            options={
                "verbose_name": "Structure Owner",
                "verbose_name_plural": "Structure Owners",
            },
        ),
        migrations.CreateModel(
            name="TaxConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alliance_tax", models.FloatField(default=0.0, verbose_name="Alliance Mining Tax")),
                ("corp_tax", models.FloatField(default=0.0, verbose_name="Corp Mining Tax")),
                ("reprocess_tax", models.FloatField(default=0.0, verbose_name="Structure Reprocessing Tax")),
                ("sov_upkeep_daily_isk", models.DecimalField(decimal_places=2, default=0, max_digits=20, verbose_name="Sov / Daily Fixed Cost (ISK)")),
                (
                    "owner",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tax_config",
                        to="moonmaster.structureowner",
                        verbose_name="Owner",
                    ),
                ),
            ],
            options={
                "verbose_name": "Tax Configuration",
                "verbose_name_plural": "Tax Configurations",
            },
        ),
        migrations.CreateModel(
            name="Structure",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("structure_id", models.PositiveBigIntegerField(unique=True, verbose_name="Structure ID")),
                ("name", models.CharField(blank=True, max_length=150, verbose_name="Structure Name")),
                ("structure_type", models.CharField(
                    choices=[("athanor", "Athanor (Drill Extraction)"), ("metenox", "Metenox (Passive Harvest)")],
                    default="athanor",
                    max_length=20,
                    verbose_name="Structure Type",
                )),
                ("is_online", models.BooleanField(default=True, verbose_name="Online")),
                ("fuel_expires", models.DateTimeField(blank=True, null=True, verbose_name="Fuel Expires")),
                ("goo_bay_fill_pct", models.FloatField(blank=True, null=True, verbose_name="Goo Bay Fill %")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "moon",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="structures",
                        to="moonmaster.moon",
                        verbose_name="Moon",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="structures",
                        to="moonmaster.structureowner",
                        verbose_name="Owner",
                    ),
                ),
            ],
            options={
                "verbose_name": "Structure",
                "verbose_name_plural": "Structures",
                "ordering": ["moon__solar_system_name", "moon__name"],
            },
        ),
        migrations.CreateModel(
            name="Extraction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chunk_arrival_time", models.DateTimeField(verbose_name="Chunk Arrival")),
                ("natural_decay_time", models.DateTimeField(verbose_name="Auto-Fire Time")),
                ("extraction_start_time", models.DateTimeField(verbose_name="Extraction Start")),
                ("status", models.CharField(
                    choices=[
                        ("scheduled", "Scheduled"),
                        ("ready", "Ready to Fire"),
                        ("fired", "Fired"),
                        ("cancelled", "Cancelled"),
                    ],
                    default="scheduled",
                    max_length=20,
                    verbose_name="Status",
                )),
                ("ore_volume_json", models.JSONField(default=dict, verbose_name="Ore Volumes (m³)")),
                ("estimated_value_isk", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True, verbose_name="Estimated Value (ISK)")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "structure",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="extractions",
                        to="moonmaster.structure",
                        verbose_name="Structure",
                    ),
                ),
            ],
            options={
                "verbose_name": "Extraction",
                "verbose_name_plural": "Extractions",
                "ordering": ["-chunk_arrival_time"],
            },
        ),
        migrations.CreateModel(
            name="MiningLedgerEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ore_type_id", models.PositiveIntegerField(verbose_name="Ore Type ID")),
                ("ore_type_name", models.CharField(blank=True, max_length=100, verbose_name="Ore Type")),
                ("quantity", models.PositiveBigIntegerField(verbose_name="Quantity")),
                ("recorded_date", models.DateField(verbose_name="Recorded Date")),
                (
                    "extraction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ledger_entries",
                        to="moonmaster.extraction",
                        verbose_name="Extraction",
                    ),
                ),
                (
                    "character",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="eveonline.evecharacter",
                        verbose_name="Character",
                    ),
                ),
            ],
            options={
                "verbose_name": "Mining Ledger Entry",
                "verbose_name_plural": "Mining Ledger Entries",
                "ordering": ["-recorded_date", "character__character_name"],
                "unique_together": {("extraction", "character", "ore_type_id", "recorded_date")},
            },
        ),
        migrations.CreateModel(
            name="OrePrice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type_id", models.PositiveIntegerField(unique=True, verbose_name="Type ID")),
                ("type_name", models.CharField(blank=True, max_length=100, verbose_name="Type Name")),
                ("avg_price", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True, verbose_name="Average Price (ISK)")),
                ("reprocessed_value", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True, verbose_name="Reprocessed Value (ISK)")),
                ("source", models.CharField(
                    choices=[("esi", "ESI Average Price"), ("fuzzwork", "Fuzzwork Buy/Sell")],
                    default="esi",
                    max_length=20,
                    verbose_name="Price Source",
                )),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Ore Price",
                "verbose_name_plural": "Ore Prices",
                "ordering": ["type_name"],
            },
        ),
    ]
