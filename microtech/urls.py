from __future__ import annotations

from django.urls import path

from microtech.views.webhooks import microtech_graphql_job_webhook

app_name = "microtech"

urlpatterns = [
    path("graphql-jobs/webhook/", microtech_graphql_job_webhook, name="graphql_job_webhook"),
]
