import os

from mail_mcp.trigger.bus import EventBus
from mail_mcp.trigger.consumer import CallbackConsumer
from mail_mcp.trigger.contracts import DeliveryResult, MailEvent, make_event_id
from mail_mcp.trigger.daemon import DaemonConfig, TriggerDaemon
from mail_mcp.trigger.source_imap import PollResult


def _ev(uid, uv="100"):
    return MailEvent(
        event_id=make_event_id("a@b.com", "INBOX", uv, uid),
        account="a@b.com",
        provider="imap_poll",
        folder="INBOX",
        uid=uid,
        uidvalidity=uv,
        internal_date="2026-10-30T09:00:00+08:00",
        sender="x@y.com",
    )


class FakePoller:
    account = "a@b.com"
    folder = "INBOX"

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def poll(self, last_uid=None, uidvalidity=None, limit=50):
        self.calls.append((last_uid, uidvalidity))
        return self.batches.pop(0) if self.batches else PollResult([], "100", last_uid or "0")


def _bus(tmp_path):
    return EventBus(os.path.join(str(tmp_path), "t.db"))


def test_poll_once_delivers_and_advances_cursor(tmp_path):
    bus = _bus(tmp_path)
    poller = FakePoller([PollResult([_ev("1"), _ev("2")], "100", "2")])
    got = []
    d = TriggerDaemon(poller, bus, [CallbackConsumer(got.append)], DaemonConfig())
    n = d.poll_once()
    assert n == 2
    assert len(got) == 2
    cur = bus.get_cursor("a@b.com", "INBOX")
    assert cur.last_uid == "2"
    bus.close()


def test_second_poll_passes_cursor(tmp_path):
    bus = _bus(tmp_path)
    poller = FakePoller([
        PollResult([_ev("1")], "100", "1"),
        PollResult([], "100", "1"),
    ])
    d = TriggerDaemon(poller, bus, [CallbackConsumer(lambda e: None)], DaemonConfig())
    d.poll_once()
    d.poll_once()
    assert poller.calls[1] == ("1", "100")
    bus.close()


def test_duplicate_events_not_redelivered(tmp_path):
    bus = _bus(tmp_path)
    poller = FakePoller([
        PollResult([_ev("1")], "100", "1"),
        PollResult([_ev("1")], "100", "1"),
    ])
    got = []
    d = TriggerDaemon(poller, bus, [CallbackConsumer(got.append)], DaemonConfig())
    d.poll_once()
    d.poll_once()
    assert len(got) == 1
    bus.close()


def test_resync_resets_cursor_without_guessing(tmp_path):
    bus = _bus(tmp_path)
    bus.set_cursor("a@b.com", "INBOX", "100", "50")
    poller = FakePoller([PollResult([], "200", "50", resync_required=True)])
    got = []
    d = TriggerDaemon(poller, bus, [CallbackConsumer(got.append)], DaemonConfig())
    assert d.poll_once() == 0
    cur = bus.get_cursor("a@b.com", "INBOX")
    assert cur.uidvalidity == "200" and cur.last_uid == "0"
    assert got == []
    bus.close()


def test_failed_consumer_marks_and_retries(tmp_path):
    bus = _bus(tmp_path)
    poller = FakePoller([PollResult([_ev("1")], "100", "1")])
    calls = {"n": 0}

    class Flaky:
        name = "flaky"

        def dispatch(self, ev):
            calls["n"] += 1
            if calls["n"] == 1:
                return DeliveryResult(False, "flaky", {}, error="boom")
            return DeliveryResult(True, "flaky", {})

    d = TriggerDaemon(poller, bus, [Flaky()], DaemonConfig())
    d.poll_once()
    assert calls["n"] == 1
    d.poll_once()  # 同一事件重试，第二次成功
    assert calls["n"] == 2
    assert bus.pending("flaky") == []
    bus.close()


def test_dead_after_max_attempts(tmp_path):
    bus = _bus(tmp_path)
    e = _ev("1")
    bus.ingest(e)
    bus.mark(e.event_id, "always_fail", "failed", {"attempts": 3})

    class Never:
        name = "always_fail"

        def dispatch(self, ev):
            raise AssertionError("不应再被调用")

    poller = FakePoller([PollResult([], "100", "1")])
    d = TriggerDaemon(poller, bus, [Never()], DaemonConfig())
    d.poll_once()
    bus.close()
