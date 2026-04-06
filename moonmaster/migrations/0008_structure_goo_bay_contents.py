from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("moonmaster", "0007_alter_oreprice_source_alter_ownercharacter_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="structure",
            name="goo_bay_contents",
            field=models.JSONField(
                default=list,
                help_text="Snapshot of processed moon materials in the bay: [{type_id, name, quantity, volume_m3}, …].",
                verbose_name="Goo Bay Contents",
            ),
        ),
    ]
