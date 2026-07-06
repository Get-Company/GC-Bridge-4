from __future__ import annotations

from contextlib import contextmanager

from .graphql_client import MicrotechGraphQLClientService


@contextmanager
def microtech_connection(**_kwargs):
    """Return a Microtech GraphQL client.

    The public name is kept temporarily so existing services and tests can be
    migrated incrementally without reintroducing a direct COM dependency.
    """

    yield MicrotechGraphQLClientService()
