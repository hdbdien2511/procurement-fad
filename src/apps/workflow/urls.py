from django.urls import path

from . import views

urlpatterns = [
    path("", views.inbox_page, name="home"),
    path("viec/xu-ly-hang-loat/", views.bulk_act, name="task_bulk_act"),
    path("viec/<int:pk>/", views.task_detail, name="task_detail"),
    path("viec/<int:pk>/xu-ly/", views.task_act, name="task_act"),
    path("uy-quyen/", views.delegations, name="delegations"),
    path("uy-quyen/<int:pk>/thu-hoi/", views.delegation_revoke, name="delegation_revoke"),
]
