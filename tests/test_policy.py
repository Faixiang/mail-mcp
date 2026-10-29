from datetime import datetime

from mail_mcp.models import AuthResult
from mail_mcp.policy.engine import evaluate
from mail_mcp.policy.schema import load_policy

RAW = {
    "owner": "me@example.com",
    "default_action": "draft_for_review",
    "require_auth_pass": True,
    "allowlist": ["wife@example.com"],
    "allowlist_domains": ["company.com"],
    "rules": [
        {"match": {"subject_contains": ["退订", "unsubscribe"]}, "action": "drop", "priority": 100},
        {"match": {"address": "wife@example.com"}, "action": "auto_reply", "priority": 50},
        {"match": {"domain": "company.com"}, "action": "draft_for_review", "priority": 20},
    ],
    "limits": {"max_sends_per_hour": 5},
    "quiet_hours": {"start": "23:00", "end": "07:30"},
}

PASS = AuthResult(spf="pass", dkim="pass", dmarc="pass")
FAIL = AuthResult(spf="fail", dkim="none", dmarc="fail")
NOON = datetime(2026, 10, 30, 12, 0)
NIGHT = datetime(2026, 10, 30, 23, 30)


def _pol():
    return load_policy(RAW)


def test_subject_veto_wins_over_address():
    d = evaluate(_pol(), "wife@example.com", "促销 退订 点这里", PASS, now=NOON)
    assert d.action == "drop"
    assert d.decision == "deny"


def test_address_rule_auto_reply():
    d = evaluate(_pol(), "wife@example.com", "晚饭吃什么", PASS, now=NOON)
    assert d.action == "auto_reply"
    assert d.decision == "allow"
    assert d.matched_rule.startswith("address:")


def test_domain_rule():
    d = evaluate(_pol(), "alice@company.com", "周报", PASS, now=NOON)
    assert d.action == "draft_for_review"
    assert d.matched_rule.startswith("domain:")


def test_default_for_unknown_sender():
    d = evaluate(_pol(), "stranger@nowhere.io", "hi", PASS, now=NOON)
    assert d.action == "draft_for_review"
    assert d.matched_rule == "default"


def test_auth_failure_downgrades_not_denies():
    d = evaluate(_pol(), "wife@example.com", "晚饭", FAIL, now=NOON)
    assert d.action == "draft_for_review"
    assert any("SPF/DKIM/DMARC" in r for r in d.reasons)


def test_first_contact_downgrade():
    d = evaluate(_pol(), "wife@example.com", "Hi", PASS, first_contact=True, now=NOON)
    assert d.action == "draft_for_review"


def test_quiet_hours_read_only():
    d = evaluate(_pol(), "wife@example.com", "还没睡", PASS, now=NIGHT)
    assert d.action == "read_only"


def test_quiet_hours_cross_midnight_early_morning():
    d = evaluate(_pol(), "wife@example.com", "早", PASS, now=datetime(2026, 10, 30, 6, 0))
    assert d.action == "read_only"


def test_priority_address_beats_domain():
    raw = dict(RAW)
    pol = load_policy(raw)
    d = evaluate(pol, "wife@example.com", "x", PASS, now=NOON)
    assert d.priority >= 50


def test_invalid_action_rejected():
    import pytest
    from mail_mcp.errors import MailMCPError

    with pytest.raises(MailMCPError):
        load_policy({"rules": [{"match": {"address": "a@b.com"}, "action": "explode"}]})
