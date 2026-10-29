import sys

from mail_mcp.trigger.consumer import CallbackConsumer, SubprocessConsumer
from mail_mcp.trigger.contracts import MailEvent, make_event_id


def _ev():
    return MailEvent(
        event_id=make_event_id("a@b.com", "INBOX", "100", "7"),
        account="a@b.com",
        provider="imap_poll",
        folder="INBOX",
        uid="7",
        uidvalidity="100",
        internal_date="2026-10-30T09:00:00+08:00",
        sender="x@y.com",
    )


def test_subprocess_receives_event_without_body():
    # 子进程把 stdin 原样回显，断言里面没有任何正文类字段
    code = "import sys;print(sys.stdin.read())"
    c = SubprocessConsumer([sys.executable, "-c", code], timeout=30)
    r = c.dispatch(_ev())
    assert r.delivered is True
    out = r.detail["stdout_tail"]
    assert "event_id" in out
    for bad in ("body", "body_text", "html", "snippet"):
        assert bad not in out


def test_subprocess_nonzero_exit_is_failure():
    c = SubprocessConsumer([sys.executable, "-c", "import sys;sys.exit(3)"], timeout=30)
    r = c.dispatch(_ev())
    assert r.delivered is False
    assert r.error == "nonzero_exit"


def test_callback_consumer_swallows_exception():
    def boom(ev):
        raise RuntimeError("nope")

    r = CallbackConsumer(boom).dispatch(_ev())
    assert r.delivered is False
    assert "RuntimeError" in r.error
