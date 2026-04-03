from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("moonmaster", "0003_structure_fuel_blocks_per_hour"),
    ]

    operations = [
        migrations.AddField(
            model_name="structure",
            name="state",
            field=models.CharField(
                default="unknown",
                help_text="Raw ESI structure state string.",
                max_length=60,
                verbose_name="State",
            ),
        ),
        migrations.AddField(
            model_name="structure",
            name="state_timer_end",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When the current reinforce or vulnerability timer expires.",
                verbose_name="State Timer End",
            ),
        ),
        migrations.AddField(
            model_name="structure",
            name="reinforce_hour",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text="Hour of day (0-23 UTC) when the vulnerability window starts.",
                verbose_name="Reinforce Hour (UTC)",
            ),
        ),
        migrations.AddField(
            model_name="structure",
            name="reinforce_weekday",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text="0=Monday … 6=Sunday. Null if no specific day is set.",
                verbose_name="Reinforce Weekday",
            ),
        ),
        migrations.AddField(
            model_name="structure",
            name="services_raw",
            field=models.JSONField(
                default=list,
                help_text="Fitted service modules from ESI: [{name, state}, …].",
                verbose_name="Services",
            ),
        ),
        migrations.AddField(
            model_name="structure",
            name="unanchors_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Unanchors At",
            ),
        ),
    ]
