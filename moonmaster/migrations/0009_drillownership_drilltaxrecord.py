import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("moonmaster", "0008_structure_goo_bay_contents"),
    ]

    operations = [
        migrations.CreateModel(
            name="DrillOwnership",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "structure",
                    models.OneToOneField(
                        limit_choices_to={"structure_type": "metenox"},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="drill_ownership",
                        to="moonmaster.structure",
                        verbose_name="Structure",
                    ),
                ),
                (
                    "character",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="owned_drills",
                        to="eveonline.evecharacter",
                        verbose_name="Drill Owner",
                    ),
                ),
                (
                    "tax_rate",
                    models.FloatField(
                        default=0.1,
                        help_text="Fraction of gross goo value charged as tax (0.0–1.0). E.g. 0.10 = 10%.",
                        verbose_name="Tax Rate",
                    ),
                ),
                ("notes", models.TextField(blank=True, verbose_name="Notes")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Drill Ownership",
                "verbose_name_plural": "Drill Ownerships",
                "ordering": ["character__character_name", "structure__name"],
            },
        ),
        migrations.CreateModel(
            name="DrillTaxRecord",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "structure",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tax_records",
                        to="moonmaster.structure",
                        verbose_name="Structure",
                    ),
                ),
                (
                    "character",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="drill_tax_records",
                        to="eveonline.evecharacter",
                        verbose_name="Drill Owner",
                    ),
                ),
                ("period_start", models.DateField(verbose_name="Period Start")),
                ("period_end", models.DateField(verbose_name="Period End")),
                (
                    "gross_value_isk",
                    models.DecimalField(decimal_places=2, max_digits=22, verbose_name="Gross Goo Value (ISK)"),
                ),
                ("tax_rate", models.FloatField(verbose_name="Tax Rate (snapshot)")),
                (
                    "tax_owed_isk",
                    models.DecimalField(decimal_places=2, max_digits=22, verbose_name="Tax Owed (ISK)"),
                ),
                ("is_paid", models.BooleanField(default=False, verbose_name="Paid")),
                ("paid_at", models.DateTimeField(blank=True, null=True, verbose_name="Paid At")),
                ("notes", models.TextField(blank=True, verbose_name="Notes")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created")),
            ],
            options={
                "verbose_name": "Drill Tax Record",
                "verbose_name_plural": "Drill Tax Records",
                "ordering": ["-period_end", "character__character_name"],
            },
        ),
    ]
