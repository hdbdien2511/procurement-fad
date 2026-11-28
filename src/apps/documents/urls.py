from django.urls import path

from . import views

urlpatterns = [
    path("tim-kiem/", views.search, name="search"),
    path("chung-tu/<uuid:pk>/tai-ve/", views.download, name="document_download"),
    path("chung-tu/<uuid:pk>/xem/", views.view_inline, name="document_view"),
]
