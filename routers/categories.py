"""Category CRUD, plus the products that belong to a category."""
from fastapi import APIRouter, status

from logging_config import logger
from routers._common import Limit, Offset, ResourceId, page
from schemas import Category, CategoryCreate, CategoryUpdate, DeleteAck, ProductPage
from store import store

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[Category], summary="List categories")
def list_categories():
    return store.list_categories()


@router.post(
    "",
    response_model=Category,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
)
def create_category(body: CategoryCreate):
    category = store.create_category(
        name=body.name, slug=body.slug, description=body.description
    )

    logger.info("Category created", extra={"category_id": category["id"], "slug": body.slug})
    return category


@router.get("/{category_id}", response_model=Category, summary="Get one category")
def get_category(category_id: ResourceId):
    return store.get_category(category_id)


@router.patch("/{category_id}", response_model=Category, summary="Update a category")
def update_category(category_id: ResourceId, body: CategoryUpdate):
    category = store.update_category(category_id, body.model_dump(exclude_unset=True))

    logger.info("Category updated", extra={"category_id": category_id})
    return category


@router.delete("/{category_id}", response_model=DeleteAck, summary="Delete an empty category")
def delete_category(category_id: ResourceId):
    store.delete_category(category_id)

    logger.info("Category deleted", extra={"category_id": category_id})
    return {"deleted": True, "id": category_id}


@router.get(
    "/{category_id}/products",
    response_model=ProductPage,
    summary="List the products in a category",
)
def category_products(category_id: ResourceId, limit: Limit = 20, offset: Offset = 0):
    store.get_category(category_id)  # 404s if the category is gone

    items, total = store.list_products(category_id=category_id, limit=limit, offset=offset)
    return page(items, total, limit, offset)
