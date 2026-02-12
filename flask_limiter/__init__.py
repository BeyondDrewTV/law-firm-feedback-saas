"""Local fallback shim for flask_limiter when package isn't available in this environment."""

class Limiter:
    def __init__(self, key_func=None, app=None, default_limits=None):
        self.key_func = key_func
        self.app = app
        self.default_limits = default_limits or []

    def limit(self, _limit_value):
        def decorator(fn):
            return fn
        return decorator
