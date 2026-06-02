"""Vercel serverless entrypoint — exposes the FastAPI ASGI app."""

from app.routes import app

__all__ = ["app"]
