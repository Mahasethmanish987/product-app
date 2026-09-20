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
| `metrics.py` | Prometheus metric definitions and the store collector |
| `routers/` | One module per resource |

## Endpoints

### System

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Service index |
| GET | `/health` | Liveness probe |
| GET | `/ready` | Readiness probe |
| GET | `/version` | Version, commit, uptime |
| GET | `/metrics` | Prometheus scrape target (not in the OpenAPI schema) |

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
- **Metrics.** See below.

## Example

```bash
curl -X POST localhost:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"customer": "acme", "lines": [{"product_id": 1, "quantity": 2}]}'

curl -X POST localhost:8000/orders/1/pay
curl localhost:8000/stats/overview
```

## Metrics

`GET /metrics` serves the Prometheus registry on the same port as the API.
It is deliberately **not** on the Traefik route, so it stays inside the
cluster, and it is hidden from the OpenAPI schema.

Everything is prefixed `product_service_`, alongside the client library's free
`process_*` and `python_*` series.

### HTTP

| Metric | Type | Labels |
| --- | --- | --- |
| `http_requests_total` | counter | `method`, `path`, `status` |
| `http_request_duration_seconds` | histogram | `method`, `path` |
| `http_requests_in_progress` | gauge | `method` |
| `domain_errors_total` | counter | `code` |

`path` is the **route template** (`/products/{product_id}`), never the raw
path — otherwise one product per id becomes one time series per id. Requests
that match no route collapse into `path="__unmatched__"`, so a port scanner
cannot mint series at will. Scrapes of `/metrics` are not counted as traffic.

### Business events

Counted inside `store.py`, at the point the thing actually happens, so every
caller is counted rather than just the HTTP one — a sale booked by paying an
order shows up the same as a manual stock adjustment.

| Metric | Type | Labels |
| --- | --- | --- |
| `orders_placed_total` | counter | `currency` |
| `order_value_total` | counter | `currency` |
| `order_transitions_total` | counter | `from_status`, `to_status` |
| `stock_movements_total` | counter | `reason` |
| `stock_units_moved_total` | counter | `reason`, `direction` |
| `reviews_added_total` | counter | `rating` |

### Catalogue state

Gauges read from the store **when Prometheus scrapes**, not written on each
mutation: a gauge kept in sync by hand drifts the moment one code path forgets
to update it, and resets to zero on restart.

| Metric | Labels |
| --- | --- |
| `products`, `products_active`, `categories`, `reviews` | — |
| `stock_units`, `inventory_value`, `low_stock_products` | — |
| `average_rating` | — (absent until something is reviewed) |
| `orders` | `status` |
| `category_products`, `category_stock_units`, `category_inventory_value` | `category` |

`average_rating` has no series at all until the first review, because a `0`
there would read as "everyone hates us" on a dashboard.

If the store raises, the collector logs and yields nothing rather than
propagating: one bad gauge must not take the HTTP and business metrics with it.

### Adding a metric

Define it in `metrics.py`, then increment it at the domain choke point in
`store.py` (not in the router — routers are one caller among several):

```python
# metrics.py
REFUNDS = Counter("refunds", "Refunds issued.", ["reason"], namespace=NAMESPACE)

# store.py
REFUNDS.labels(reason=reason).inc()
```

For a new gauge over store state, add it to `StoreCollector._collect`.

### Scraping it

The cluster runs **kube-prometheus-stack** (Prometheus Operator), whose
Prometheus discovers targets through `ServiceMonitor` CRDs and ignores
`prometheus.io/scrape` annotations. The chart therefore ships a ServiceMonitor,
on by default, with annotations off.

The `release: monitoring` label on it is **mandatory**. The stack leaves
`serviceMonitorSelectorNilUsesHelmValues` at its default of `true` with a nil
`serviceMonitorSelector`, so the Operator matches only ServiceMonitors carrying
`release: <its helm release>`. Get that label wrong and Prometheus ignores this
target silently -- no error, and no down target to notice either.

Ordering: the monitoring stack must be installed first, or `helm install` here
fails with `no matches for kind "ServiceMonitor"` because the CRD does not
exist yet.

If the scraper is ever swapped for a plain non-operator Prometheus, flip it
round -- that one reads the annotations and has no CRD:

```sh
helm upgrade --install product-service ./deployments/charts/product-service \
  --set metrics.serviceMonitor.enabled=false \
  --set metrics.podAnnotations=true
```

Never enable both: the pod gets scraped twice and every counter reads double.

Check the target landed:

```sh
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
# http://localhost:9090 -> Status -> Target health -> look for product-service
```

### One worker, on purpose

`prometheus_client`'s default registry is per-process. The image runs a single
uvicorn worker, so a scrape sees the whole picture. Adding `--workers` means
adding [multiprocess mode](https://prometheus.github.io/client_python/multiprocess/)
at the same time, or each scrape lands on a random worker and the counters
appear to jump backwards.
