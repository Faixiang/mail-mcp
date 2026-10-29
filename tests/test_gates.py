from mail_mcp.safety.gates import BATCH_CONFIRM_THRESHOLD, GateInput, evaluate_send_gate


def _base(**kw):
    d = dict(
        profile_allows=True,
        recipients=["wife@example.com"],
        allowlist={"wife@example.com"},
        allowlist_domains=set(),
        confirmed=True,
    )
    d.update(kw)
    return GateInput(**d)


def test_happy_path_allow():
    r = evaluate_send_gate(_base())
    assert r.decision == "allow"


def test_profile_denied_first():
    r = evaluate_send_gate(_base(profile_allows=False, tainted=True))
    assert r.decision == "deny"
    assert r.gate == "profile"


def test_unknown_recipient_needs_confirm():
    r = evaluate_send_gate(_base(recipients=["stranger@evil.com"]))
    assert r.decision == "confirm"
    assert r.gate == "whitelist"
    assert "stranger@evil.com" in r.detail["recipients"]


def test_domain_allowlist_passes():
    r = evaluate_send_gate(_base(recipients=["bob@company.com"], allowlist=set(), allowlist_domains={"company.com"}))
    assert r.decision == "allow"


def test_batch_threshold():
    recips = [f"u{i}@example.com" for i in range(BATCH_CONFIRM_THRESHOLD + 1)]
    r = evaluate_send_gate(_base(recipients=recips, allowlist=set(recips)))
    assert r.decision == "confirm"
    assert r.gate == "batch"


def test_content_flags_block():
    r = evaluate_send_gate(_base(content_flags=["contains_password_request"]))
    assert r.decision == "confirm"
    assert r.gate == "content"


def test_taint_denies_even_if_confirmed():
    r = evaluate_send_gate(_base(tainted=True))
    assert r.decision == "deny"
    assert r.gate == "taint"


def test_loop_detected_denies():
    r = evaluate_send_gate(_base(loop_reasons=["auto-submitted header"]))
    assert r.decision == "deny"
    assert r.gate == "loop"


def test_quota_denies():
    r = evaluate_send_gate(_base(quota_ok=False))
    assert r.decision == "deny"
    assert r.gate == "quota"


def test_unconfirmed_needs_confirm_at_last_step():
    r = evaluate_send_gate(_base(confirmed=False))
    assert r.decision == "confirm"
    assert r.gate == "confirm_required"
