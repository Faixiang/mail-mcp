# IMAP + SMTP 通用适配器。覆盖 QQ/163/Gmail(应用专用密码)/Outlook(需 OAuth) 等绝大多数邮箱。
# 只实现协议搬运；消毒、taint、策略全部在返回后由上层处理。
from __future__ import annotations

import email
import imaplib
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime, parseaddr

from ..errors import E_PROVIDER_UNSUPPORTED, MailMCPError
from ..models import Address, Attachment, AuthResult, Message
from ..safety.sanitize import sanitize_body
from ..safety.taint import detect_injection
from .base import Capabilities

# 常见服务商预设，避免用户手填 host/port
PRESETS: dict[str, dict] = {
    "qq.com": {"imap": ("imap.qq.com", 993), "smtp": ("smtp.qq.com", 465)},
    "foxmail.com": {"imap": ("imap.qq.com", 993), "smtp": ("smtp.qq.com", 465)},
    "163.com": {"imap": ("imap.163.com", 993), "smtp": ("smtp.163.com", 465)},
    "126.com": {"imap": ("imap.126.com", 993), "smtp": ("smtp.126.com", 465)},
    "gmail.com": {"imap": ("imap.gmail.com", 993), "smtp": ("smtp.gmail.com", 587)},
    "outlook.com": {"imap": ("outlook.office365.com", 993), "smtp": ("smtp.office365.com", 587)},
    "hotmail.com": {"imap": ("outlook.office365.com", 993), "smtp": ("smtp.office365.com", 587)},
}

_UID_RE = re.compile(r"UID (\d+)", re.IGNORECASE)


@dataclass
class ImapCredentials:
    address: str
    password: str
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_starttls: bool = False


def _decode(v: str | None) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return v


