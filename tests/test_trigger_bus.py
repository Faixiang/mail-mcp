import os

import pytest

from mail_mcp.trigger.bus import EventBus
from mail_mcp.trigger.contracts import MailEvent, make_event_id


def _ev(uid="1", uv="100", sender="x@y.com"):
    return MailEvent(
        event_id=make_event_id("a@b.com", "INBOX", uv, uid),
        account="a@b.com",
        provider="imap_poll",
        folder="INBOX",
        uid=uid,
        uidvalidity=uv,
        internal_date="2026-10-30T09:00:00+08:00",
        sender=sender,
    )


@pytest.fixture()
def bus(tmp_path):
    b = EventBus(os.path.join(str(tmp_path), "t.db"))
    yield b
    b.close()


def test_ingest_is_idempotent(bus):
    e = _ev()
    assert bus.ingest(e) is True
    assert bus.ingest(e) is False


def test_pending_excludes_delivered(bus):
    e1, e2 = _ev("1"), _ev("2")
    bus.ingest(e1)
    bus.ingest(e2)
    assert len(bus.pending("c1")) == 2
    bus.mark(e1.event_id, "c1", "ok")
    assert len(bus.pending("c1")) == 1


def test_pending_is_per_consumer(bus):
    e = _ev()
    bus.ingest(e)
    bus.mark(e.event_id, "c1", "ok")
    assert bus.pending("c1") == []
    assert len(bus.pending("c2")) == 1


def test_failed_event_is_retried(bus):
    e = _ev()
    bus.ingest(e)
    bus.mark(e.event_id, "c1", "failed", {"attempts": 1})
    assert len(bus.pending("c1")) == 1
    assert bus.attempt_count(e.event_id, "c1") == 1


def test_dead_event_not_retried_forever(bus):
    e = _ev()
    bus.ingest(e)
    bus.mark(e.event_id, "c1", "dead", {"reason": "max attempts"})
    assert bus.attempt_count(e.event_id, "c1") > 3


def test_cursor_monotonic(bus):
    bus.set_cursor("a@b.com", "INBOX", "100", "10")
    bus.set_cursor("a@b.com", "INBOX", "100", "8")  # 回退请求必须被忽略
    assert bus.get_cursor("a@b.com", "INBOX").last_uid == "10"


def test_cursor_reset_on_uidvalidity_change(bus):
    bus.set_cursor("a@b.com", "INBOX", "100", "10")
    bus.set_cursor("a@b.com", "INBOX", "200", "1")
    cur = bus.get_cursor("a@b.com", "INBOX")
    assert cur.uidvalidity == "200" and cur.last_uid == "1"


def test_get_returns_event(bus):
    e = _ev()
    bus.ingest(e)
    assert bus.get(e.event_id) == e
    assert bus.get("nope") is None
