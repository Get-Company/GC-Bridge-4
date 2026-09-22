from __future__ import annotations

from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.services import BaseService
from microtech.models import MicrotechSettings
from microtech.services.graphql_client import GraphQLMicrotechError


class GraphQLMicrotechCircuitOpen(GraphQLMicrotechError):
    """Der Wrapper ist nach wiederholten Transportfehlern kurzzeitig gesperrt."""

    def __init__(self, *, retry_at) -> None:
        self.retry_at = retry_at
        super().__init__(f"Microtech GraphQL ist voruebergehend nicht erreichbar. Neuer Versuch ab {retry_at.isoformat()}.")


class MicrotechGraphQLCircuitBreakerService(BaseService):
    """Koordiniert einen datenbankgestuetzten GraphQL-Circuit-Breaker ueber alle Worker."""

    model = MicrotechSettings

    @staticmethod
    def _failure_threshold() -> int:
        return max(1, int(getattr(settings, "MICROTECH_GRAPHQL_CIRCUIT_FAILURE_THRESHOLD", 3)))

    @staticmethod
    def _reset_seconds() -> int:
        return max(1, int(getattr(settings, "MICROTECH_GRAPHQL_CIRCUIT_RESET_SECONDS", 300)))

    @classmethod
    def is_retryable_transport_error(cls, error: Exception) -> bool:
        if isinstance(error, GraphQLMicrotechCircuitOpen):
            return True
        if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
        if isinstance(error, requests.exceptions.HTTPError):
            response = error.response
            return response is not None and int(response.status_code) >= 500
        return False

    def ensure_request_allowed(self) -> None:
        now = timezone.now()
        with transaction.atomic():
            config = MicrotechSettings.objects.select_for_update().get_or_create(pk=1)[0]
            if config.graphql_circuit_open_until and config.graphql_circuit_open_until > now:
                raise GraphQLMicrotechCircuitOpen(retry_at=config.graphql_circuit_open_until)

    def record_success(self) -> None:
        now = timezone.now()
        MicrotechSettings.objects.filter(pk=1).update(
            graphql_circuit_open_until=None,
            graphql_consecutive_failures=0,
            graphql_last_error="",
            updated_at=now,
        )

    def record_failure(self, error: Exception) -> None:
        if not self.is_retryable_transport_error(error):
            return

        now = timezone.now()
        with transaction.atomic():
            config = MicrotechSettings.objects.select_for_update().get_or_create(pk=1)[0]
            failures = config.graphql_consecutive_failures + 1
            config.graphql_consecutive_failures = failures
            config.graphql_last_failure_at = now
            config.graphql_last_error = str(error)
            if failures >= self._failure_threshold():
                config.graphql_circuit_open_until = now + timedelta(seconds=self._reset_seconds())
            config.save(
                update_fields=(
                    "graphql_circuit_open_until",
                    "graphql_consecutive_failures",
                    "graphql_last_failure_at",
                    "graphql_last_error",
                    "updated_at",
                )
            )
