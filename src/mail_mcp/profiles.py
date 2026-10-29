# Profile 定义。核心原则：越界的工具直接不注册，而不是注册后拒绝。
from __future__ import annotations

from dataclasses import dataclass

READER_TOOLS = (
    "list_mailboxes",
    "list_messages",
    "search_messages",
    "get_message",
    "get_thread",
    "get_attachment",
    "get_quota",
    "get_me",
)

WRITE_TOOLS = (
    "send_message",
    "reply_message",
    "forward_message",
    "mark_message",
    "move_message",
)

DANGER_TOOLS = (
    "delete_message",
    "purge_messages",
)

PROFILE_READER = "reader"
PROFILE_FULL = "full"
PROFILE_DANGER = "danger"


@dataclass(frozen=True)
class Profile:
    name: str
    tools: tuple[str, ...]
    allows_write: bool
    allows_delete: bool
    account: str = ""

    def registered(self, enable_delete: bool = False) -> tuple[str, ...]:
        if self.allows_delete and not enable_delete:
            return tuple(t for t in self.tools if t not in DANGER_TOOLS)
        return self.tools


PROFILES: dict[str, Profile] = {
    PROFILE_READER: Profile(PROFILE_READER, READER_TOOLS, allows_write=False, allows_delete=False),
    PROFILE_FULL: Profile(PROFILE_FULL, READER_TOOLS + WRITE_TOOLS, allows_write=True, allows_delete=False),
    PROFILE_DANGER: Profile(
        PROFILE_DANGER, READER_TOOLS + WRITE_TOOLS + DANGER_TOOLS, allows_write=True, allows_delete=True
    ),
}


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        from .errors import E_INVALID_ARGUMENT, MailMCPError

        raise MailMCPError(
            E_INVALID_ARGUMENT,
            f"未知 profile: {name}",
            {"valid": sorted(PROFILES)},
        ) from None
