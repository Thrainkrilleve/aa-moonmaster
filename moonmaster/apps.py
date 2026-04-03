from django.apps import AppConfig


class MoonMasterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "moonmaster"
    verbose_name = "Moon Master"
    label = "moonmaster"

    def ready(self):
        # AA's main_character_required decorator blocks every user—including
        # superusers—who have no linked EVE character.  The excluded_views
        # mechanism in UrlHook only activates when the app is listed in
        # APPS_WITH_PUBLIC_VIEWS, which we cannot guarantee.  Patch
        # user_has_main_character directly so superusers are always passed
        # through; normal users still need a main character.
        import allianceauth.authentication.decorators as _dec

        _original = _dec.user_has_main_character

        def _superuser_passthrough(user):
            if getattr(user, "is_superuser", False):
                return True
            return _original(user)

        _dec.user_has_main_character = _superuser_passthrough
