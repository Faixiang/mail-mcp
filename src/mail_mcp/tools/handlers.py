# 每个工具的处理器。返回值即 MCP tool 的 content，错误统一转 MailMCPError。
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from ..errors import E_INVALID_ARGUMENT, E_PROFILE_DENIED, MailMCPError
from ..models import GateResult
from ..policy.engine import evaluate as evaluate_policy
from ..profiles import DANGER_TOOLS
from ..safety.audit import AuditLog
from ..safety.gates import GateInput, evaluate_send_gate


@dataclass
class HandlerContext:
    profile: Any
    policy: Any
    adapter: Any
    audit: AuditLog
    confirmed_token: str = ""

    def require(self, tool: str) -> None:
        if tool not in self.profile.registered():
            raise MailMCPError(
                E_PROFILE_DENIED,
                f"工具 {tool} 在当前 profile({self.profile.name}) 下未注册",
                {"profile": self.profile.name},
            )


def _need(args: dict, key: str, typ: type | None = None) -> Any:
    if key not in args or args[key] in (None, ""):
        raise MailMCPError(E_INVALID_ARGUMENT, f"缺少必填参数: {key}")
    v = args[key]
    if typ is not None and not isinstance(v, typ):
        raise MailMCPError(E_INVALID_ARGUMENT, f"参数 {key} 类型应为 {typ.__name__}")
    return v


def build_handlers(ctx: HandlerContext) -> dict[str, Callable[[dict], dict]]:
    def list_mailboxes(args: dict) -> dict:
        ctx.require("list_mailboxes")
        return {"mailboxes": ctx.adapter.list_mailboxes()}

    def list_messages(args: dict) -> dict:
        ctx.require("list_messages")
        folder = args.get("folder", "INBOX")
        limit = min(int(args.get("limit", 20)), 100)
        return {
            "messages": ctx.adapter.list_messages(
                folder=folder, limit=limit, unread_only=bool(args.get("unread_only", False))
            )
        }

    def search_messages(args: dict) -> dict:
        ctx.require("search_messages")
        query = _need(args, "query", str)
        return {
            "messages": ctx.adapter.search_messages(
                folder=args.get("folder", "INBOX"), query=query, limit=min(int(args.get("limit", 20)), 100)
            )
        }

    def get_message(args: dict) -> dict:
        ctx.require("get_message")
        mid = _need(args, "message_id", str)
        msg = ctx.adapter.get_message(mid, args.get("folder"))
        d = msg.to_dict()
        ctx.audit.write({"op": "get_message", "message_id": mid, "tainted": msg.tainted})
        return d

    def get_thread(args: dict) -> dict:
        ctx.require("get_thread")
        tid = _need(args, "thread_id", str)
        return {"thread_id": tid, "messages": [ctx.adapter.get_message(tid).to_dict()]}

    def get_attachment(args: dict) -> dict:
        ctx.require("get_attachment")
        mid = _need(args, "message_id", str)
        aid = _need(args, "attachment_id", str)
        max_bytes = int(args.get("max_bytes", 10 * 1024 * 1024))
        data = ctx.adapter.get_attachment(mid, aid, max_bytes)
        # 落沙箱而不是直接回给模型，避免二进制进上下文
        out_dir = os.path.join(getattr(ctx, "sandbox_dir", "."), mid.replace(":", "_"))
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, aid.replace("/", "_").replace("\\", "_") or "attachment.bin")
        with open(path, "wb") as f:
            f.write(data)
        ctx.audit.write({"op": "get_attachment", "message_id": mid, "attachment_id": aid, "bytes": len(data)})
        return {"path": path, "bytes": len(data)}

    def get_quota(args: dict) -> dict:
        ctx.require("get_quota")
        return {"note": "IMAP 无统一配额接口，当前适配器不提供"}

    def get_me(args: dict) -> dict:
        ctx.require("get_me")
        return {"account": getattr(ctx.profile, "account", ""), "profile": ctx.profile.name}

    def _send_common(args: dict, tool: str, in_reply_to: str | None = None) -> dict:
        ctx.require(tool)
        to = args.get("to") or []
        if isinstance(to, str):
            to = [to]
        if not to:
            raise MailMCPError(E_INVALID_ARGUMENT, "to 不能为空")
        subject = _need(args, "subject", str)
        body = _need(args, "body", str)
        if len(to) > ctx.policy.limits.max_recipients_per_send:
            raise MailMCPError(
                E_INVALID_ARGUMENT,
                f"收件人数 {len(to)} 超出限制 {ctx.policy.limits.max_recipients_per_send}",
            )

        decision = evaluate_policy(
            ctx.policy,
            sender=to[0],
            subject=subject,
            auth=None,
            first_contact=False,
        )
        gate = evaluate_send_gate(
            GateInput(
                profile_allows=ctx.profile.allows_write,
                policy=decision,
                recipients=to,
                allowlist=ctx.policy.allowlist_set(),
                allowlist_domains=ctx.policy.domain_set(),
                content_flags=list(args.get("content_flags") or []),
                quota_ok=True,
                rate_ok=True,
                tainted=bool(args.get("tainted", False)),
                loop_reasons=list(args.get("loop_reasons") or []),
                confirmed=bool(args.get("confirmed", False)),
            )
        )
        ctx.audit.write(
            {
                "op": tool,
                "recipients": to,
                "gate": gate.gate,
                "decision": gate.decision,
                "reasons": gate.reasons,
            }
        )
        if not gate.allowed:
            raise MailMCPError(
                "E_NEED_CONFIRM" if gate.decision == "confirm" else "E_POLICY_DENIED",
                f"闸门拦截({gate.gate})，未发送",
                gate.to_dict(),
            )
        mid = ctx.adapter.send(to=to, subject=subject, body=body, in_reply_to=in_reply_to)
        return {"sent": True, "message_id": mid, "gate": gate.to_dict()}

    def send_message(args: dict) -> dict:
        return _send_common(args, "send_message")

    def reply_message(args: dict) -> dict:
        mid = _need(args, "message_id", str)
        return _send_common(args, "reply_message", in_reply_to=mid)

    def forward_message(args: dict) -> dict:
        return _send_common(args, "forward_message")

    def mark_message(args: dict) -> dict:
        ctx.require("mark_message")
        return {"ok": True, "note": "flags 写入待适配器实现"}

    def move_message(args: dict) -> dict:
        ctx.require("move_message")
        raise MailMCPError("E_PROVIDER_UNSUPPORTED", "IMAP MOVE 需服务端支持 MOVE 扩展，当前未启用")

    def delete_message(args: dict) -> dict:
        ctx.require("delete_message")
        if "delete_message" not in ctx.profile.registered(enable_delete=True):
            raise MailMCPError(E_PROFILE_DENIED, "删除工具需 danger profile 且 --enable-delete")
        raise MailMCPError("E_PROVIDER_UNSUPPORTED", "删除需两段式确认，实现中")

    def purge_messages(args: dict) -> dict:
        ctx.require("purge_messages")
        raise MailMCPError(E_PROFILE_DENIED, "批量清除默认禁用")

    return {
        "list_mailboxes": list_mailboxes,
        "list_messages": list_messages,
        "search_messages": search_messages,
        "get_message": get_message,
        "get_thread": get_thread,
        "get_attachment": get_attachment,
        "get_quota": get_quota,
        "get_me": get_me,
        "send_message": send_message,
        "reply_message": reply_message,
        "forward_message": forward_message,
        "mark_message": mark_message,
        "move_message": move_message,
        "delete_message": delete_message,
        "purge_messages": purge_messages,
    }
