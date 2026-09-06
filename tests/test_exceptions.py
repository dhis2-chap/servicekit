"""Tests for custom exceptions with RFC 9457 Problem Details support."""

import pytest

from servicekit.exceptions import (
    BadRequestError,
    ConflictError,
    ErrorType,
    ForbiddenError,
    InvalidULIDError,
    NotFoundError,
    ServicekitException,
    UnauthorizedError,
    ValidationError,
    classify_integrity_error,
)


def test_chapkit_exception_with_defaults() -> None:
    """Test ServicekitException with default values."""
    exc = ServicekitException("Something went wrong")

    assert str(exc) == "Something went wrong"
    assert exc.detail == "Something went wrong"
    assert exc.type_uri == ErrorType.INTERNAL_ERROR
    assert exc.title == "Internal Server Error"
    assert exc.status == 500
    assert exc.instance is None
    assert exc.extensions == {}


def test_chapkit_exception_with_custom_values() -> None:
    """Test ServicekitException with custom values."""
    exc = ServicekitException(
        "Custom error",
        type_uri="urn:custom:error",
        title="Custom Error",
        status=418,
        instance="/api/v1/teapot",
        extra_field="extra_value",
    )

    assert exc.detail == "Custom error"
    assert exc.type_uri == "urn:custom:error"
    assert exc.title == "Custom Error"
    assert exc.status == 418
    assert exc.instance == "/api/v1/teapot"
    assert exc.extensions == {"extra_field": "extra_value"}


def test_not_found_error() -> None:
    """Test NotFoundError sets correct RFC 9457 fields."""
    exc = NotFoundError("Resource not found", instance="/api/v1/items/123")

    assert str(exc) == "Resource not found"
    assert exc.detail == "Resource not found"
    assert exc.type_uri == ErrorType.NOT_FOUND
    assert exc.title == "Resource Not Found"
    assert exc.status == 404
    assert exc.instance == "/api/v1/items/123"


def test_validation_error() -> None:
    """Test ValidationError sets correct RFC 9457 fields."""
    exc = ValidationError("Invalid input", instance="/api/v1/users", field="email")

    assert str(exc) == "Invalid input"
    assert exc.detail == "Invalid input"
    assert exc.type_uri == ErrorType.VALIDATION_FAILED
    assert exc.title == "Validation Failed"
    assert exc.status == 400
    assert exc.instance == "/api/v1/users"
    assert exc.extensions == {"field": "email"}


def test_conflict_error() -> None:
    """Test ConflictError sets correct RFC 9457 fields."""
    exc = ConflictError("Resource already exists", instance="/api/v1/configs/prod")

    assert str(exc) == "Resource already exists"
    assert exc.detail == "Resource already exists"
    assert exc.type_uri == ErrorType.CONFLICT
    assert exc.title == "Resource Conflict"
    assert exc.status == 409
    assert exc.instance == "/api/v1/configs/prod"


def test_invalid_ulid_error() -> None:
    """Test InvalidULIDError sets correct RFC 9457 fields."""
    exc = InvalidULIDError("Malformed ULID", instance="/api/v1/items/invalid", ulid="bad-ulid")

    assert str(exc) == "Malformed ULID"
    assert exc.detail == "Malformed ULID"
    assert exc.type_uri == ErrorType.INVALID_ULID
    assert exc.title == "Invalid ULID Format"
    assert exc.status == 400
    assert exc.instance == "/api/v1/items/invalid"
    assert exc.extensions == {"ulid": "bad-ulid"}


def test_bad_request_error() -> None:
    """Test BadRequestError sets correct RFC 9457 fields."""
    exc = BadRequestError("Missing required parameter", instance="/api/v1/search")

    assert str(exc) == "Missing required parameter"
    assert exc.detail == "Missing required parameter"
    assert exc.type_uri == ErrorType.BAD_REQUEST
    assert exc.title == "Bad Request"
    assert exc.status == 400
    assert exc.instance == "/api/v1/search"


def test_unauthorized_error() -> None:
    """Test UnauthorizedError sets correct RFC 9457 fields."""
    exc = UnauthorizedError("Invalid credentials", instance="/api/v1/login")

    assert str(exc) == "Invalid credentials"
    assert exc.detail == "Invalid credentials"
    assert exc.type_uri == ErrorType.UNAUTHORIZED
    assert exc.title == "Unauthorized"
    assert exc.status == 401
    assert exc.instance == "/api/v1/login"


def test_forbidden_error() -> None:
    """Test ForbiddenError sets correct RFC 9457 fields."""
    exc = ForbiddenError("Access denied", instance="/api/v1/admin", required_role="admin")

    assert str(exc) == "Access denied"
    assert exc.detail == "Access denied"
    assert exc.type_uri == ErrorType.FORBIDDEN
    assert exc.title == "Forbidden"
    assert exc.status == 403
    assert exc.instance == "/api/v1/admin"
    assert exc.extensions == {"required_role": "admin"}


def test_error_type_constants() -> None:
    """Test ErrorType URN constants are correctly defined."""
    assert ErrorType.NOT_FOUND == "urn:servicekit:error:not-found"
    assert ErrorType.VALIDATION_FAILED == "urn:servicekit:error:validation-failed"
    assert ErrorType.CONFLICT == "urn:servicekit:error:conflict"
    assert ErrorType.INVALID_ULID == "urn:servicekit:error:invalid-ulid"
    assert ErrorType.INTERNAL_ERROR == "urn:servicekit:error:internal"
    assert ErrorType.UNAUTHORIZED == "urn:servicekit:error:unauthorized"
    assert ErrorType.FORBIDDEN == "urn:servicekit:error:forbidden"
    assert ErrorType.BAD_REQUEST == "urn:servicekit:error:bad-request"


def test_exceptions_are_raisable() -> None:
    """Test that exceptions can be raised and caught."""
    with pytest.raises(NotFoundError) as exc_info:
        raise NotFoundError("Test error")

    assert exc_info.value.status == 404
    assert str(exc_info.value) == "Test error"


def test_exception_without_instance() -> None:
    """Test exceptions work without instance parameter."""
    exc = ValidationError("Missing field")

    assert exc.instance is None
    assert exc.detail == "Missing field"


def test_exception_with_multiple_extensions() -> None:
    """Test exceptions can handle multiple extension fields."""
    exc = BadRequestError("Invalid query", field="name", reason="too_short", min_length=3)

    assert exc.extensions == {"field": "name", "reason": "too_short", "min_length": 3}


@pytest.mark.parametrize(
    ("driver_message", "expected"),
    [
        ("FOREIGN KEY constraint failed", "foreign_key"),
        ("UNIQUE constraint failed: t.id", "unique"),
        ("NOT NULL constraint failed: t.name", "not_null"),
        ("CHECK constraint failed: positive_amount", "check"),
        ("database is locked", None),
    ],
)
def test_classify_integrity_error(driver_message: str, expected: str | None) -> None:
    """Test that driver messages map to safe constraint classifications."""
    assert classify_integrity_error(Exception(driver_message)) == expected


def test_classify_integrity_error_prefers_driver_error() -> None:
    """Test that classification reads the driver error rather than the SQL statement."""

    class WrappedError(Exception):
        """Error carrying an orig attribute like SQLAlchemy's DBAPIError."""

        orig = Exception("FOREIGN KEY constraint failed")

    assert classify_integrity_error(WrappedError("INSERT INTO unique_names VALUES (?)")) == "foreign_key"
