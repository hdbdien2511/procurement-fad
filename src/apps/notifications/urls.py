from django.urls import path

from . import views

urlpatterns = [
    path("cai-dat/email/", views.email_settings, name="email_settings"),
    path("cai-dat/email/gui-thu/", views.email_send_test, name="email_send_test"),
]
