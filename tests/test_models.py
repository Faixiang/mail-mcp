from datetime import datetime, timezone

from mail_mcp.models import Address, AuthResult, Message


def test_auth_requires_all_three_pass():
    assert AuthResult("pass", "pass", "pass").verified is True
    assert AuthResult("pass", "pass", None).verified is False
    assert AuthResult("fail", "pass", "pass").verified is False


def test_message_defaults_untrusted():
    m = Message(
        message_id="INBOX:1",
        thread_id="t1",
        account="a@b.com",
        provider="imap_smtp",
        folder="INBOX",
        received_at=datetime.now(timezone.utc),
        sender=Address("", "x@y.com"),
    )
    assert m.trust == "untrusted"
    assert m.tainted is False


def test_message_to_dict_serializable():
    import json

    m = Message(
        message_id="INBOX:1",
        thread_id="t1",
        account="a@b.com",
        provider="imap_smtp",
        folder="INBOX",
        received_at=datetime.now(timezone.utc),
        sender=Address("Bob", "x@y.com"),
    )
    s = json.dumps(m.to_dict())
    assert "INBOX:1" in s
