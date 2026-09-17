"""Tests for product-service.

These are the contract: if a change breaks one of these, CI turns red
and the pull request cannot be merged.
"""


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

def test_health_returns_healthy(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "product-service",
    }


def test_ready_reports_the_store_is_up(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"store": "up"}


def test_version_exposes_build_metadata(client):
    body = client.get("/version").json()

    assert body["service"] == "product-service"
    assert "version" in body
    assert body["uptime_seconds"] >= 0


def test_every_response_carries_a_request_id(client):
    response = client.get("/health")

    assert response.headers["X-Request-ID"]
    assert float(response.headers["X-Response-Time-ms"]) >= 0


def test_caller_supplied_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"


# ---------------------------------------------------------------------------
# Products: read and search
# ---------------------------------------------------------------------------

def test_products_returns_the_seeded_catalogue(client):
    response = client.get("/products")

    assert response.status_code == 200

    body = response.json()
    assert body["page"] == {"total": 2, "limit": 20, "offset": 0, "has_more": False}
    assert [item["name"] for item in body["items"]] == ["Laptop", "Keyboard"]


def test_get_product_by_id(client):
    response = client.get("/products/1")

    assert response.status_code == 200

    body = response.json()
    assert body["id"] == 1
    assert body["sku"] == "LAP-001"
    assert body["available"] == body["stock"] - body["reserved"]


def test_get_product_rejects_non_integer_id(client):
    """FastAPI validates the path type for us -- this test locks that in."""
    response = client.get("/products/not-a-number")

    assert response.status_code == 422


def test_unknown_product_returns_a_structured_404(client):
    response = client.get("/products/999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"]["id"] == 999


def test_search_matches_name_sku_and_description(client):
    assert client.get("/products?q=lap").json()["page"]["total"] == 1
    assert client.get("/products?q=KEY-001").json()["page"]["total"] == 1
    assert client.get("/products?q=mechanical").json()["page"]["total"] == 1
    assert client.get("/products?q=nothing-matches").json()["page"]["total"] == 0


def test_price_filters_narrow_the_result(client):
    body = client.get("/products?min_price=100").json()

    assert [item["sku"] for item in body["items"]] == ["LAP-001"]


def test_inverted_price_range_is_rejected(client):
    response = client.get("/products?min_price=500&max_price=100")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_sorting_by_price_descending(client):
    body = client.get("/products?sort=price&order=desc").json()

    prices = [float(item["price"]) for item in body["items"]]
    assert prices == sorted(prices, reverse=True)


def test_pagination_reports_has_more(client):
    body = client.get("/products?limit=1&offset=0").json()

    assert len(body["items"]) == 1
    assert body["page"]["has_more"] is True

    body = client.get("/products?limit=1&offset=1").json()
    assert body["page"]["has_more"] is False


def test_tag_filter_is_case_insensitive(client, new_product):
    new_product(tags=["Portable", "4K"])

    assert client.get("/products?tag=4k").json()["page"]["total"] == 1


def test_limit_above_the_cap_is_rejected(client):
    assert client.get("/products?limit=500").status_code == 422


# ---------------------------------------------------------------------------
# Products: write
# ---------------------------------------------------------------------------

def test_create_product_returns_201_and_location(client, new_product):
    product = new_product()

    assert product["id"] == 3
    assert product["stock"] == 10
    assert product["available"] == 10
    assert product["rating"] is None
    assert client.get(f"/products/{product['id']}").status_code == 200


def test_create_product_rejects_a_duplicate_sku(client, new_product):
    new_product(sku="DUP-001")
    response = client.post("/products", json={
        "name": "Clone", "sku": "DUP-001", "price": "10.00",
        "category_id": 1, "status": "active",
    })

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_create_product_rejects_an_unknown_category(client):
    response = client.post("/products", json={
        "name": "Orphan", "sku": "ORP-001", "price": "10.00", "category_id": 99,
    })

    assert response.status_code == 404
    assert response.json()["error"]["details"]["resource"] == "category"


def test_create_product_rejects_a_negative_price(client):
    response = client.post("/products", json={
        "name": "Free", "sku": "FRE-001", "price": "-1.00", "category_id": 1,
    })

    assert response.status_code == 422


