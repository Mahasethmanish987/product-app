"""Customer reviews. The product's rating is derived from these."""
from fastapi import APIRouter, status

from logging_config import logger
from routers._common import Limit, Offset, ResourceId, page
from schemas import DeleteAck, Review, ReviewCreate, ReviewPage
from store import store

router = APIRouter(prefix="/products/{product_id}/reviews", tags=["reviews"])


@router.get("", response_model=ReviewPage, summary="List reviews, newest first")
def list_reviews(product_id: ResourceId, limit: Limit = 20, offset: Offset = 0):
    items, total = store.list_reviews(product_id, limit=limit, offset=offset)

    return page(items, total, limit, offset)


@router.post(
    "",
    response_model=Review,
    status_code=status.HTTP_201_CREATED,
    summary="Leave a review",
)
def create_review(product_id: ResourceId, body: ReviewCreate):
    review = store.add_review(
        product_id, author=body.author, rating=body.rating, comment=body.comment
    )

    logger.info(
        "Review added",
        extra={"product_id": product_id, "review_id": review["id"], "rating": body.rating},
    )
    return review


@router.delete("/{review_id}", response_model=DeleteAck, summary="Delete a review")
def delete_review(product_id: ResourceId, review_id: ResourceId):
    store.delete_review(product_id, review_id)

    logger.info("Review deleted", extra={"product_id": product_id, "review_id": review_id})
    return {"deleted": True, "id": review_id}
