from django.urls import path

from . import views

app_name = "moonmaster"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("moons/", views.moon_list, name="moon_list"),
    path("moons/<int:moon_id>/", views.moon_detail, name="moon_detail"),
    path("extractions/", views.extractions, name="extractions"),
    path("metenox/", views.metenox_list, name="metenox_list"),
    path("structures/", views.structure_list, name="structure_list"),
    path("reports/", views.reports, name="reports"),
    # Owner management
    path("owners/", views.manage_owners, name="manage_owners"),
    path("owners/add/", views.add_owner, name="add_owner"),
    path("owners/sync-all/", views.sync_all_now, name="sync_all_now"),
    path("owners/<int:owner_id>/remove/", views.remove_owner, name="remove_owner"),
    path("owners/character/<int:pk>/remove/", views.remove_owner_character, name="remove_owner_character"),
    path("owners/<int:owner_id>/sync/", views.sync_owner_now, name="sync_owner_now"),
    path("owners/<int:owner_id>/tax/", views.update_tax_config, name="update_tax_config"),
    # Moon survey import
    path("survey/import/", views.import_survey, name="import_survey"),
    # AJAX / API endpoints
    path("api/moon/<int:moon_id>/profitability/", views.moon_profitability_api, name="moon_profitability_api"),
    path("api/prices/refresh/", views.refresh_prices_api, name="refresh_prices_api"),
]
