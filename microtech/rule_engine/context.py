from __future__ import annotations


class EvaluationContext:
    def __init__(self, root: object):
        self.root = root

    def get(self, path: str) -> object:
        current: object = self.root
        for segment in str(path).split("__"):
            if current is None or not hasattr(current, segment):
                return None
            current = getattr(current, segment)
            if callable(current):
                current = current()
        return current
