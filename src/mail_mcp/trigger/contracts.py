# 事件契约。铁律：事件只描述"有一封信"，绝不携带正文。
# 一旦事件里出现正文，注入就会绕过 MCP 的消毒层直接进模型上下文——这是整个设计的第一性约束。
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1

# 任何情况下都不允许出现在事件里的字段名（子串匹配）
FORBIDDEN_FIELDS = ("body", "html", "content", "preview", "snippet", "raw", "token", "password")

# 事件里允许出现的字段，白名单而非黑名单
ALLOWED_FIELDS = (
    "event_id",
    "schema_version",
    "account",
    "provider",
    "folder",
    "uid",
    "uidvalidity",
    "internal_date",
    "sender",
    "subject_fingerprint",
    "size",
    "has_attachments",
    "auth_hint",
)


def make_event_id(account: str, folder: str, uidvalidity: str, uid: str) -> str:
    # 稳定的幂等键：同一封信在任何消费者上算出同一个 id
    raw = f"{account}|{folder}|{uidvalidity}|{uid}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def fingerprint(text: str) -> str:
    # 只有指纹，不存原文。用于同一主题串内去重，不可逆推内容
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class MailEvent:
    event_id: str
    account: str
    provider: str
    folder: str
    uid: str
    uidvalidity: str
    internal_date: str
    sender: str
    subject_fingerprint: str = ""
    size: int = 0
    has_attachments: bool = False
    auth_hint: str = "unknown"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        # 先扫真实属性：即使有人绕过 dataclass 塞了 body_* 属性，也要拦在出口
        for k in vars(self):
            if any(bad in k.lower() for bad in FORBIDDEN_FIELDS):
                raise ValueError(f"事件字段 {k} 命中禁止名单")
        d = asdict(self)
        # 投影到白名单，防止后续加字段时夹带正文
        out = {k: d[k] for k in ALLOWED_FIELDS if k in d}
        for k in out:
            if any(bad in k.lower() for bad in FORBIDDEN_FIELDS):
                raise ValueError(f"事件字段 {k} 命中禁止名单")
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "MailEvent":
        missing = [k for k in ("event_id", "account", "folder", "uid", "uidvalidity") if k not in d]
        if missing:
            raise ValueError(f"事件缺少必填字段: {missing}")
        if d.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ValueError(f"不支持的事件版本: {d.get('schema_version')}")
        return cls(**{k: d[k] for k in ALLOWED_FIELDS if k in d})

    def is_for(self, sender: str) -> bool:
        return self.sender.lower() == sender.lower()


@dataclass
class Cursor:
    # 消费游标。只在确认投递成功后前进，绝不回退
    account: str
    folder: str
    uidvalidity: str
    last_uid: str
    updated_at: str = ""


@dataclass
class DeliveryResult:
    delivered: bool
    consumer: str
    detail: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
