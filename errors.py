"""Domain errors and the HTTP shape they turn into.

Routers raise these; a single exception handler in app.py renders them, so
no endpoint has to build an error body by hand.
"""


class ServiceError(Exception):
    """Base class for every error this service converts into a response."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message, **details):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self):
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class NotFoundError(ServiceError):
    status_code = 404
    code = "not_found"

    def __init__(self, resource, resource_id):
        super().__init__(
            f"{resource} {resource_id!r} does not exist",
            resource=resource,
            id=resource_id,
        )


class ConflictError(ServiceError):
    """The request is well formed but fights with current state."""

    status_code = 409
    code = "conflict"


class InsufficientStockError(ConflictError):
    code = "insufficient_stock"

    def __init__(self, product_id, requested, available):
        super().__init__(
            f"product {product_id} has {available} unit(s) available, {requested} requested",
            product_id=product_id,
            requested=requested,
            available=available,
        )


class ValidationError(ServiceError):
    status_code = 422
    code = "validation_error"
