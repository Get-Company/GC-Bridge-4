from __future__ import annotations

from collections.abc import Mapping


class EvaluationContext:
    def __init__(self, root: object):
        self.root = root

    def get(self, path: str) -> object:
        current: object = self.root
        for segment in str(path).split("__"):
            if current is None:
                return None
            if isinstance(current, Mapping):
                if segment not in current:
                    return None
                current = current[segment]
            else:
                if not hasattr(current, segment):
                    return None
                current = getattr(current, segment)
            # Rule field paths are data paths.  Calling a method while resolving
            # a condition or template can trigger hidden database work or side
            # effects, so methods are intentionally never invoked implicitly.
            if callable(current):
                return None
        return current
