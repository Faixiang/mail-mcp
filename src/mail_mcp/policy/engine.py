# 规则裁决。优先级：主题否决 > 精确地址 > 域 > 默认。
from __future__ import annotations

from datetime import datetime

from ..models import AuthResult, PolicyDecision
from .schema import PolicyConfig


def _subject_hit(rule_keywords: list[str], subject: str) -> bool:
    s = (subject or "").lower()
    return any(k.lower() in s for k in rule_keywords)


def _identity_hit(rule_match: dict, sender: str, domain: str) -> bool:
    addr = (rule_match.get("address") or "").lower()
    if addr and addr == sender.lower():
        return True
    dom = (rule_match.get("domain") or "").lower()
    if dom and dom == domain:
        return True
    return False


def _in_quiet_hours(qh: dict, now: datetime) -> bool:
    start, end = qh.get("start"), qh.get("end")
    if not start or not end:
        return False
    hhmm = now.strftime("%H:%M")
    if start <= end:
        return start <= hhmm < end
    # 跨午夜
    return hhmm >= start or hhmm < end


def evaluate(
    policy: PolicyConfig,
    sender: str,
    subject: str,
    auth: AuthResult | None = None,
    first_contact: bool = False,
    now: datetime | None = None,
) -> PolicyDecision:
    sender = (sender or "").strip().lower()
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    now = now or datetime.now()
    evaluated: dict[str, bool] = {}
    reasons: list[str] = []

    # 1. 主题否决，最高优先，直接 drop
    for r in policy.rules:
        kws = r.match.get("subject_contains") or []
        if kws and r.action == "drop" and _subject_hit(list(kws), subject):
            evaluated["subject_veto"] = True
            return PolicyDecision(
                decision="deny",
                action="drop",
                matched_rule=f"subject_veto:{','.join(kws)}",
                priority=1000 + r.priority,
                evaluated=evaluated,
                reasons=[f"主题命中否决词: {kws}"],
            )
    evaluated["subject_veto"] = False

    # 2. 身份规则，按有效优先级降序，命中即停
    identity_rules = [
        r for r in policy.rules
        if (r.match.get("address") or r.match.get("domain"))
    ]
    identity_rules.sort(key=lambda r: r.effective_priority(), reverse=True)
    hit = None
    for r in identity_rules:
        if _identity_hit(r.match, sender, domain):
            hit = r
            break

    if hit is not None:
        action = hit.action
        rule_name = f"{'address' if hit.match.get('address') else 'domain'}:{hit.match.get('address') or hit.match.get('domain')}"
        priority = hit.effective_priority()
    else:
        action = policy.default_action
        rule_name = "default"
        priority = 0
    evaluated["identity_match"] = hit is not None
    evaluated["in_allowlist"] = sender in policy.allowlist_set() or (
        domain and domain in policy.domain_set()
    )

    # 3. 认证不通过则降级，不直接拒绝
    if policy.require_auth_pass and auth is not None and not auth.verified:
        if action == "auto_reply":
            reasons.append("SPF/DKIM/DMARC 未全通过，自动回复降级为待审草稿")
            action = "draft_for_review"
        evaluated["auth_verified"] = False
    else:
        evaluated["auth_verified"] = True if auth is None else auth.verified

    # 4. 首次接触一律待审
    if first_contact and action == "auto_reply":
        reasons.append("首次接触该发件人，不自动回复")
        action = "draft_for_review"
    evaluated["first_contact"] = first_contact

    # 5. 静默时段只读
    if _in_quiet_hours(policy.quiet_hours, now) and action in ("auto_reply", "draft_for_review"):
        reasons.append("处于静默时段，降级为只读")
        action = "read_only"
    evaluated["quiet_hours"] = _in_quiet_hours(policy.quiet_hours, now)

    decision = "deny" if action == "drop" else ("allow" if action == "auto_reply" else "confirm")
    return PolicyDecision(
        decision=decision,
        action=action,
        matched_rule=rule_name,
        priority=priority,
        evaluated=evaluated,
        reasons=reasons,
    )
