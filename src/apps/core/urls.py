from django.urls import path

from . import settings_views

urlpatterns = [
    path("cai-dat/", settings_views.settings_page, name="settings_page"),
    path("cai-dat/tham-so/", settings_views.settings_params, name="settings_params"),
    path("cai-dat/ty-gia/", settings_views.settings_rate_add, name="settings_rate_add"),
]
