"""Prometheus metrics for product-service.

Three kinds live here.

* **HTTP metrics** -- recorded by the middleware in `app.py` for every
  request, labelled with the *route template* (`/products/{product_id}`)
  rather than the raw path, so one product per id does not become one time
  series per id.
* **Business counters** -- bumped by `store.py` at the point the thing
  actually happens, so every caller is counted, not just the HTTP one.
* **Store gauges** -- current catalogue state. These are not kept in sync on
  write; a collector reads the store when Prometheus scrapes, which is the
  only way a gauge can survive a restart or a missed update.

Nothing here imports `store`, so the domain layer can import this module
without a cycle. The collector gets its store handed to it instead.
"""
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from logging_config import logger
from schemas import OrderStatus

# Prefixes every series, so `product_service_` selects the whole service in
# a query and nothing collides with another exporter on the same Prometheus.
NAMESPACE = "product_service"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

REQUESTS = Counter(
    "http_requests",
    "HTTP requests handled, by route template and outcome.",
    ["method", "path", "status"],
    namespace=NAMESPACE,
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Wall-clock time spent handling a request.",
    ["method", "path"],
    namespace=NAMESPACE,
    # Tuned for an in-memory service: most work lands under 25ms, and the
    # default buckets would put nearly every request in the first one.
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    # Method only, no path: the route template is not known until routing has
    # run, and the raw path would mint a series per product id.
    "Requests currently being handled.",
    ["method"],
    namespace=NAMESPACE,
)

DOMAIN_ERRORS = Counter(
    "domain_errors",
    "Requests rejected by a domain rule, by error code.",
    ["code"],
    namespace=NAMESPACE,
)


# ---------------------------------------------------------------------------
# Business events
# ---------------------------------------------------------------------------

ORDERS_PLACED = Counter(
    "orders_placed",
    "Orders placed.",
    ["currency"],
    namespace=NAMESPACE,
)

ORDER_VALUE = Counter(
    "order_value",
    "Cumulative value of orders placed, in the order's own currency.",
    ["currency"],
    namespace=NAMESPACE,
)

ORDER_TRANSITIONS = Counter(
    "order_transitions",
    "Accepted order status changes.",
    ["from_status", "to_status"],
    namespace=NAMESPACE,
)

STOCK_MOVEMENTS = Counter(
    "stock_movements",
    "Entries written to the stock movement ledger, by reason.",
    ["reason"],
    namespace=NAMESPACE,
)

STOCK_UNITS_MOVED = Counter(
    "stock_units_moved",
    "Units of stock moved, by reason and direction. Always a positive count; "
    "`direction` says which way they went.",
    ["reason", "direction"],
    namespace=NAMESPACE,
)

REVIEWS_ADDED = Counter(
    "reviews_added",
    "Reviews left by customers.",
    ["rating"],
    namespace=NAMESPACE,
)


# ---------------------------------------------------------------------------
# Store gauges
# ---------------------------------------------------------------------------

class StoreCollector(Collector):
    """Reads the catalogue when Prometheus scrapes.

    A gauge that is written on every mutation drifts the moment one code path
    forgets to update it, and resets to zero on restart. Reading the store at
    scrape time cannot drift: the number is the number.
    """

    def __init__(self, store):
        self._store = store

    def collect(self):
        try:
            yield from self._collect()
        except Exception:
            # A raising collector breaks the whole /metrics response, taking
            # the HTTP and business metrics down with it. One bad gauge is
            # not worth losing the rest.
            logger.exception("Store metrics collection failed")

    def _collect(self):
        overview = self._store.overview()

        yield self._gauge(
            "products", "Products in the catalogue.", overview["product_count"]
        )
        yield self._gauge(
            "products_active",
            "Products with status=active.",
            overview["active_product_count"],
        )
        yield self._gauge(
            "categories", "Categories defined.", overview["category_count"]
        )
        yield self._gauge("reviews", "Reviews stored.", overview["review_count"])
        yield self._gauge(
            "stock_units", "Units of stock on the shelf.", overview["total_stock"]
        )
        yield self._gauge(
            "inventory_value",
            "Price times stock, summed over every product.",
            float(overview["inventory_value"]),
        )

        # `average_rating` is None until somebody reviews something. Emitting
        # a 0 there would read as "everyone hates us" on a dashboard, so the
        # series simply does not exist yet.
        if overview["average_rating"] is not None:
            yield self._gauge(
                "average_rating",
                "Mean rating across all reviewed products.",
                float(overview["average_rating"]),
            )

        yield self._gauge(
            "low_stock_products",
            "Products at or below their own low-stock threshold.",
            len(self._store.low_stock()),
        )

        # Orders never leave the store, so a per-status gauge is the cheapest
        # way to see a pending backlog build up.
        orders = GaugeMetricFamily(
            f"{NAMESPACE}_orders",
            "Orders currently in each status.",
            labels=["status"],
        )
        for status in OrderStatus:
            _, total = self._store.list_orders(status=status, limit=1)
            orders.add_metric([status.value], total)
        yield orders

        products_by_category = GaugeMetricFamily(
            f"{NAMESPACE}_category_products",
            "Products in each category.",
            labels=["category"],
        )
        stock_by_category = GaugeMetricFamily(
            f"{NAMESPACE}_category_stock_units",
            "Units of stock in each category.",
            labels=["category"],
        )
        value_by_category = GaugeMetricFamily(
            f"{NAMESPACE}_category_inventory_value",
            "Inventory value in each category.",
            labels=["category"],
        )
        for row in overview["by_category"]:
            name = row["name"]
            products_by_category.add_metric([name], row["product_count"])
            stock_by_category.add_metric([name], row["total_stock"])
            value_by_category.add_metric([name], float(row["inventory_value"]))

        yield products_by_category
        yield stock_by_category
        yield value_by_category

    @staticmethod
    def _gauge(name, documentation, value):
        return GaugeMetricFamily(f"{NAMESPACE}_{name}", documentation, value=value)


def register_store_collector(store, registry=None):
    """Attach the store gauges to a registry. Idempotent per registry.

    The tests build the app more than once in a session, and registering the
    same collector twice raises, so an existing registration wins.
    """
    from prometheus_client import REGISTRY

    target = registry if registry is not None else REGISTRY

    for collector in list(target._collector_to_names):
        if isinstance(collector, StoreCollector):
            return collector

    collector = StoreCollector(store)
    target.register(collector)
    return collector


def record_request(method, path, status_code, duration_seconds):
    """One call per finished request, from the middleware."""
    REQUESTS.labels(method=method, path=path, status=str(status_code)).inc()
    REQUEST_DURATION.labels(method=method, path=path).observe(duration_seconds)


def record_stock_movement(reason, delta):
    """One call per ledger entry, from the store."""
    reason = str(reason)
    STOCK_MOVEMENTS.labels(reason=reason).inc()

    if delta:
        direction = "in" if delta > 0 else "out"
        STOCK_UNITS_MOVED.labels(reason=reason, direction=direction).inc(abs(delta))


__all__ = [
    "NAMESPACE",
    "CollectorRegistry",
    "DOMAIN_ERRORS",
    "ORDERS_PLACED",
    "ORDER_TRANSITIONS",
    "ORDER_VALUE",
    "REQUESTS",
    "REQUESTS_IN_PROGRESS",
    "REQUEST_DURATION",
    "REVIEWS_ADDED",
    "STOCK_MOVEMENTS",
    "STOCK_UNITS_MOVED",
    "StoreCollector",
    "record_request",
    "record_stock_movement",
    "register_store_collector",
]
