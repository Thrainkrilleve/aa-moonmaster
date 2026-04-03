from django.apps import AppConfig


class MoonMasterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "moonmaster"
    verbose_name = "Moon Master"
    label = "moonmaster"

    def ready(self):
        # Import hooks module so @hooks.register decorators execute and the
        # menu_item_hook / url_hook are registered with AllianceAuth.
        from . import hooks  # noqa: F401

        # AA v4 uses a DB-driven, cache-guarded menu sync.  Once the cache key
        # is set, sync_all() never re-runs even if a new app is installed.
        # Clearing the key here (on every Django startup) ensures our MenuItem
        # row gets added to the DB on the next request.
        try:
            from allianceauth.menu.core.smart_sync import reset_menu_items_sync
            reset_menu_items_sync()
        except Exception:
            pass

        # AA's main_character_required decorator redirects every user—including
        # superusers—who have no linked EVE character.  Patch the check so
        # superusers always pass; regular users still need a main character.
        try:
            import allianceauth.authentication.decorators as _dec

            _original = _dec.user_has_main_character

            def _superuser_passthrough(user):
                if getattr(user, "is_superuser", False):
                    return True
                return _original(user)

            _dec.user_has_main_character = _superuser_passthrough
        except Exception:
            pass
