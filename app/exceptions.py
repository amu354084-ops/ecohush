from __future__ import annotations


class APIException(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class NotFoundError(APIException):
    def __init__(self, detail: str = "Not found") -> None:
        super().__init__(detail, status_code=404)
