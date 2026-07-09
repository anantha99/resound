"""Small Temporal decorator compatibility layer.

The production dependency is ``temporalio``. These fallbacks keep local tests and
static imports useful if the Temporal package is unavailable during isolated
tooling runs.
"""

from __future__ import annotations

try:  # pragma: no cover - exercised when temporalio is installed.
    from temporalio import activity, workflow
except ImportError:  # pragma: no cover - defensive fallback.

    class _NoopNamespace:
        @staticmethod
        def defn(fn_or_cls=None, **_kwargs):
            def decorator(value):
                return value

            return decorator(fn_or_cls) if fn_or_cls is not None else decorator

        @staticmethod
        def run(fn):
            return fn

    activity = _NoopNamespace()
    workflow = _NoopNamespace()
