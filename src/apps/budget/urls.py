from django.urls import path

from . import views

urlpatterns = [
    path("ngan-sach/", views.budget_list, name="budget_list"),
    path("ngan-sach/xuat/", views.budget_export, name="budget_export"),
    path("ngan-sach/nhap-excel/", views.budget_import, name="budget_import"),
    path("ngan-sach/<int:pk>/so-cai/", views.budget_ledger, name="budget_ledger"),
]
