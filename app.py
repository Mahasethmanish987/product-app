import json
import logging
import sys

from fastapi import FastAPI


class JsonFormatter(logging.Formatter):

    def format(self, record):
        log = {
            "service": "product-service",
            "level": record.levelname,
            "message": record.getMessage(),
        }

        if hasattr(record, "product_id"):
            log["product_id"] = record.product_id

        return json.dumps(log)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("product-service")
logger.setLevel(logging.INFO)
logger.addHandler(handler)


app = FastAPI(title="Product Service")


@app.get("/health")
def health():

    logger.info("Health endpoint called")

    return {
        "status": "healthy",
        "service": "product-service"
    }


@app.get("/products")
def products():

    logger.info("Fetching all products")

    return [
        {"id": 1, "name": "Laptop"},
        {"id": 2, "name": "Keyboard"},
    ]


@app.get("/products/{product_id}")
def get_product(product_id: int):

    logger.info(
        "Fetching product",
        extra={
            "product_id": product_id
        }
    )

    return {
        "id": product_id,
        "name": f"Product {product_id}"
    }
