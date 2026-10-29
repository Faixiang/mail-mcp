# 统一接口。适配器只做协议差异，不做策略判断。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import Message


@dataclass
class Capabilities:
    folders: bool = True
    search_server_side: bool = True
    keywords: bool = False
    flags: bool = True
    move: bool = False
    attachments: bool = True
    threads: bool = False
    push_events: bool = False
    notes: list[str] = field(default_factory=list)


class Adapter(Protocol):
    name: str
    caps: Capabilities

    def list_mailboxes(self) -> list[dict]: ...

    def list_messages(self, folder: str, limit: int = 20, unread_only: bool = False) -> list[dict]: ...

    def search_messages(self, folder: str, query: str, limit: int = 20) -> list[dict]: ...

    def get_message(self, message_id: str, folder: str | None = None) -> Message: ...

    def get_attachment(self, message_id: str, attachment_id: str, max_bytes: int) -> bytes: ...

    def send(self, to: list[str], subject: str, body: str, headers: dict[str, str] | None = None) -> str: ...
