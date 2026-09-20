"""Liveness, readiness, build metadata and the Prometheus scrape target.

Kubernetes talks to the probes; they must stay cheap and dependency-free.
Prometheus talks to /metrics.
"""
import os
import time

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from logging_config import SERVICE_NAME, logger
from metrics import register_store_collector
from store import store

router = APIRouter(tags=["system"])

STARTED_AT = time.time()
VERSION = os.getenv("SERVICE_VERSION", "0.2.0")
COMMIT = os.getenv("GIT_COMMIT", "unknown")

# The catalogue gauges read the store when Prometheus scrapes, so the
# collector has to be attached before the first scrape rather than on the
# first mutation.
register_store_collector(store)


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


@router.get(
    "/metrics",
    summary="Prometheus scrape target",
    response_class=Response,
    include_in_schema=False,
)
def metrics():
    """Render the registry in Prometheus' text format.

    Left out of the OpenAPI schema and off the public Traefik route: this is
    for the in-cluster scraper, not for API clients.
    """
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