class ImapSmtpAdapter:
    name = "imap_smtp"
    caps = Capabilities(
        folders=True,
        search_server_side=True,
        keywords=False,
        flags=True,
        move=False,
        attachments=True,
        threads=False,
        push_events=True,
        notes=["push 需 IMAP IDLE，本仓库不实现，交由独立触发层"],
    )

    def __init__(self, cred: ImapCredentials) -> None:
        self.cred = cred
        self._conn: imaplib.IMAP4_SSL | None = None
        dom = cred.address.rsplit("@", 1)[-1].lower()
        preset = PRESETS.get(dom)
        if not cred.imap_host:
            if not preset:
                raise MailMCPError(
                    E_PROVIDER_UNSUPPORTED,
                    f"未识别的邮箱域 {dom}，需显式传入 imap_host/smtp_host",
                    {"known": sorted(PRESETS)},
                )
            cred.imap_host = preset["imap"][0]
            cred.imap_port = cred.imap_port or preset["imap"][1]
        if not cred.smtp_host:
            cred.smtp_host = preset["smtp"][0] if preset else cred.imap_host.replace("imap", "smtp")
            cred.smtp_port = cred.smtp_port or (preset["smtp"][1] if preset else 465)

    # ---- 连接管理 ----
    def _connect(self) -> imaplib.IMAP4_SSL:
        if self._conn is not None:
            return self._conn
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(self.cred.imap_host, self.cred.imap_port, ssl_context=ctx)
        conn.login(self.cred.address, self.cred.password)
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    # ---- 读取 ----
    def list_mailboxes(self) -> list[dict]:
        conn = self._connect()
        typ, data = conn.list()
        out = []
        for raw in data or []:
            if not isinstance(raw, bytes):
                continue
            line = raw.decode("utf-8", "replace")
            m = re.match(r'\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+)', line)
            if not m:
                continue
            out.append(
                {
                    "name": m.group("name").strip('"'),
                    "delimiter": m.group("delim"),
                    "flags": m.group("flags").split(),
                }
            )
        return out

    def _select(self, folder: str) -> None:
        conn = self._connect()
        typ, _ = conn.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise MailMCPError(E_PROVIDER_UNSUPPORTED, f"无法选择邮件夹: {folder}")

    def list_messages(self, folder: str = "INBOX", limit: int = 20, unread_only: bool = False) -> list[dict]:
        self._select(folder)
        conn = self._conn
        assert conn is not None
        typ, data = conn.uid("search", None, "UNSEEN" if unread_only else "ALL")
        if typ != "OK":
            return []
        uids = (data[0] or b"").split()
        uids = uids[-limit:]
        uids.reverse()
        out = []
        for uid in uids:
            typ, msg_data = conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            hdr = email.message_from_bytes(msg_data[0][1])
            out.append(
                {
                    "message_id": f"{folder}:{uid.decode()}",
                    "subject": _decode(hdr.get("Subject")),
                    "from": parseaddr(hdr.get("From") or "")[1],
                    "date": hdr.get("Date"),
                }
            )
        return out

    def search_messages(self, folder: str, query: str, limit: int = 20) -> list[dict]:
        self._select(folder)
        conn = self._conn
        assert conn is not None
        # IMAP SEARCH 只支持 ASCII 关键字；中文需客户端过滤
        safe = query.replace('"', "")
        typ, data = conn.uid("search", None, "TEXT", f'"{safe}"')
        if typ != "OK":
            return []
        uids = (data[0] or b"").split()[-limit:]
        return [{"message_id": f"{folder}:{u.decode()}"} for u in uids]

    def get_message(self, message_id: str, folder: str | None = None) -> Message:
        if ":" not in message_id:
            raise MailMCPError(E_PROVIDER_UNSUPPORTED, f"message_id 格式应为 folder:uid，收到 {message_id}")
        folder_part, uid = message_id.rsplit(":", 1)
        folder = folder or folder_part
        self._select(folder)
        conn = self._conn
        assert conn is not None
        typ, data = conn.uid("fetch", uid, "(RFC822)")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            raise MailMCPError(E_PROVIDER_UNSUPPORTED, f"拉取失败: {message_id}")
        msg = email.message_from_bytes(data[0][1])
        return self._parse(msg, folder, uid)

    def _parse(self, msg: email.message.Message, folder: str, uid: str) -> Message:
        plain, html_part, atts = None, None, []
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                payload = part.get_payload(decode=True) or b""
                atts.append(
                    Attachment(
                        attachment_id=part.get("Content-ID") or part.get_filename() or "",
                        filename=_decode(part.get_filename()),
                        size=len(payload),
                        mime=ctype,
                    )
                )
                continue
            if ctype == "text/plain" and plain is None:
                plain = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
            elif ctype == "text/html" and html_part is None:
                html_part = (part.get_payload(decode=True) or b"").decode(
                    part.get_content_charset() or "utf-8", "replace"
                )

        body, rep = sanitize_body(plain, html_part)
        reasons = detect_injection(body)

        try:
            received = parsedate_to_datetime(msg.get("Date"))
        except Exception:
            from datetime import datetime, timezone

            received = datetime.now(timezone.utc)

        from_name, from_addr = parseaddr(msg.get("From") or "")
        auth = AuthResult(
            spf=msg.get("Received-SPF") and str(msg.get("Received-SPF")).split()[0],
            dkim="pass" if msg.get("DKIM-Signature") else None,
            dmarc=None,
        )

        return Message(
            message_id=f"{folder}:{uid}",
            thread_id=msg.get("Message-ID") or f"{folder}:{uid}",
            account=getattr(self.cred, "address", ""),
            provider=self.name,
            folder=folder,
            received_at=received,
            sender=Address(name=_decode(from_name), address=from_addr),
            to=[Address(*parseaddr(a)) for a in (msg.get_all("To") or [])],
            cc=[Address(*parseaddr(a)) for a in (msg.get_all("Cc") or [])],
            subject=_decode(msg.get("Subject")),
            flags=[],
            auth=auth,
            trust="untrusted",
            tainted=bool(reasons),
            taint_reasons=reasons,
            body_text=body,
            body_truncated=rep.truncated,
            quoted_stripped=rep.quoted_stripped,
            attachments=atts,
            headers_of_interest={
                "list-id": msg.get("List-Id"),
                "auto-submitted": msg.get("Auto-Submitted"),
                "x-agent-origin": msg.get("X-Agent-Origin"),
                "reply-to": msg.get("Reply-To"),
            },
        )

    def get_attachment(self, message_id: str, attachment_id: str, max_bytes: int = 10 * 1024 * 1024) -> bytes:
        folder_part, uid = message_id.rsplit(":", 1)
        self._select(folder_part)
        conn = self._conn
        assert conn is not None
        typ, data = conn.uid("fetch", uid, "(RFC822)")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            raise MailMCPError(E_PROVIDER_UNSUPPORTED, f"拉取失败: {message_id}")
        msg = email.message_from_bytes(data[0][1])
        for part in msg.walk():
            cid = part.get("Content-ID") or ""
            fn = part.get_filename() or ""
            if attachment_id not in (cid, fn, cid.strip("<>")):
                continue
            payload = part.get_payload(decode=True) or b""
            if len(payload) > max_bytes:
                raise MailMCPError(
                    E_PROVIDER_UNSUPPORTED, f"附件 {len(payload)} 字节超出上限 {max_bytes}", {"filename": fn}
                )
            return payload
        raise MailMCPError(E_PROVIDER_UNSUPPORTED, f"未找到附件: {attachment_id}")

    # ---- 发送 ----
    def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        headers: dict[str, str] | None = None,
        in_reply_to: str | None = None,
    ) -> str:
        msg = EmailMessage()
        msg["From"] = self.cred.address
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        # 固定标识，供对端环路检测
        msg["X-Agent-Origin"] = f"mail-mcp/{self.cred.address}"
        msg["Auto-Submitted"] = "auto-replied"
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        for k, v in (headers or {}).items():
            # 禁止覆盖身份与环路标识
            if k.lower() in ("from", "x-agent-origin", "auto-submitted"):
                continue
            msg[k] = v
        msg.set_content(body)

        ctx = ssl.create_default_context()
        if self.cred.smtp_port == 587:
            with smtplib.SMTP(self.cred.smtp_host, self.cred.smtp_port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(self.cred.address, self.cred.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(self.cred.smtp_host, self.cred.smtp_port, context=ctx, timeout=30) as s:
                s.login(self.cred.address, self.cred.password)
                s.send_message(msg)
        return msg.get("Message-ID") or ""
