from __future__ import annotations

from contextlib import contextmanager

from .graphql_client import MicrotechGraphQLClientService


class MicrotechConnectionConfig:
    """Compatibility shim for old imports.

    Direct Microtech COM connections were removed from GC-Bridge. The external
    GraphQL wrapper owns the COM worker and credentials now.
    """

    @classmethod
    def from_env(cls) -> "MicrotechConnectionConfig":
        return cls()


class MicrotechConnectionService(MicrotechGraphQLClientService):
    """Compatibility alias for the GraphQL client service."""


@contextmanager
def microtech_connection(**_kwargs):
    """Return a Microtech GraphQL client.

    The public name is kept temporarily so existing services and tests can be
    migrated incrementally without reintroducing a direct COM dependency.
    """

    yield MicrotechGraphQLClientService()
