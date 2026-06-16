from django.contrib import admin
from django.urls import path

from telefon.views import ZeitsteuerungDetailView, ZeitsteuerungListView

_default_get_urls = admin.site.get_urls


def _telefon_urls():
    return [
        path(
            "telefon/zeitsteuerung/",
            admin.site.admin_view(ZeitsteuerungListView.as_view(admin_site=admin.site)),
            name="telefon_zeitsteuerung_list",
        ),
        path(
            "telefon/zeitsteuerung/<str:service_id>/",
            admin.site.admin_view(ZeitsteuerungDetailView.as_view(admin_site=admin.site)),
            name="telefon_zeitsteuerung_detail",
        ),
    ] + _default_get_urls()


admin.site.get_urls = _telefon_urls
