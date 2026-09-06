"""Custom exceptions with RFC 9457 Problem Details support."""

from __future__ import annotations

from typing import Any


class ErrorType:
    """URN-based error type identifiers for RFC 9457 Problem Details."""

    NOT_FOUND = "urn:servicekit:error:not-found"
    VALIDATION_FAILED = "urn:servicekit:error:validation-failed"
    CONFLICT = "urn:servicekit:error:conflict"
    INVALID_ULID = "urn:servicekit:error:invalid-ulid"
    INTERNAL_ERROR = "urn:servicekit:error:internal"
    DATABASE_ERROR = "urn:servicekit:error:database"
    UNAUTHORIZED = "urn:servicekit:error:unauthorized"
    FORBIDDEN = "urn:servicekit:error:forbidden"
    BAD_REQUEST = "urn:servicekit:error:bad-request"


class ServicekitException(Exception):
    """Base exception for servicekit with RFC 9457 Problem Details support."""

    def __init__(
        self,
        detail: str,
        *,
        type_uri: str = ErrorType.INTERNAL_ERROR,
        title: str = "Internal Server Error",
        status: int = 500,
        instance: str | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(detail)
        self.type_uri = type_uri
        self.title = title
        self.status = status
        self.detail = detail
        self.instance = instance
        self.extensions = extensions


class NotFoundError(ServicekitException):
    """Resource not found exception (404)."""

    def __init__(self, detail: str, *, instance: str | None = None, **extensions: Any) -> None:
        super().__init__(
            detail,
            type_uri=ErrorType.NOT_FOUND,
            title="Resource Not Found",
            status=404,
            instance=instance,
            **extensions,
        )


class ValidationError(ServicekitException):
    """Validation failed exception (400)."""

    def __init__(self, detail: str, *, instance: str | None = None, **extensions: Any) -> None:
        super().__init__(
            detail,
            type_uri=ErrorType.VALIDATION_FAILED,
            title="Validation Failed",
            status=400,
            instance=instance,
            **extensions,
        )


class ConflictError(ServicekitException):
    """Resource conflict exception (409)."""

    def __init__(self, detail: str, *, instance: str | None = None, **extensions: Any) -> None:
        super().__init__(
            detail,
            type_uri=ErrorType.CONFLICT,
            title="Resource Conflict",
            status=409,
            instance=instance,
            **extensions,
        )


class InvalidULIDError(ServicekitException):
    """Invalid ULID format exception (400)."""

    def __init__(self, detail: str, *, instance: str | None = None, **extensions: Any) -> None:
        super().__init__(
            detail,
            type_uri=ErrorType.INVALID_ULID,
            title="Invalid ULID Format",
            status=400,
            instance=instance,
            **extensions,
        )


class BadRequestError(ServicekitException):
    """Bad request exception (400)."""

    def __init__(self, detail: str, *, instance: str | None = None, **extensions: Any) -> None:
        super().__init__(
            detail,
            type_uri=ErrorType.BAD_REQUEST,
            title="Bad Request",
            status=400,
            instance=instance,
            **extensions,
        )


class UnauthorizedError(ServicekitException):
    """Unauthorized exception (401)."""

    def __init__(self, detail: str, *, instance: str | None = None, **extensions: Any) -> None:
        super().__init__(
            detail,
            type_uri=ErrorType.UNAUTHORIZED,
            title="Unauthorized",
            status=401,
            instance=instance,
            **extensions,
        )


class ForbiddenError(ServicekitException):
    """Forbidden exception (403)."""

    def __init__(self, detail: str, *, instance: str | None = None, **extensions: Any) -> None:
        super().__init__(
            detail,
            type_uri=ErrorType.FORBIDDEN,
            title="Forbidden",
            status=403,
            instance=instance,
            **extensions,
        )