def test_create_product_rejects_unknown_fields(client):
    response = client.post("/products", json={
        "name": "Sneaky", "sku": "SNK-001", "price": "1.00",
        "category_id": 1, "discount": 90,
    })

    assert response.status_code == 422


def test_tags_are_normalised_and_deduplicated(client, new_product):
    product = new_product(tags=["  Work ", "work", "PORTABLE"])

    assert product["tags"] == ["work", "portable"]


def test_patch_touches_only_the_fields_sent(client, new_product):
    product = new_product()
    response = client.patch(f"/products/{product['id']}", json={"price": "199.99"})

    assert response.status_code == 200

    body = response.json()
    assert body["price"] == "199.99"
    assert body["name"] == product["name"]
    assert body["updated_at"] >= product["updated_at"]


def test_put_replaces_the_whole_product(client, new_product):
    product = new_product()
    response = client.put(f"/products/{product['id']}", json={
        "name": "Replaced", "sku": "REP-001", "price": "5.00",
        "currency": "EUR", "category_id": 2, "tags": [], "status": "discontinued",
    })

    assert response.status_code == 200

    body = response.json()
    assert body["name"] == "Replaced"
    assert body["description"] is None
    assert body["stock"] == product["stock"]  # stock is inventory's job, not PUT's


def test_delete_product_removes_it(client, new_product):
    product = new_product()

    assert client.delete(f"/products/{product['id']}").json() == {
        "deleted": True, "id": product["id"],
    }
    assert client.get(f"/products/{product['id']}").status_code == 404


def test_delete_is_blocked_while_stock_is_reserved(client, new_product):
    product = new_product()
    client.post(f"/products/{product['id']}/inventory/reserve", json={"quantity": 2})

    response = client.delete(f"/products/{product['id']}")

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reserved"] == 2


def test_bulk_create_reports_per_item_failures(client):
    response = client.post("/products/bulk", json={"products": [
        {"name": "Good", "sku": "BLK-001", "price": "1.00", "category_id": 1},
        {"name": "Bad category", "sku": "BLK-002", "price": "1.00", "category_id": 99},
        {"name": "Duplicate", "sku": "LAP-001", "price": "1.00", "category_id": 1},
    ]})

    assert response.status_code == 207

    body = response.json()
    assert [p["sku"] for p in body["created"]] == ["BLK-001"]
    assert [f["code"] for f in body["failed"]] == ["not_found", "conflict"]
    assert body["failed"][0]["index"] == 1


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def test_categories_carry_their_product_count(client):
    body = client.get("/categories").json()

    assert {c["slug"]: c["product_count"] for c in body} == {
        "electronics": 1, "accessories": 1,
    }


def test_create_category_rejects_a_duplicate_slug(client):
    response = client.post("/categories", json={"name": "Again", "slug": "electronics"})

    assert response.status_code == 409


def test_create_category_rejects_a_malformed_slug(client):
    response = client.post("/categories", json={"name": "Bad", "slug": "Not A Slug"})

    assert response.status_code == 422


def test_delete_category_is_blocked_while_products_reference_it(client):
    response = client.delete("/categories/1")

    assert response.status_code == 409
    assert response.json()["error"]["details"]["product_ids"] == [1]


def test_delete_category_succeeds_once_it_is_empty(client):
    created = client.post("/categories", json={"name": "Empty", "slug": "empty"}).json()

    assert client.delete(f"/categories/{created['id']}").status_code == 200
    assert client.get(f"/categories/{created['id']}").status_code == 404


def test_category_products_endpoint_is_scoped(client):
    body = client.get("/categories/2/products").json()

    assert [item["sku"] for item in body["items"]] == ["KEY-001"]


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def test_inventory_reports_availability_and_low_stock(client):
    body = client.get("/products/2/inventory").json()

    assert body["stock"] == 3
    assert body["available"] == 3
    assert body["is_low"] is True


def test_adjust_adds_stock_and_writes_a_movement(client):
    response = client.post("/products/2/inventory/adjust", json={
        "delta": 7, "reason": "restock", "note": "pallet arrived",
    })

    assert response.status_code == 200
    assert response.json()["stock"] == 10

    movements = client.get("/products/2/inventory/movements").json()
    assert movements[0]["delta"] == 7
    assert movements[0]["stock_after"] == 10
    assert movements[0]["reason"] == "restock"


