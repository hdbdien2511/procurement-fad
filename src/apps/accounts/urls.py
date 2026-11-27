from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("dang-nhap/", views.LoginView.as_view(), name="login"),
    path("xac-thuc-otp/", views.otp_verify, name="otp_verify"),
    path("chua-dang-ky-otp/", views.otp_required, name="otp_required"),
    path("dang-xuat/", LogoutView.as_view(), name="logout"),
]
