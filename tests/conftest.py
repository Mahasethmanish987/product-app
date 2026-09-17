"""Shared fixtures.

The store lives in module state, so every test starts from a freshly seeded
copy -- otherwise test order would decide whether a test passes.
"""
import pytest
from fastapi.testclient import TestClient

from app import app
from store import store


@pytest.fixture(autouse=True)
def fresh_store():
    store.reset(seed=True)
    yield
    store.reset(seed=True)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def new_product(client):
    """Factory for a product with sane defaults; override any field."""
    def make(**overrides):
        body = {
            "name": "Monitor",
            "sku": "MON-001",
            "price": "249.50",
            "currency": "USD",
            "category_id": 1,
            "description": "27 inch panel",
            "tags": ["display"],
            "status": "active",
            "initial_stock": 10,
        }
        body.update(overrides)

        response = client.post("/products", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return make
