# 出站闸门。十步判定，顺序即优先级，任一步 deny 即终止。
# 设计前提：模型可能已被注入污染，因此这里不信任任何上游判断，只信自己的规则。
from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import (
    E_LOOP_DETECTED,
    E_NEED_CONFIRM,
    E_POLICY_DENIED,
    E_PROFILE_DENIED,
    E_QUOTA_EXCEEDED,
    E_RATE_LIMITED,
    E_TAINT_WRITE_BLOCKED,
)
from ..models import GateResult, PolicyDecision

BATCH_CONFIRM_THRESHOLD = 3


@dataclass
class GateInput:
    profile_allows: bool = True
    policy: PolicyDecision | None = None
    recipients: list[str] = field(default_factory=list)
    allowlist: set[str] = field(default_factory=set)
    allowlist_domains: set[str] = field(default_factory=set)
    content_flags: list[str] = field(default_factory=list)
    quota_ok: bool = True
    rate_ok: bool = True
    tainted: bool = False
    loop_reasons: list[str] = field(default_factory=list)
    confirmed: bool = False


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def evaluate_send_gate(gi: GateInput) -> GateResult:
    reasons: list[str] = []

    # 1. profile
    if not gi.profile_allows:
        return GateResult("deny", "profile", [E_PROFILE_DENIED], {"gate": "profile"})

    # 2. 策略
    if gi.policy is not None:
        if gi.policy.action == "drop":
            return GateResult("deny", "policy", [E_POLICY_DENIED], {"action": "drop"})
        reasons.extend(gi.policy.reasons)

    # 3. 白名单
    unknown = []
    for r in gi.recipients:
        a = r.strip().lower()
        if a in gi.allowlist:
            continue
        if _domain(a) and _domain(a) in gi.allowlist_domains:
            continue
        unknown.append(a)
    if unknown:
        return GateResult(
            "confirm",
            "whitelist",
            reasons + [E_NEED_CONFIRM],
            {"gate": "whitelist", "recipients": unknown},
        )

    # 4. 批量阈值
    if len(gi.recipients) > BATCH_CONFIRM_THRESHOLD:
        return GateResult(
            "confirm",
            "batch",
            reasons + [E_NEED_CONFIRM],
            {"gate": "batch", "count": len(gi.recipients)},
        )

    # 5. 内容审查
    if gi.content_flags:
        return GateResult(
            "confirm",
            "content",
            reasons + [E_NEED_CONFIRM],
            {"gate": "content", "flags": list(gi.content_flags)},
        )

    # 6. 频率与配额
    if not gi.rate_ok:
        return GateResult("deny", "rate", reasons + [E_RATE_LIMITED], {"gate": "rate"})
    if not gi.quota_ok:
        return GateResult("deny", "quota", reasons + [E_QUOTA_EXCEEDED], {"gate": "quota"})

    # 7. taint
    if gi.tainted:
        return GateResult(
            "deny", "taint", reasons + [E_TAINT_WRITE_BLOCKED], {"gate": "taint"}
        )

    # 8. 环路
    if gi.loop_reasons:
        return GateResult(
            "deny", "loop", reasons + [E_LOOP_DETECTED], {"gate": "loop", "hits": list(gi.loop_reasons)}
        )

    # 9. 两段式确认
    if not gi.confirmed:
        return GateResult(
            "confirm",
            "confirm_required",
            reasons + [E_NEED_CONFIRM],
            {"gate": "confirm_required", "recipients": list(gi.recipients)},
        )

    # 10. 放行
    return GateResult("allow", "none", reasons or ["all checks passed"])
