"""Request and response models.

Pydantic validates these before a router ever runs, so the handlers below
only deal with data that is already known-good.
"""
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISCONTINUED = "discontinued"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class SortField(StrEnum):
    NAME = "name"
    PRICE = "price"
    CREATED_AT = "created_at"
    RATING = "rating"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class StockMovementReason(StrEnum):
    RESTOCK = "restock"
    SALE = "sale"
    RETURN = "return"
    DAMAGE = "damage"
    CORRECTION = "correction"


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=500)


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)


class Category(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    product_count: int = 0
    created_at: datetime


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------

class ProductBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    sku: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9\-]+$")
    price: Decimal = Field(gt=0, le=Decimal("1000000"), decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    category_id: int
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    status: ProductStatus = ProductStatus.DRAFT

    @field_validator("tags")
    @classmethod
    def normalise_tags(cls, tags):
        """Lowercase, trim, drop blanks, de-duplicate -- order preserved."""
        seen = {}
        for tag in tags:
            cleaned = tag.strip().lower()
            if cleaned:
                seen[cleaned] = None
        return list(seen)


class ProductCreate(ProductBase):
    initial_stock: int = Field(default=0, ge=0, le=1_000_000)


class ProductReplace(ProductBase):
    """Body for PUT -- every field is required, the resource is overwritten."""


class ProductUpdate(BaseModel):
    """Body for PATCH -- only the fields present are touched."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    price: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000"), decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    category_id: int | None = None
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)
    status: ProductStatus | None = None


class Product(BaseModel):
    id: int
    name: str
    sku: str
    price: Decimal
    currency: str
    category_id: int
    description: str | None
    tags: list[str]
    status: ProductStatus
    stock: int
    reserved: int
    available: int
    rating: float | None
    review_count: int
    created_at: datetime
    updated_at: datetime


class BulkProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    products: list[ProductCreate] = Field(min_length=1, max_length=100)


class BulkResult(BaseModel):
    created: list[Product]
    failed: list[dict]


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------

class InventoryState(BaseModel):
    product_id: int
    sku: str
    stock: int
    reserved: int
    available: int
    low_stock_threshold: int
    is_low: bool


class StockAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delta: int = Field(description="Signed change; negative removes stock")
    reason: StockMovementReason = StockMovementReason.CORRECTION
    note: str | None = Field(default=None, max_length=200)

    @field_validator("delta")
    @classmethod
    def reject_zero(cls, delta):
        if delta == 0:
            raise ValueError("delta must not be zero")
        return delta


class StockReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(gt=0, le=10_000)


class StockMovement(BaseModel):
    id: int
    product_id: int
    delta: int
    reason: StockMovementReason
    note: str | None
    stock_after: int
    created_at: datetime


# --------------------------------------------------------------------------
# Reviews
# --------------------------------------------------------------------------

class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: str = Field(min_length=1, max_length=80)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class Review(BaseModel):
    id: int
    product_id: int
    author: str
    rating: int
    comment: str | None
    created_at: datetime


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------

class OrderLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int
    quantity: int = Field(gt=0, le=1000)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer: str = Field(min_length=1, max_length=120)
    lines: list[OrderLineCreate] = Field(min_length=1, max_length=50)


class OrderLine(BaseModel):
    product_id: int
    sku: str
    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class Order(BaseModel):
    id: int
    customer: str
    status: OrderStatus
    lines: list[OrderLine]
    total: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime


class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus


# --------------------------------------------------------------------------
# Shared envelopes
# --------------------------------------------------------------------------

class Page(BaseModel):
    """Pagination metadata returned alongside every list endpoint."""

    total: int
    limit: int
    offset: int
    has_more: bool


class ProductPage(BaseModel):
    items: list[Product]
    page: Page


class ReviewPage(BaseModel):
    items: list[Review]
    page: Page


class OrderPage(BaseModel):
    items: list[Order]
    page: Page


class CategoryStats(BaseModel):
    category_id: int
    name: str
    product_count: int
    total_stock: int
    inventory_value: Decimal


class Overview(BaseModel):
    product_count: int
    active_product_count: int
    category_count: int
    order_count: int
    review_count: int
    total_stock: int
    inventory_value: Decimal
    average_rating: float | None
    by_category: list[CategoryStats]


class DeleteAck(BaseModel):
    deleted: bool
    id: int
