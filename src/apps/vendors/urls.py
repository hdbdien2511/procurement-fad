from django.urls import path

from . import views

urlpatterns = [
    path("nha-cung-cap/", views.vendor_list, name="vendor_list"),
    path("nha-cung-cap/xuat/", views.vendor_export, name="vendor_export"),
    path("nha-cung-cap/nhap-excel/", views.vendor_import, name="vendor_import"),
]
