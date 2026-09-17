"""Stock levels, reservations and the movement ledger.

`stock` is what sits on the shelf, `reserved` is what a pending order has
claimed, and `available = stock - reserved` is what anyone else can buy.
"""
from typing import Annotated

from fastapi import APIRouter, Query

from logging_config import logger
from routers._common import ResourceId
from schemas import InventoryState, StockAdjustment, StockMovement, StockReservation
from store import store

router = APIRouter(prefix="/products/{product_id}/inventory", tags=["inventory"])


@router.get("", response_model=InventoryState, summary="Current stock for a product")
def get_inventory(product_id: ResourceId):
    return store.inventory(product_id)


@router.post("/adjust", response_model=InventoryState, summary="Add or remove stock")
def adjust(product_id: ResourceId, body: StockAdjustment):
    state = store.adjust_stock(product_id, body.delta, body.reason, body.note)

    logger.info(
        "Stock adjusted",
        extra={
            "product_id": product_id,
            "delta": body.delta,
            "reason": body.reason.value,
            "stock": state["stock"],
        },
    )
    return state


@router.post("/reserve", response_model=InventoryState, summary="Hold stock for an order")
def reserve(product_id: ResourceId, body: StockReservation):
    state = store.reserve_stock(product_id, body.quantity)

    logger.info(
        "Stock reserved",
        extra={
            "product_id": product_id,
            "quantity": body.quantity,
            "available": state["available"],
        },
    )
    return state


@router.post("/release", response_model=InventoryState, summary="Give a reservation back")
def release(product_id: ResourceId, body: StockReservation):
    state = store.release_stock(product_id, body.quantity)

    logger.info(
        "Stock released",
        extra={
            "product_id": product_id,
            "quantity": body.quantity,
            "available": state["available"],
        },
    )
    return state


@router.get(
    "/movements",
    response_model=list[StockMovement],
    summary="Audit trail of stock changes, newest first",
)
def movements(
    product_id: ResourceId,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return store.list_movements(product_id, limit=limit)
