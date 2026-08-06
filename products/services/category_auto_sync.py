from __future__ import annotations

from contextlib import contextmanager
from threading import local


_state = local()


def is_category_auto_sync_disabled() -> bool:
    """Return whether local category changes must not be sent back to Shopware."""
    return bool(getattr(_state, "disabled", False))


@contextmanager
def disable_category_auto_sync():
    """Suppress outbound category signals while importing data from Shopware."""
    previous = is_category_auto_sync_disabled()
    _state.disabled = True
    try:
        yield
    finally:
        _state.disabled = previous
