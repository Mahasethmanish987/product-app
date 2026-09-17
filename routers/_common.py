"""Parameter types shared by the routers.

Declaring them once as `Annotated` aliases keeps every endpoint's pagination
and path validation identical.
"""
from typing import Annotated

from fastapi import Path, Query

from schemas import Page

ResourceId = Annotated[int, Path(ge=1)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def page(items, total, limit, offset):
    """Build the pagination envelope every list endpoint returns."""
    return {
        "items": items,
        "page": Page(
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(items) < total,
        ),
    }
