# policy.yaml 的结构定义与加载校验。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import E_INVALID_ARGUMENT, MailMCPError

VALID_ACTIONS = {"auto_reply", "draft_for_review", "read_only", "drop"}


@dataclass
class Rule:
    match: dict[str, Any] = field(default_factory=dict)
    action: str = "draft_for_review"
    priority: int = 0
    note: str = ""

    @property
    def specificity(self) -> int:
        # 地址精确 > 域 > 主题关键词
        m = self.match
        if m.get("address"):
            return 50
        if m.get("domain"):
            return 20
        if m.get("subject_contains"):
            return 30
        if m.get("list_id"):
            return 10
        return 0

    def effective_priority(self) -> int:
        return self.priority + self.specificity


@dataclass
class Limits:
    max_sends_per_hour: int = 10
    max_sends_per_day: int = 50
    max_recipients_per_send: int = 3
    max_auto_replies_per_thread: int = 2


@dataclass
class PolicyConfig:
    owner: str = ""
    default_action: str = "draft_for_review"
    require_auth_pass: bool = True
    allowlist: list[str] = field(default_factory=list)
    allowlist_domains: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)
    quiet_hours: dict[str, Any] = field(default_factory=dict)
    subaddress_tag: str = "agent"

    def allowlist_set(self) -> set[str]:
        return {a.strip().lower() for a in self.allowlist if a.strip()}

    def domain_set(self) -> set[str]:
        return {d.strip().lower() for d in self.allowlist_domains if d.strip()}


def _as_rule(raw: dict[str, Any], idx: int) -> Rule:
    action = str(raw.get("action", "draft_for_review"))
    if action not in VALID_ACTIONS:
        raise MailMCPError(
            E_INVALID_ARGUMENT,
            f"rules[{idx}].action 非法: {action}",
            {"valid": sorted(VALID_ACTIONS)},
        )
    match = raw.get("match") or {}
    if not isinstance(match, dict) or not match:
        raise MailMCPError(E_INVALID_ARGUMENT, f"rules[{idx}].match 不能为空")
    return Rule(
        match=match,
        action=action,
        priority=int(raw.get("priority", 0)),
        note=str(raw.get("note", "")),
    )


def load_policy(raw: dict[str, Any]) -> PolicyConfig:
    limits_raw = raw.get("limits") or {}
    limits = Limits(
        max_sends_per_hour=int(limits_raw.get("max_sends_per_hour", 10)),
        max_sends_per_day=int(limits_raw.get("max_sends_per_day", 50)),
        max_recipients_per_send=int(limits_raw.get("max_recipients_per_send", 3)),
        max_auto_replies_per_thread=int(limits_raw.get("max_auto_replies_per_thread", 2)),
    )
    rules = [_as_rule(r, i) for i, r in enumerate(raw.get("rules") or [])]
    return PolicyConfig(
        owner=str(raw.get("owner", "")),
        default_action=str(raw.get("default_action", "draft_for_review")),
        require_auth_pass=bool(raw.get("require_auth_pass", True)),
        allowlist=list(raw.get("allowlist") or []),
        allowlist_domains=list(raw.get("allowlist_domains") or []),
        rules=rules,
        limits=limits,
        quiet_hours=dict(raw.get("quiet_hours") or {}),
        subaddress_tag=str(raw.get("subaddress_tag", "agent")),
    )
