from django.urls import path

from . import views

urlpatterns = [
    path("to-trinh/", views.requisition_list, name="requisition_list"),
    path("to-trinh/xuat/", views.requisition_export, name="requisition_export"),
    path("to-trinh/tao/", views.requisition_create, name="requisition_create"),
    path("to-trinh/<int:pk>/", views.requisition_detail, name="requisition_detail"),
    path("to-trinh/<int:pk>/nop/", views.requisition_submit, name="requisition_submit"),
    path("to-trinh/<int:pk>/sao-chep/", views.requisition_copy, name="requisition_copy"),
    path("to-trinh/<int:pk>/sua-lai/", views.requisition_revise, name="requisition_revise"),
    path("to-trinh/<int:pk>/huy/", views.requisition_cancel, name="requisition_cancel"),
    path("to-trinh/<int:pk>/giu-cho-lai/", views.requisition_retry_reserve, name="requisition_retry_reserve"),
    path("to-trinh/<int:pk>/chung-tu/", views.requisition_upload, name="requisition_upload"),
    path("to-trinh/<int:pk>/tien-kiem/", views.requisition_precheck, name="requisition_precheck"),
    path("to-trinh/<int:pk>/tien-kiem/xu-ly/", views.requisition_precheck_act, name="requisition_precheck_act"),
]
