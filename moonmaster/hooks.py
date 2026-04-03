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
        if request.user.has_perm("moonmaster.basic_access"):
            return super().render(request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    return MoonMasterMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "moonmaster", r"^moonmaster/")
