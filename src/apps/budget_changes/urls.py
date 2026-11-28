from django.urls import path

from . import views

urlpatterns = [
    path("ngan-sach/de-nghi/", views.budget_change_list, name="budget_change_list"),
    path("ngan-sach/de-nghi/tao/", views.budget_change_create, name="budget_change_create"),
    path("ngan-sach/de-nghi/<int:pk>/", views.budget_change_detail, name="budget_change_detail"),
    path("ngan-sach/de-nghi/<int:pk>/nop/", views.budget_change_submit, name="budget_change_submit"),
]
