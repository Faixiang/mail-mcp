# 核心数据对象。全部 dataclass，无行为，便于序列化与测试。
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Literal

TrustLevel = Literal["untrusted", "self"]
Decision = Literal["allow", "confirm", "deny"]
PolicyAction = Literal["auto_reply", "draft_for_review", "read_only", "drop"]


@dataclass
class Address:
    name: str = ""
    address: str = ""


@dataclass
class AuthResult:
    spf: str | None = None
    dkim: str | None = None
    dmarc: str | None = None

    @property
    def verified(self) -> bool:
        # 三项全 pass 才算已验证；缺头一律视为未验证
        return all(v == "pass" for v in (self.spf, self.dkim, self.dmarc))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verified"] = self.verified
        return d


@dataclass
class Attachment:
    attachment_id: str
    filename: str
    size: int
    mime: str
    sha256: str = ""


@dataclass
class Message:
    message_id: str
    thread_id: str
    account: str
    provider: str
    folder: str
    received_at: datetime
    sender: Address
    to: list[Address] = field(default_factory=list)
    cc: list[Address] = field(default_factory=list)
    subject: str = ""
    flags: list[str] = field(default_factory=list)
    auth: AuthResult = field(default_factory=AuthResult)
    trust: TrustLevel = "untrusted"
    tainted: bool = False
    taint_reasons: list[str] = field(default_factory=list)
    body_text: str = ""
    body_truncated: bool = False
    quoted_stripped: bool = False
    attachments: list[Attachment] = field(default_factory=list)
    headers_of_interest: dict[str, str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "account": self.account,
            "provider": self.provider,
            "folder": self.folder,
            "received_at": self.received_at.isoformat(),
            "from": asdict(self.sender),
            "to": [asdict(a) for a in self.to],
            "cc": [asdict(a) for a in self.cc],
            "subject": self.subject,
            "flags": list(self.flags),
            "auth": self.auth.to_dict(),
            "trust": self.trust,
            "tainted": self.tainted,
            "taint_reasons": list(self.taint_reasons),
            "body_text": self.body_text,
            "body_truncated": self.body_truncated,
            "quoted_stripped": self.quoted_stripped,
            "attachments": [asdict(a) for a in self.attachments],
            "headers_of_interest": dict(self.headers_of_interest),
        }


@dataclass
class PolicyDecision:
    decision: Decision
    action: PolicyAction
    matched_rule: str = "default"
    priority: int = 0
    evaluated: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    decision: Decision
    gate: str = "none"
    reasons: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
