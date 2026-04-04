from django.db import migrations, models
import django.db.models.deletion


def create_owner_characters(apps, schema_editor):
    """Seed OwnerCharacter rows from existing StructureOwner.character FKs."""
    StructureOwner = apps.get_model("moonmaster", "StructureOwner")
    OwnerCharacter = apps.get_model("moonmaster", "OwnerCharacter")
    for owner in StructureOwner.objects.filter(character__isnull=False):
        OwnerCharacter.objects.get_or_create(
            owner=owner,
            character=owner.character,
            defaults={"is_primary": True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("moonmaster", "0004_structure_reinforce_fields"),
        ("eveonline", "0017_alliance_and_corp_names_are_not_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="OwnerCharacter",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "is_primary",
                    models.BooleanField(
                        default=False,
                        help_text="Primary character — tried first on every sync.",
                        verbose_name="Primary",
                    ),
                ),
                ("added_at", models.DateTimeField(auto_now_add=True, verbose_name="Added")),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="owner_characters",
                        to="moonmaster.structureowner",
                        verbose_name="Owner",
                    ),
                ),
                (
                    "character",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="eveonline.evecharacter",
                        verbose_name="Character",
                    ),
                ),
            ],
            options={
                "verbose_name": "Owner Character",
                "verbose_name_plural": "Owner Characters",
                "ordering": ["-is_primary", "id"],
                "unique_together": {("owner", "character")},
            },
        ),
        migrations.RunPython(create_owner_characters, migrations.RunPython.noop),
    ]
