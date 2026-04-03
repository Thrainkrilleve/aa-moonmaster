from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("moonmaster", "0002_alter_moon_ore_composition_alter_moon_rarity_class_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="structure",
            name="fuel_blocks_per_hour",
            field=models.FloatField(
                default=0.0,
                help_text="Sum of fuel blocks/hour consumed by all online service modules. Derived from ESI structure services.",
                verbose_name="Fuel Blocks/hr",
            ),
        ),
    ]
