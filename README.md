# product-app

FastAPI product catalogue: categories, products, inventory with reservations,
reviews and orders. State lives in memory (`store.py`), so a restart reseeds
two categories and two products.

## Run

```bash
pip install -r requirements-dev.txt
uvicorn app:app --reload
pytest
ruff check .
```

Interactive docs: <http://localhost:8000/docs>

## Layout

| File | Role |
| --- | --- |
| `app.py` | App assembly: middleware, error handlers, router wiring |
| `schemas.py` | Pydantic request/response models and enums |
| `store.py` | In-memory data store; the only place that mutates state |
| `errors.py` | Domain errors and the HTTP status they map to |
| `logging_config.py` | JSON log formatter |
| `routers/` | One module per resource |

## Endpoints

### System

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Service index |
| GET | `/health` | Liveness probe |
| GET | `/ready` | Readiness probe |
| GET | `/version` | Version, commit, uptime |

### Categories

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/categories` | List categories with product counts |
| POST | `/categories` | Create a category |
| GET | `/categories/{id}` | Get one category |
| PATCH | `/categories/{id}` | Update name/description |
| DELETE | `/categories/{id}` | Delete — 409 while products reference it |
| GET | `/categories/{id}/products` | Products in that category |

### Products

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/products` | Search: `q`, `category_id`, `status`, `tag`, `min_price`, `max_price`, `in_stock`, `sort`, `order`, `limit`, `offset` |
| POST | `/products` | Create a product |
| POST | `/products/bulk` | Create up to 100, `207` with per-item failures |
| GET | `/products/{id}` | Get one product |
| PUT | `/products/{id}` | Replace a product |
| PATCH | `/products/{id}` | Partial update |
| DELETE | `/products/{id}` | Delete — 409 while stock is reserved |

### Inventory

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/products/{id}/inventory` | Stock, reserved, available, low-stock flag |
| POST | `/products/{id}/inventory/adjust` | Signed `delta` with a reason |
| POST | `/products/{id}/inventory/reserve` | Hold units |
| POST | `/products/{id}/inventory/release` | Give a hold back |
| GET | `/products/{id}/inventory/movements` | Audit trail, newest first |

### Reviews

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/products/{id}/reviews` | List reviews |
| POST | `/products/{id}/reviews` | Add a 1–5 star review |
| DELETE | `/products/{id}/reviews/{review_id}` | Delete a review |

### Orders

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/orders` | List, filter by `status` and `customer` |
| POST | `/orders` | Place an order, reserving stock atomically |
| GET | `/orders/{id}` | Get one order |
| POST | `/orders/{id}/status` | Move status through the allowed transitions |
| POST | `/orders/{id}/pay` | Shortcut for `status=paid` |
| POST | `/orders/{id}/cancel` | Shortcut for `status=cancelled` |

### Stats

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/stats/overview` | Counts, inventory value, average rating, per-category totals |
| GET | `/stats/low-stock` | Products at or below their threshold (`?threshold=` to override) |

## Behaviour worth knowing

- **Stock model.** `available = stock - reserved`. Creating an order reserves;
  paying turns the reservation into a sale and writes a `sale` movement;
  cancelling a pending order releases it, cancelling a paid one restocks as a
  `return`. Order status follows `pending → paid → shipped`, with `cancelled`
  reachable from `pending` and `paid`; anything else is a 409.
- **Atomic orders.** Every line is checked before anything is reserved, so a
  basket that cannot be filled leaves no partial reservations.
- **Uniform errors.** Every failure returns
  `{"error": {"code", "message", "details"}}`, including FastAPI's own 422s.
- **Request tracing.** Every response carries `X-Request-ID` (echoed if the
  caller sent one) and `X-Response-Time-ms`, and both appear in the JSON logs.

## Example

```bash
curl -X POST localhost:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"customer": "acme", "lines": [{"product_id": 1, "quantity": 2}]}'

curl -X POST localhost:8000/orders/1/pay
curl localhost:8000/stats/overview
```
