# 统一错误码。对外暴露的 code 稳定，message 不保证稳定。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

E_PROFILE_DENIED = "E_PROFILE_DENIED"
E_AUTH_MISSING = "E_AUTH_MISSING"
E_AUTH_EXPIRED = "E_AUTH_EXPIRED"
E_PROVIDER_UNSUPPORTED = "E_PROVIDER_UNSUPPORTED"
E_POLICY_DENIED = "E_POLICY_DENIED"
E_NEED_CONFIRM = "E_NEED_CONFIRM"
E_RATE_LIMITED = "E_RATE_LIMITED"
E_QUOTA_EXCEEDED = "E_QUOTA_EXCEEDED"
E_TAINT_WRITE_BLOCKED = "E_TAINT_WRITE_BLOCKED"
E_ATTACHMENT_REJECTED = "E_ATTACHMENT_REJECTED"
E_CURSOR_INVALID = "E_CURSOR_INVALID"
E_INVALID_ARGUMENT = "E_INVALID_ARGUMENT"
E_LOOP_DETECTED = "E_LOOP_DETECTED"

RETRYABLE = {
    E_NEED_CONFIRM,
    E_RATE_LIMITED,
    E_QUOTA_EXCEEDED,
    E_CURSOR_INVALID,
}


@dataclass
class MailMCPError(Exception):
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "detail": self.detail,
        }

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code}: {self.message}"
