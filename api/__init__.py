"""API package.

The FastAPI app is loaded lazily so non-server entrypoints can import
``api.session`` without initializing routes, auth, and startup side effects.
"""

__all__ = ["app"]


def __getattr__(name):
    if name == "app":
        from .main import app

        return app
    raise AttributeError(name)
