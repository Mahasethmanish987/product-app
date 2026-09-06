"""Tests for product-service.

These are the contract: if a change breaks one of these, CI turns red
and the pull request cannot be merged.
"""
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health_returns_healthy():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "product-service",
    }


def test_products_returns_two_items():
    response = client.get("/products")

    assert response.status_code == 200

    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0] == {"id": 1, "name": "Laptop"}


def test_get_product_by_id():
    response = client.get("/products/42")

    assert response.status_code == 200
    assert response.json() == {"id": 42, "name": "Product 42"}


def test_get_product_rejects_non_integer_id():
    """FastAPI validates the path type for us -- this test locks that in."""
    response = client.get("/products/not-a-number")

    assert response.status_code == 422
