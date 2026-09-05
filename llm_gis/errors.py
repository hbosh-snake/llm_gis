from __future__ import annotations

INPUT_NOT_FOUND = "INPUT_NOT_FOUND"
CRS_MISSING = "CRS_MISSING"
CRS_SUSPICIOUS = "CRS_SUSPICIOUS"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
COMMAND_FAILED = "COMMAND_FAILED"
PATH_OUTSIDE_ROOT = "PATH_OUTSIDE_ROOT"
TABLE_NOT_FOUND = "TABLE_NOT_FOUND"
MISSING_ARGUMENT = "MISSING_ARGUMENT"
UNEXPECTED = "UNEXPECTED"


class GisError(Exception):
    """A failure a caller can act on: what failed, why, and what to do."""

    def __init__(
        self,
        code: str,
        message: str,
        suggested_action: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggested_action = suggested_action
        self.details = details or {}

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": "error",
            "code": self.code,
            "message": self.message,
            "suggested_action": self.suggested_action,
        }
        if self.details:
            payload["details"] = self.details
        return payload
