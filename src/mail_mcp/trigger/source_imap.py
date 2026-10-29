# 事件源：IMAP 轮询。IDLE 需要长连接与重连处理，放在后续迭代，接口已预留。
from __future__ import annotations

import email
import imaplib
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime, parseaddr

from ..adapters.imap_smtp import PRESETS
from .contracts import MailEvent, fingerprint, make_event_id

_UIDVALIDITY_RE = re.compile(r"UIDVALIDITY (\d+)", re.IGNORECASE)


@dataclass
class PollResult:
    events: list[MailEvent]
    uidvalidity: str
    last_uid: str
    resync_required: bool = False


def _decode(v: str | None) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return v


class ImapPoller:
    name = "imap_poll"

    def __init__(
        self,
        account: str,
        password: str,
        folder: str = "INBOX",
        imap_host: str = "",
        imap_port: int = 993,
        conn=None,
    ) -> None:
        self.account = account
        self.password = password
        self.folder = folder
        dom = account.rsplit("@", 1)[-1].lower()
        preset = PRESETS.get(dom)
        self.imap_host = imap_host or (preset["imap"][0] if preset else "")
        self.imap_port = imap_port or (preset["imap"][1] if preset else 993)
        # 允许注入连接，便于离线测试
        self._conn = conn

    def _connect(self):
        if self._conn is not None:
            return self._conn
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ctx)
        conn.login(self.account, self.password)
        self._conn = conn
        return conn

    def uidvalidity(self) -> str:
        conn = self._connect()
        typ, data = conn.select(f'"{self.folder}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"无法选择邮件夹 {self.folder}")
        for item in data or []:
            s = item.decode() if isinstance(item, bytes) else str(item)
            m = _UIDVALIDITY_RE.search(s)
            if m:
                return m.group(1)
        return "0"

    def poll(self, last_uid: str | None, uidvalidity: str | None = None, limit: int = 50) -> PollResult:
        conn = self._connect()
        conn.select(f'"{self.folder}"', readonly=True)
        current_uv = self.uidvalidity()

        # UIDVALIDITY 变了，说明服务端重建了 uid 空间，旧游标不可信
        if uidvalidity and current_uv and uidvalidity != current_uv:
            return PollResult([], current_uv, last_uid or "0", resync_required=True)

        criteria = f"UID {int(last_uid) + 1}:*" if last_uid else "ALL"
        typ, data = conn.uid("search", None, criteria)
        if typ != "OK":
            return PollResult([], current_uv, last_uid or "0")

        uids = (data[0] or b"").split()
        uids = [u for u in uids if u][-limit:]
        events: list[MailEvent] = []
        max_uid = last_uid or "0"
        for raw_uid in uids:
            uid = raw_uid.decode() if isinstance(raw_uid, bytes) else str(raw_uid)
            ev = self._to_event(conn, uid, current_uv)
            if ev is not None:
                events.append(ev)
            try:
                if int(uid) > int(max_uid):
                    max_uid = uid
            except ValueError:
                pass
        return PollResult(events, current_uv, max_uid)

    def _to_event(self, conn, uid: str, uidvalidity: str) -> MailEvent | None:
        typ, msg_data = conn.uid(
            "fetch",
            uid,
            "(BODY.PEEK[HEADER.FIELDS (FROM DATE SUBJECT CONTENT-TYPE CONTENT-DISPOSITION SIZE)])",
        )
        if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
            return None
        hdr = email.message_from_bytes(msg_data[0][1])
        _, from_addr = parseaddr(hdr.get("From") or "")
        try:
            internal = parsedate_to_datetime(hdr.get("Date")).isoformat()
        except Exception:
            internal = datetime.now(timezone.utc).isoformat()

        ctype = (hdr.get("Content-Type") or "").lower()
        disp = (hdr.get("Content-Disposition") or "").lower()
        has_att = "multipart/mixed" in ctype or "attachment" in disp
        try:
            size = int(hdr.get("Size") or 0)
        except ValueError:
            size = 0

        return MailEvent(
            event_id=make_event_id(self.account, self.folder, uidvalidity, uid),
            account=self.account,
            provider="imap_poll",
            folder=self.folder,
            uid=uid,
            uidvalidity=uidvalidity,
            internal_date=internal,
            sender=from_addr,
            subject_fingerprint=fingerprint(_decode(hdr.get("Subject"))),
            size=size,
            has_attachments=has_att,
            auth_hint="unknown",
        )

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None