def test_adjust_cannot_push_stock_negative(client):
    response = client.post("/products/2/inventory/adjust", json={"delta": -99})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_stock"


def test_adjust_rejects_a_zero_delta(client):
    assert client.post("/products/1/inventory/adjust", json={"delta": 0}).status_code == 422


def test_reserve_then_release_round_trips(client):
    reserved = client.post("/products/1/inventory/reserve", json={"quantity": 4}).json()

    assert reserved["reserved"] == 4
    assert reserved["available"] == 8

    released = client.post("/products/1/inventory/release", json={"quantity": 4}).json()

    assert released["reserved"] == 0
    assert released["available"] == 12


def test_reserve_beyond_availability_is_rejected(client):
    response = client.post("/products/2/inventory/reserve", json={"quantity": 99})

    assert response.status_code == 409

    details = response.json()["error"]["details"]
    assert details["requested"] == 99
    assert details["available"] == 3


def test_releasing_more_than_is_reserved_is_rejected(client):
    assert client.post(
        "/products/1/inventory/release", json={"quantity": 1}
    ).status_code == 409


def test_stock_cannot_drop_below_what_is_reserved(client):
    client.post("/products/1/inventory/reserve", json={"quantity": 10})
    response = client.post("/products/1/inventory/adjust", json={"delta": -5})

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reserved"] == 10


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

def test_reviews_drive_the_product_rating(client):
    client.post("/products/1/reviews", json={"author": "ana", "rating": 5})
    client.post("/products/1/reviews", json={"author": "bo", "rating": 4, "comment": "good"})

    product = client.get("/products/1").json()

    assert product["review_count"] == 2
    assert product["rating"] == 4.5


def test_reviews_are_listed_newest_first(client):
    client.post("/products/1/reviews", json={"author": "first", "rating": 3})
    client.post("/products/1/reviews", json={"author": "second", "rating": 3})

    body = client.get("/products/1/reviews").json()

    assert [r["author"] for r in body["items"]] == ["second", "first"]
    assert body["page"]["total"] == 2


def test_review_rating_must_be_between_one_and_five(client):
    assert client.post(
        "/products/1/reviews", json={"author": "ana", "rating": 6}
    ).status_code == 422


def test_deleting_a_review_updates_the_rating(client):
    created = client.post("/products/1/reviews", json={"author": "ana", "rating": 1}).json()

    assert client.delete(f"/products/1/reviews/{created['id']}").status_code == 200
    assert client.get("/products/1").json()["rating"] is None


def test_a_review_cannot_be_deleted_through_another_product(client):
    created = client.post("/products/1/reviews", json={"author": "ana", "rating": 5}).json()

    assert client.delete(f"/products/2/reviews/{created['id']}").status_code == 404


def test_deleting_a_product_takes_its_reviews_with_it(client, new_product):
    product = new_product()
    client.post(f"/products/{product['id']}/reviews", json={"author": "ana", "rating": 5})
    client.delete(f"/products/{product['id']}")

    assert client.get(f"/products/{product['id']}/reviews").status_code == 404


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def test_creating_an_order_reserves_stock_and_totals_the_lines(client):
    response = client.post("/orders", json={
        "customer": "acme",
        "lines": [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}],
    })

    assert response.status_code == 201

    order = response.json()
    assert order["status"] == "pending"
    assert order["total"] == "2687.99"  # 2 x 1299.00 + 89.99
    assert client.get("/products/1/inventory").json()["reserved"] == 2


def test_repeated_lines_for_one_product_are_merged(client):
    order = client.post("/orders", json={
        "customer": "acme",
        "lines": [{"product_id": 1, "quantity": 2}, {"product_id": 1, "quantity": 3}],
    }).json()

    assert len(order["lines"]) == 1
    assert order["lines"][0]["quantity"] == 5


