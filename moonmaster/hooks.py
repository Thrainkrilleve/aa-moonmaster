from django.utils.translation import gettext_lazy as _

from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import urls


class MoonMasterMenuItem(MenuItemHook):
    def __init__(self):
        super().__init__(
            _("Moon Master"),
            "fas fa-moon",
            "moonmaster:dashboard",
            navactive=["moonmaster:"],
        )

    def render(self, request):
        if request.user.is_superuser or request.user.has_perm("moonmaster.basic_access"):
            return super().render(request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    return MoonMasterMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(
        urls,
        "moonmaster",
        r"^moonmaster/",
        excluded_views=[
            "moonmaster.views.dashboard",
            "moonmaster.views.moon_list",
            "moonmaster.views.moon_detail",
            "moonmaster.views.extractions",
            "moonmaster.views.metenox_list",
            "moonmaster.views.structure_list",
            "moonmaster.views.reports",
            "moonmaster.views.manage_owners",
            "moonmaster.views.add_owner",
            "moonmaster.views.remove_owner",
            "moonmaster.views.moon_profitability_api",
            "moonmaster.views.refresh_prices_api",
        ],
    )
