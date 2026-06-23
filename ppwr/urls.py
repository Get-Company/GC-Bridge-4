from django.urls import path

from ppwr import views

app_name = "ppwr"

urlpatterns = [
    path("erklaerung/<slug:slug>/", views.erklaerung_html, name="erklaerung-html"),
    path("erklaerung/<slug:slug>/pdf/", views.erklaerung_pdf, name="erklaerung-pdf"),
]
