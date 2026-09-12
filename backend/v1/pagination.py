"""Pagination query params + envelope constructors for v1 list endpoints."""

from fastapi import Query


class PageParams:
    """Shared ?page=&page_size= dependency (1-indexed page)."""

    def __init__(
        self,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
    ):
        self.page = page
        self.page_size = page_size


def paginate(items: list, page: int, page_size: int) -> tuple[list, dict]:
    total = len(items)
    start = (page - 1) * page_size
    return items[start:start + page_size], {
        "page": page,
        "page_size": page_size,
        "total": total,
    }
