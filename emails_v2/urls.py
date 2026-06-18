# emails_v2/urls.py
from django.urls import path
from emails_v2 import views

app_name = "email_builder"

urlpatterns = [
    path("", views.campaign_list, name="list"),
    path("campaign/create/", views.campaign_create, name="create"),
    path("campaign/<int:campaign_id>/", views.campaign_editor, name="editor"),
    path("htmx/block/create/", views.htmx_block_create, name="htmx_block_create"),
    path("htmx/block/<int:block_id>/reorder/", views.htmx_block_reorder, name="htmx_block_reorder"),
    path("htmx/block/<int:block_id>/delete/", views.htmx_block_delete, name="htmx_block_delete"),
    path("htmx/block/<int:block_id>/vars/", views.htmx_variable_panel, name="htmx_variable_panel"),
    path("htmx/block/<int:block_id>/vars/save/", views.htmx_variable_save, name="htmx_variable_save"),
    path("htmx/campaign/<int:campaign_id>/preview/", views.htmx_preview, name="htmx_preview"),
]
