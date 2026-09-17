"""In-memory data store.

This stands in for a database. Everything is guarded by one re-entrant lock
because uvicorn runs sync endpoints in a thread pool, so two requests really
can touch the same dict at the same time.

Swapping this for a real database means reimplementing this class; no router
touches a dict directly.
"""
import itertools
import threading
from datetime import UTC, datetime
from decimal import Decimal

from errors import ConflictError, InsufficientStockError, NotFoundError
from schemas import OrderStatus, ProductStatus, StockMovementReason

DEFAULT_LOW_STOCK_THRESHOLD = 5


def _now():
    return datetime.now(UTC)


class Store:

    def __init__(self):
        self._lock = threading.RLock()
        self.reset()

    # -- lifecycle ---------------------------------------------------------

    def reset(self, seed=True):
        """Wipe and optionally re-seed. Tests call this between cases."""
        with self._lock:
            self._categories = {}
            self._products = {}
            self._reviews = {}
            self._orders = {}
            self._movements = {}

            self._category_ids = itertools.count(1)
            self._product_ids = itertools.count(1)
            self._review_ids = itertools.count(1)
            self._order_ids = itertools.count(1)
            self._movement_ids = itertools.count(1)

            if seed:
                self._seed()

    def _seed(self):
        electronics = self.create_category(
            name="Electronics", slug="electronics", description="Powered things"
        )
        accessories = self.create_category(
            name="Accessories", slug="accessories", description="Things for things"
        )

        self.create_product(
            name="Laptop",
            sku="LAP-001",
            price=Decimal("1299.00"),
            currency="USD",
            category_id=electronics["id"],
            description="14 inch developer laptop",
            tags=["portable", "work"],
            status=ProductStatus.ACTIVE,
            initial_stock=12,
        )
        self.create_product(
            name="Keyboard",
            sku="KEY-001",
            price=Decimal("89.99"),
            currency="USD",
            category_id=accessories["id"],
            description="Mechanical, tactile switches",
            tags=["input"],
            status=ProductStatus.ACTIVE,
            initial_stock=3,
        )

    # -- categories --------------------------------------------------------

    def list_categories(self):
        with self._lock:
            return [self._category_view(c) for c in self._categories.values()]

    def get_category(self, category_id):
        with self._lock:
            category = self._categories.get(category_id)
            if category is None:
                raise NotFoundError("category", category_id)
            return self._category_view(category)

    def create_category(self, *, name, slug, description=None):
        with self._lock:
            if any(c["slug"] == slug for c in self._categories.values()):
                raise ConflictError(f"category slug {slug!r} is already taken", slug=slug)

            category = {
                "id": next(self._category_ids),
                "name": name,
                "slug": slug,
                "description": description,
                "created_at": _now(),
            }
            self._categories[category["id"]] = category
            return self._category_view(category)

    def update_category(self, category_id, changes):
        with self._lock:
            category = self._categories.get(category_id)
            if category is None:
                raise NotFoundError("category", category_id)

            category.update({k: v for k, v in changes.items() if v is not None})
            return self._category_view(category)

    def delete_category(self, category_id):
        with self._lock:
            if category_id not in self._categories:
                raise NotFoundError("category", category_id)

            in_use = [p["id"] for p in self._products.values() if p["category_id"] == category_id]
            if in_use:
                raise ConflictError(
                    f"category {category_id} still has {len(in_use)} product(s)",
                    category_id=category_id,
                    product_ids=in_use[:10],
                )

            del self._categories[category_id]

    def _category_view(self, category):
        count = sum(1 for p in self._products.values() if p["category_id"] == category["id"])
        return {**category, "product_count": count}

    # -- products ----------------------------------------------------------

    def create_product(
        self,
        *,
        name,
        sku,
        price,
        currency,
        category_id,
        description=None,
        tags=None,
        status=ProductStatus.DRAFT,
        initial_stock=0,
    ):
        with self._lock:
            if category_id not in self._categories:
                raise NotFoundError("category", category_id)
            if any(p["sku"] == sku for p in self._products.values()):
                raise ConflictError(f"sku {sku!r} is already taken", sku=sku)

            now = _now()
            product = {
                "id": next(self._product_ids),
                "name": name,
                "sku": sku,
                "price": Decimal(price),
                "currency": currency,
                "category_id": category_id,
                "description": description,
                "tags": list(tags or []),
                "status": ProductStatus(status),
                "stock": initial_stock,
                "reserved": 0,
                "low_stock_threshold": DEFAULT_LOW_STOCK_THRESHOLD,
                "created_at": now,
                "updated_at": now,
            }
            self._products[product["id"]] = product

            if initial_stock:
                self._record_movement(
                    product, initial_stock, StockMovementReason.RESTOCK, "initial stock"
                )

            return self._product_view(product)

    def get_product(self, product_id):
        with self._lock:
            return self._product_view(self._require_product(product_id))

    def replace_product(self, product_id, values):
        with self._lock:
            product = self._require_product(product_id)

            if values["category_id"] not in self._categories:
                raise NotFoundError("category", values["category_id"])
            self._assert_sku_free(values["sku"], excluding=product_id)

            product.update(values)
            product["price"] = Decimal(values["price"])
            product["updated_at"] = _now()
            return self._product_view(product)

    def update_product(self, product_id, changes):
        with self._lock:
            product = self._require_product(product_id)

            if changes.get("category_id") is not None:
                if changes["category_id"] not in self._categories:
                    raise NotFoundError("category", changes["category_id"])

            for key, value in changes.items():
                if value is not None:
                    product[key] = Decimal(value) if key == "price" else value

            product["updated_at"] = _now()
            return self._product_view(product)

    def delete_product(self, product_id):
        with self._lock:
            product = self._require_product(product_id)

            if product["reserved"] > 0:
                raise ConflictError(
                    f"product {product_id} has {product['reserved']} reserved unit(s)",
                    product_id=product_id,
                    reserved=product["reserved"],
                )

            del self._products[product_id]
            self._reviews = {
                rid: r for rid, r in self._reviews.items() if r["product_id"] != product_id
            }

    def list_products(
        self,
        *,
        q=None,
        category_id=None,
        status=None,
        tag=None,
        min_price=None,
        max_price=None,
        in_stock=None,
        sort="created_at",
        order="asc",
        limit=20,
        offset=0,
    ):
        """Filter, sort and slice. Returns (items, total_before_slicing)."""
        with self._lock:
            rows = [self._product_view(p) for p in self._products.values()]

        if q:
            needle = q.strip().lower()
            rows = [
                r for r in rows
                if needle in r["name"].lower()
                or needle in r["sku"].lower()
                or needle in (r["description"] or "").lower()
            ]
        if category_id is not None:
            rows = [r for r in rows if r["category_id"] == category_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if tag:
            needle = tag.strip().lower()
            rows = [r for r in rows if needle in r["tags"]]
        if min_price is not None:
            rows = [r for r in rows if r["price"] >= min_price]
        if max_price is not None:
            rows = [r for r in rows if r["price"] <= max_price]
        if in_stock is not None:
            rows = [r for r in rows if (r["available"] > 0) is in_stock]

        # `rating` is None for unreviewed products; sort those last either way.
        def key(row):
            value = row[sort]
            return (value is None, value if value is not None else 0)

        rows.sort(key=key, reverse=(order == "desc"))

        total = len(rows)
        return rows[offset:offset + limit], total

    def _require_product(self, product_id):
        product = self._products.get(product_id)
        if product is None:
            raise NotFoundError("product", product_id)
        return product

    def _assert_sku_free(self, sku, excluding=None):
        for product in self._products.values():
            if product["sku"] == sku and product["id"] != excluding:
                raise ConflictError(f"sku {sku!r} is already taken", sku=sku)

    def _product_view(self, product):
        reviews = [r for r in self._reviews.values() if r["product_id"] == product["id"]]
        rating = round(sum(r["rating"] for r in reviews) / len(reviews), 2) if reviews else None

        return {
            **product,
            "available": product["stock"] - product["reserved"],
            "rating": rating,
            "review_count": len(reviews),
        }

    # -- inventory ---------------------------------------------------------

    def inventory(self, product_id):
        with self._lock:
            product = self._require_product(product_id)
            available = product["stock"] - product["reserved"]
            return {
                "product_id": product["id"],
                "sku": product["sku"],
                "stock": product["stock"],
                "reserved": product["reserved"],
                "available": available,
                "low_stock_threshold": product["low_stock_threshold"],
                "is_low": available <= product["low_stock_threshold"],
            }

    def adjust_stock(self, product_id, delta, reason, note=None):
        with self._lock:
            product = self._require_product(product_id)
            new_stock = product["stock"] + delta

            if new_stock < 0:
                raise InsufficientStockError(product_id, abs(delta), product["stock"])
            if new_stock < product["reserved"]:
                raise ConflictError(
                    f"cannot drop stock below the {product['reserved']} reserved unit(s)",
                    product_id=product_id,
                    reserved=product["reserved"],
                    requested_stock=new_stock,
                )

            product["stock"] = new_stock
            product["updated_at"] = _now()
            self._record_movement(product, delta, reason, note)
            return self.inventory(product_id)

    def reserve_stock(self, product_id, quantity):
        with self._lock:
            product = self._require_product(product_id)
            available = product["stock"] - product["reserved"]

            if quantity > available:
                raise InsufficientStockError(product_id, quantity, available)

            product["reserved"] += quantity
            product["updated_at"] = _now()
            return self.inventory(product_id)

    def release_stock(self, product_id, quantity):
        with self._lock:
            product = self._require_product(product_id)

            if quantity > product["reserved"]:
                raise ConflictError(
                    f"only {product['reserved']} unit(s) are reserved",
                    product_id=product_id,
                    requested=quantity,
                    reserved=product["reserved"],
                )

            product["reserved"] -= quantity
            product["updated_at"] = _now()
            return self.inventory(product_id)

    def list_movements(self, product_id, limit=50):
        with self._lock:
            self._require_product(product_id)
            rows = [m for m in self._movements.values() if m["product_id"] == product_id]
            rows.sort(key=lambda m: m["id"], reverse=True)
            return rows[:limit]

    def low_stock(self, threshold=None):
        with self._lock:
            out = []
            for product in self._products.values():
                state = self.inventory(product["id"])
                limit = threshold if threshold is not None else state["low_stock_threshold"]
                if state["available"] <= limit:
                    out.append(state)
            return sorted(out, key=lambda s: s["available"])

    def _record_movement(self, product, delta, reason, note):
        movement = {
            "id": next(self._movement_ids),
            "product_id": product["id"],
            "delta": delta,
            "reason": StockMovementReason(reason),
            "note": note,
            "stock_after": product["stock"],
            "created_at": _now(),
        }
        self._movements[movement["id"]] = movement
        return movement

    # -- reviews -----------------------------------------------------------

    def add_review(self, product_id, *, author, rating, comment=None):
        with self._lock:
            self._require_product(product_id)

            review = {
                "id": next(self._review_ids),
                "product_id": product_id,
                "author": author,
                "rating": rating,
                "comment": comment,
                "created_at": _now(),
            }
            self._reviews[review["id"]] = review
            return review

    def list_reviews(self, product_id, *, limit=20, offset=0):
        with self._lock:
            self._require_product(product_id)
            rows = [r for r in self._reviews.values() if r["product_id"] == product_id]

        rows.sort(key=lambda r: r["id"], reverse=True)
        return rows[offset:offset + limit], len(rows)

    def delete_review(self, product_id, review_id):
        with self._lock:
            self._require_product(product_id)
            review = self._reviews.get(review_id)

            if review is None or review["product_id"] != product_id:
                raise NotFoundError("review", review_id)

            del self._reviews[review_id]

    # -- orders ------------------------------------------------------------

    def create_order(self, *, customer, lines):
        """Reserve every line first; if any line fails, nothing is reserved."""
        with self._lock:
            merged = {}
            for line in lines:
                merged[line["product_id"]] = merged.get(line["product_id"], 0) + line["quantity"]

            # Check the whole basket before mutating, so a failure leaves no
            # half-reserved products behind.
            for product_id, quantity in merged.items():
                product = self._require_product(product_id)
                available = product["stock"] - product["reserved"]
                if quantity > available:
                    raise InsufficientStockError(product_id, quantity, available)

            currencies = {self._products[pid]["currency"] for pid in merged}
            if len(currencies) > 1:
                raise ConflictError(
                    "an order cannot mix currencies", currencies=sorted(currencies)
                )

            order_lines = []
            total = Decimal("0.00")
            for product_id, quantity in merged.items():
                product = self._products[product_id]
                product["reserved"] += quantity

                line_total = product["price"] * quantity
                total += line_total
                order_lines.append({
                    "product_id": product_id,
                    "sku": product["sku"],
                    "name": product["name"],
                    "quantity": quantity,
                    "unit_price": product["price"],
                    "line_total": line_total,
                })

            now = _now()
            order = {
                "id": next(self._order_ids),
                "customer": customer,
                "status": OrderStatus.PENDING,
                "lines": order_lines,
                "total": total,
                "currency": currencies.pop(),
                "created_at": now,
                "updated_at": now,
            }
            self._orders[order["id"]] = order
            return order

    def get_order(self, order_id):
        with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                raise NotFoundError("order", order_id)
            return order

    def list_orders(self, *, status=None, customer=None, limit=20, offset=0):
        with self._lock:
            rows = list(self._orders.values())

        if status is not None:
            rows = [o for o in rows if o["status"] == status]
        if customer:
            needle = customer.strip().lower()
            rows = [o for o in rows if needle in o["customer"].lower()]

        rows.sort(key=lambda o: o["id"], reverse=True)
        return rows[offset:offset + limit], len(rows)

    # Which status may follow which. Anything not listed is rejected.
    _ORDER_TRANSITIONS = {
        OrderStatus.PENDING: {OrderStatus.PAID, OrderStatus.CANCELLED},
        OrderStatus.PAID: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
        OrderStatus.SHIPPED: set(),
        OrderStatus.CANCELLED: set(),
    }

    def set_order_status(self, order_id, new_status):
        with self._lock:
            order = self.get_order(order_id)
            current = order["status"]

            if new_status not in self._ORDER_TRANSITIONS[current]:
                raise ConflictError(
                    f"cannot move order from {current.value} to {new_status.value}",
                    order_id=order_id,
                    current_status=current.value,
                    requested_status=new_status.value,
                    allowed=sorted(s.value for s in self._ORDER_TRANSITIONS[current]),
                )

            if new_status is OrderStatus.PAID:
                # Reserved units become sold: drop both stock and reservation.
                for line in order["lines"]:
                    product = self._products[line["product_id"]]
                    product["reserved"] -= line["quantity"]
                    product["stock"] -= line["quantity"]
                    self._record_movement(
                        product, -line["quantity"], StockMovementReason.SALE,
                        f"order {order_id}",
                    )
            elif new_status is OrderStatus.CANCELLED and current is OrderStatus.PENDING:
                # Still only reserved -- hand the units back.
                for line in order["lines"]:
                    self._products[line["product_id"]]["reserved"] -= line["quantity"]
            elif new_status is OrderStatus.CANCELLED and current is OrderStatus.PAID:
                # Already sold -- treat the cancellation as a return.
                for line in order["lines"]:
                    product = self._products[line["product_id"]]
                    product["stock"] += line["quantity"]
                    self._record_movement(
                        product, line["quantity"], StockMovementReason.RETURN,
                        f"order {order_id} cancelled",
                    )

            order["status"] = new_status
            order["updated_at"] = _now()
            return order

    # -- stats -------------------------------------------------------------

    def overview(self):
        with self._lock:
            products = [self._product_view(p) for p in self._products.values()]
            ratings = [p["rating"] for p in products if p["rating"] is not None]

            by_category = []
            for category in self._categories.values():
                owned = [p for p in products if p["category_id"] == category["id"]]
                by_category.append({
                    "category_id": category["id"],
                    "name": category["name"],
                    "product_count": len(owned),
                    "total_stock": sum(p["stock"] for p in owned),
                    "inventory_value": sum(
                        (p["price"] * p["stock"] for p in owned), Decimal("0.00")
                    ),
                })

            return {
                "product_count": len(products),
                "active_product_count": sum(
                    1 for p in products if p["status"] is ProductStatus.ACTIVE
                ),
                "category_count": len(self._categories),
                "order_count": len(self._orders),
                "review_count": len(self._reviews),
                "total_stock": sum(p["stock"] for p in products),
                "inventory_value": sum(
                    (p["price"] * p["stock"] for p in products), Decimal("0.00")
                ),
                "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "by_category": sorted(by_category, key=lambda c: c["category_id"]),
            }


store = Store()
