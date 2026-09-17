"""Read-only aggregates over the catalogue."""
from typing import Annotated

from fastapi import APIRouter, Query

from schemas import InventoryState, Overview
from store import store

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=Overview, summary="Catalogue-wide totals")
def overview():
    return store.overview()


@router.get(
    "/low-stock",
    response_model=list[InventoryState],
    summary="Products at or below their low-stock threshold",
)
def low_stock(
    threshold: Annotated[
        int | None,
        Query(ge=0, le=10_000, description="Override each product's own threshold"),
    ] = None,
):
    return store.low_stock(threshold)
