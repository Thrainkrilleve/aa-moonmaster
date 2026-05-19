import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("moonmaster", "0009_drillownership_drilltaxrecord"),
    ]

    operations = [
        # New permissions on DrillOwnership
        migrations.AlterModelOptions(
            name="drillownership",
            options={
                "ordering": ["character__character_name", "structure__name"],
                "verbose_name": "Drill Ownership",
                "verbose_name_plural": "Drill Ownerships",
                "permissions": [
                    ("manage_drill_tax", "Can manage drill ownerships and billing records"),
                    ("view_drill_tax", "Can view all drill tax records"),
                ],
            },
        ),
        # ESI journal ref on DrillTaxRecord
        migrations.AddField(
            model_name="drilltaxrecord",
            name="esi_journal_ref_id",
            field=models.BigIntegerField(
                blank=True,
                help_text="Populated automatically when the ESI payment scanner matches a journal entry.",
                null=True,
                unique=True,
                verbose_name="ESI Journal Ref ID",
            ),
        ),
        # DrillTaxPaymentConfig
        migrations.CreateModel(
            name="DrillTaxPaymentConfig",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "owner",
                    models.OneToOneField(
                        help_text="The corporation whose wallet journal is scanned for payments.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="drill_tax_payment_config",
                        to="moonmaster.structureowner",
                        verbose_name="Corp Owner",
                    ),
                ),
                (
                    "payment_keyword",
                    models.CharField(
                        default="drilling tax",
                        help_text=(
                            "Text to match (case-insensitive) in the ESI journal entry 'reason' field. "
                            "Players must include this text when donating ISK."
                        ),
                        max_length=100,
                        verbose_name="Payment Keyword",
                    ),
                ),
                (
                    "is_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Uncheck to pause automatic payment detection for this corp.",
                        verbose_name="Enabled",
                    ),
                ),
                (
                    "last_scanned_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="Last Scanned"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Drill Tax Payment Config",
                "verbose_name_plural": "Drill Tax Payment Configs",
            },
        ),
    ]
