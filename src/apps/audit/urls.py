from django.urls import path

from . import views

urlpatterns = [
    path("nhat-ky/", views.audit_list, name="audit_list"),
    path("nhat-ky/xuat/", views.audit_export, name="audit_export"),
]
