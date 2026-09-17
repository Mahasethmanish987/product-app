"""Orders. Creating one reserves stock; paying converts the reservation into
a sale; cancelling hands the units back.
"""
from typing import Annotated

from fastapi import APIRouter, Query, status

from logging_config import logger
from routers._common import Limit, Offset, ResourceId, page
from schemas import Order, OrderCreate, OrderPage, OrderStatus, OrderStatusUpdate
from store import store

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=OrderPage, summary="List orders, newest first")
def list_orders(
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    customer: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    limit: Limit = 20,
    offset: Offset = 0,
):
    items, total = store.list_orders(
        status=status_filter, customer=customer, limit=limit, offset=offset
    )

    return page(items, total, limit, offset)


@router.post(
    "",
    response_model=Order,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order and reserve its stock",
)
def create_order(body: OrderCreate):
    order = store.create_order(
        customer=body.customer,
        lines=[line.model_dump() for line in body.lines],
    )

    logger.info(
        "Order created",
        extra={"order_id": order["id"], "customer": body.customer, "total": str(order["total"])},
    )
    return order


@router.get("/{order_id}", response_model=Order, summary="Get one order")
def get_order(order_id: ResourceId):
    return store.get_order(order_id)


@router.post("/{order_id}/status", response_model=Order, summary="Move an order's status")
def set_status(order_id: ResourceId, body: OrderStatusUpdate):
    order = store.set_order_status(order_id, body.status)

    logger.info(
        "Order status changed",
        extra={"order_id": order_id, "status": order["status"].value},
    )
    return order


@router.post("/{order_id}/pay", response_model=Order, summary="Shortcut for status=paid")
def pay(order_id: ResourceId):
    return store.set_order_status(order_id, OrderStatus.PAID)


@router.post("/{order_id}/cancel", response_model=Order, summary="Shortcut for status=cancelled")
def cancel(order_id: ResourceId):
    return store.set_order_status(order_id, OrderStatus.CANCELLED)
