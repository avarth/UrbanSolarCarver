"""The local web service behind ``usc ui``."""
from .server import create_app

__all__ = ["create_app"]
