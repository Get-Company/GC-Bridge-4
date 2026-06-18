from django.urls import path

from qrcodes import views

app_name = "qrcodes"

urlpatterns = [
    path("", views.qr_code_list, name="list"),
    path("new/", views.qr_code_create, name="create"),
    path("<int:pk>/", views.qr_code_detail, name="detail"),
    path("<int:pk>/edit/", views.qr_code_edit, name="edit"),
    path("<int:pk>/delete/", views.qr_code_delete, name="delete"),
    path("<int:pk>/preview/", views.qr_code_preview, name="preview"),
    path("<int:pk>/download/<str:file_format>/<str:size_key>/", views.qr_code_download, name="download"),
]