def test_an_unfillable_order_reserves_nothing(client):
    response = client.post("/orders", json={
        "customer": "acme",
        "lines": [{"product_id": 1, "quantity": 1}, {"product_id": 2, "quantity": 99}],
    })

    assert response.status_code == 409
    assert client.get("/products/1/inventory").json()["reserved"] == 0


def test_paying_converts_the_reservation_into_a_sale(client):
    order = client.post("/orders", json={
        "customer": "acme", "lines": [{"product_id": 1, "quantity": 2}],
    }).json()

    paid = client.post(f"/orders/{order['id']}/pay").json()
    assert paid["status"] == "paid"

    inventory = client.get("/products/1/inventory").json()
    assert inventory["stock"] == 10
    assert inventory["reserved"] == 0

    movements = client.get("/products/1/inventory/movements").json()
    assert movements[0]["reason"] == "sale"
    assert movements[0]["delta"] == -2


def test_cancelling_a_pending_order_returns_the_reservation(client):
    order = client.post("/orders", json={
        "customer": "acme", "lines": [{"product_id": 1, "quantity": 2}],
    }).json()

    assert client.post(f"/orders/{order['id']}/cancel").json()["status"] == "cancelled"

    inventory = client.get("/products/1/inventory").json()
    assert inventory["stock"] == 12
    assert inventory["reserved"] == 0


def test_cancelling_a_paid_order_restocks_it_as_a_return(client):
    order = client.post("/orders", json={
        "customer": "acme", "lines": [{"product_id": 1, "quantity": 2}],
    }).json()
    client.post(f"/orders/{order['id']}/pay")
    client.post(f"/orders/{order['id']}/cancel")

    assert client.get("/products/1/inventory").json()["stock"] == 12
    assert client.get("/products/1/inventory/movements").json()[0]["reason"] == "return"


def test_an_illegal_status_transition_is_rejected(client):
    order = client.post("/orders", json={
        "customer": "acme", "lines": [{"product_id": 1, "quantity": 1}],
    }).json()
    client.post(f"/orders/{order['id']}/cancel")

    response = client.post(f"/orders/{order['id']}/status", json={"status": "paid"})

    assert response.status_code == 409

    details = response.json()["error"]["details"]
    assert details["current_status"] == "cancelled"
    assert details["allowed"] == []


def test_orders_can_be_filtered_by_status_and_customer(client):
    client.post("/orders", json={
        "customer": "acme", "lines": [{"product_id": 1, "quantity": 1}],
    })
    second = client.post("/orders", json={
        "customer": "globex", "lines": [{"product_id": 1, "quantity": 1}],
    }).json()
    client.post(f"/orders/{second['id']}/pay")

    assert client.get("/orders?status=paid").json()["page"]["total"] == 1
    assert client.get("/orders?customer=acme").json()["page"]["total"] == 1
    assert client.get("/orders").json()["page"]["total"] == 2


def test_an_order_needs_at_least_one_line(client):
    assert client.post("/orders", json={"customer": "acme", "lines": []}).status_code == 422


def test_an_order_cannot_mix_currencies(client, new_product):
    new_product(sku="EUR-001", currency="EUR")

    response = client.post("/orders", json={
        "customer": "acme",
        "lines": [{"product_id": 1, "quantity": 1}, {"product_id": 3, "quantity": 1}],
    })

    assert response.status_code == 409
    assert response.json()["error"]["details"]["currencies"] == ["EUR", "USD"]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def test_overview_aggregates_the_catalogue(client):
    client.post("/products/1/reviews", json={"author": "ana", "rating": 4})

    body = client.get("/stats/overview").json()

    assert body["product_count"] == 2
    assert body["active_product_count"] == 2
    assert body["total_stock"] == 15
    assert body["inventory_value"] == "15857.97"  # 12 x 1299.00 + 3 x 89.99
    assert body["average_rating"] == 4.0
    assert [c["name"] for c in body["by_category"]] == ["Electronics", "Accessories"]


def test_low_stock_uses_each_products_threshold(client):
    body = client.get("/stats/low-stock").json()

    assert [state["sku"] for state in body] == ["KEY-001"]


def test_low_stock_threshold_can_be_overridden(client):
    body = client.get("/stats/low-stock?threshold=20").json()

    assert {state["sku"] for state in body} == {"LAP-001", "KEY-001"}
