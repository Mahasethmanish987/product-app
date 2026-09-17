"""Product CRUD, search and bulk import."""
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from errors import ServiceError, ValidationError
from logging_config import logger
from routers._common import Limit, Offset, ResourceId, page
from schemas import (
    BulkProductCreate,
    BulkResult,
    DeleteAck,
    Product,
    ProductCreate,
    ProductPage,
    ProductReplace,
    ProductStatus,
    ProductUpdate,
    SortField,
    SortOrder,
)
from store import store

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductPage, summary="Search and list products")
def list_products(
    q: Annotated[str | None, Query(min_length=1, max_length=120, description="Free text")] = None,
    category_id: Annotated[int | None, Query(ge=1)] = None,
    status_filter: Annotated[ProductStatus | None, Query(alias="status")] = None,
    tag: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    in_stock: bool | None = None,
    sort: SortField = SortField.CREATED_AT,
    order: SortOrder = SortOrder.ASC,
    limit: Limit = 20,
    offset: Offset = 0,
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValidationError(
            "min_price must not be greater than max_price",
            min_price=str(min_price),
            max_price=str(max_price),
        )

    items, total = store.list_products(
        q=q,
        category_id=category_id,
        status=status_filter,
        tag=tag,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        sort=sort.value,
        order=order.value,
        limit=limit,
        offset=offset,
    )

    logger.info(
        "Listed products",
        extra={"returned": len(items), "total": total, "query": q},
    )

    return page(items, total, limit, offset)


@router.post(
    "",
    response_model=Product,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
)
def create_product(body: ProductCreate, response: Response):
    product = store.create_product(**body.model_dump())

    response.headers["Location"] = f"/products/{product['id']}"
    logger.info("Product created", extra={"product_id": product["id"], "sku": product["sku"]})
    return product


@router.post(
    "/bulk",
    response_model=BulkResult,
    status_code=status.HTTP_207_MULTI_STATUS,
    summary="Create many products, reporting per-item failures",
)
def bulk_create(body: BulkProductCreate):
    """Partial success is the point: one bad SKU should not sink the batch."""
    created, failed = [], []

    for index, item in enumerate(body.products):
        try:
            created.append(store.create_product(**item.model_dump()))
        except ServiceError as exc:
            failed.append({"index": index, "sku": item.sku, **exc.to_dict()["error"]})

    logger.info(
        "Bulk create finished",
        extra={"created_count": len(created), "failed_count": len(failed)},
    )
    return {"created": created, "failed": failed}


@router.get("/{product_id}", response_model=Product, summary="Get one product")
def get_product(product_id: ResourceId):
    logger.info("Fetching product", extra={"product_id": product_id})
    return store.get_product(product_id)


@router.put("/{product_id}", response_model=Product, summary="Replace a product")
def replace_product(product_id: ResourceId, body: ProductReplace):
    product = store.replace_product(product_id, body.model_dump())

    logger.info("Product replaced", extra={"product_id": product_id})
    return product


@router.patch("/{product_id}", response_model=Product, summary="Partially update a product")
def update_product(product_id: ResourceId, body: ProductUpdate):
    product = store.update_product(product_id, body.model_dump(exclude_unset=True))

    logger.info("Product updated", extra={"product_id": product_id})
    return product


@router.delete("/{product_id}", response_model=DeleteAck, summary="Delete a product")
def delete_product(product_id: ResourceId):
    store.delete_product(product_id)

    logger.info("Product deleted", extra={"product_id": product_id})
    return {"deleted": True, "id": product_id}
