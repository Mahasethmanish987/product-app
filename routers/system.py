"""Liveness, readiness and build metadata.

Kubernetes talks to these; they must stay cheap and dependency-free.
"""
import os
import time

from fastapi import APIRouter

from logging_config import SERVICE_NAME, logger
from store import store

router = APIRouter(tags=["system"])

STARTED_AT = time.time()
VERSION = os.getenv("SERVICE_VERSION", "0.2.0")
COMMIT = os.getenv("GIT_COMMIT", "unknown")


@router.get("/health", summary="Liveness probe")
def health():
    logger.info("Health endpoint called")

    return {
        "status": "healthy",
        "service": SERVICE_NAME,
    }


@router.get("/ready", summary="Readiness probe")
def ready():
    """Ready means the store answers. With a real database this is the ping."""
    try:
        store.overview()
    except Exception:
        logger.exception("Readiness check failed")
        return {"status": "degraded", "service": SERVICE_NAME, "checks": {"store": "down"}}

    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "checks": {"store": "up"},
    }


@router.get("/version", summary="Build metadata")
def version():
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "commit": COMMIT,
        "uptime_seconds": round(time.time() - STARTED_AT, 3),
    }
