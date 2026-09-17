"""product-service entrypoint.

Wires the routers together and installs the cross-cutting pieces: request
ids, access logging, and the single place where errors become responses.
"""
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from errors import ServiceError
from logging_config import SERVICE_NAME, logger, safe_extra
from routers import categories, inventory, orders, products, reviews, stats, system

REQUEST_ID_HEADER = "X-Request-ID"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Service starting", extra={"routes": len(app.routes)})
    yield
    logger.info("Service stopping")


app = FastAPI(
    title="Product Service",
    version=system.VERSION,
    summary="Catalogue, inventory, reviews and orders.",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Give every request an id and log how it went."""
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
    request.state.request_id = request_id

    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers["X-Response-Time-ms"] = str(duration_ms)

    logger.info(
        "Request handled",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    """Every domain error renders through here, so the body shape is uniform."""
    logger.warning(
        "Request rejected",
        extra=safe_extra({
            "request_id": getattr(request.state, "request_id", None),
            "error_code": exc.code,
            "path": request.url.path,
            **exc.details,
        }),
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Match FastAPI's 422 to the same envelope the domain errors use.

    `ctx` can hold the original exception object, which json cannot encode,
    so each entry is reduced to the parts a client can act on.
    """
    errors = [
        {
            "location": list(error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "request body or parameters failed validation",
                "details": {"errors": errors},
            }
        },
    )


app.include_router(system.router)
app.include_router(categories.router)
app.include_router(products.router)
app.include_router(inventory.router)
app.include_router(reviews.router)
app.include_router(orders.router)
app.include_router(stats.router)


@app.get("/", tags=["system"], summary="Service index")
def index():
    return {
        "service": SERVICE_NAME,
        "version": system.VERSION,
        "docs": "/docs",
        "openapi": "/openapi.json",
    }
