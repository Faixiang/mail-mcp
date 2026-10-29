# MCP 入口。在此处按 profile 决定注册哪些工具——未注册即模型不可见。
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from .config import RuntimeConfig, parse_argv
from .errors import MailMCPError
from .policy.schema import load_policy
from .profiles import get_profile
from .safety.audit import AuditLog

# 工具 schema 集中声明，注册与 schema 同源，避免漂移
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_mailboxes": {
        "description": "列出账号下的邮件夹",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "list_messages": {
        "description": "按邮件夹列出邮件摘要，不返回正文",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "default": "INBOX"},
                "limit": {"type": "integer", "default": 20, "maximum": 100},
                "unread_only": {"type": "boolean", "default": False},
            },
        },
    },
    "search_messages": {
        "description": "服务端搜索邮件，返回 message_id 列表",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "folder": {"type": "string", "default": "INBOX"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    "get_message": {
        "description": "读取单封邮件。返回内容标记为 untrusted，引用段已剥离，注入特征已标 tainted",
        "inputSchema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}, "folder": {"type": "string"}},
            "required": ["message_id"],
        },
    },
    "get_thread": {
        "description": "读取整个会话",
        "inputSchema": {
            "type": "object",
            "properties": {"thread_id": {"type": "string"}},
            "required": ["thread_id"],
        },
    },
    "get_attachment": {
        "description": "下载附件到沙箱目录，返回本地路径。不把二进制内容放进上下文",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
                "attachment_id": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 10485760},
            },
            "required": ["message_id", "attachment_id"],
        },
    },
    "get_quota": {
        "description": "查询配额，IMAP 下多为不可用",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "get_me": {
        "description": "返回当前账号与 profile",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "send_message": {
        "description": "发送新邮件。经策略与闸门，未命中白名单或未确认会被拦截。注意：本工具不接受 source_message_id——内容必须来自调用方，不得直接转发邮件正文",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "array", "items": {"type": "string"}},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
                "content_flags": {"type": "array", "items": {"type": "string"}},
                "tainted": {"type": "boolean", "default": False},
            },
            "required": ["to", "subject", "body"],
        },
    },
    "reply_message": {
        "description": "回复指定邮件。引用原文由服务端拼接，不需要也不接受 quoted_text 以外的正文参数",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
                "to": {"type": "array", "items": {"type": "string"}},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
            "required": ["message_id", "to", "subject", "body"],
        },
    },
    "forward_message": {
        "description": "转发邮件，需显式收件人",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "array", "items": {"type": "string"}},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "confirmed": {"type": "boolean", "default": False},
            },
            "required": ["to", "subject", "body"],
        },
    },
    "mark_message": {
        "description": "修改已读/星标等标记",
        "inputSchema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}, "flags": {"type": "array", "items": {"type": "string"}}},
            "required": ["message_id"],
        },
    },
    "move_message": {
        "description": "移动邮件到指定文件夹",
        "inputSchema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}, "folder": {"type": "string"}},
            "required": ["message_id", "folder"],
        },
    },
    "delete_message": {
        "description": "删除单封邮件。默认不注册，需 danger profile + --enable-delete，且需两段式确认",
        "inputSchema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}, "confirmed": {"type": "boolean", "default": False}},
            "required": ["message_id"],
        },
    },
    "purge_messages": {
        "description": "批量清除。默认禁用",
        "inputSchema": {
            "type": "object",
            "properties": {"folder": {"type": "string"}, "confirmed": {"type": "boolean", "default": False}},
        },
    },
}

HELP = """
mail-mcp — unified multi-provider email MCP server

用法:
  mail-mcp --profile reader --provider imap --account you@qq.com
  mail-mcp --profile full   --provider imap --account you@qq.com --policy ~/.mail-mcp/policy.yaml

参数:
  --profile   reader | full | danger   默认 reader
  --account   邮箱地址
  --provider  imap | gmail | graph | qq_official   默认 imap
  --home      状态目录，默认 ~/.mail-mcp
  --policy    策略文件路径
  --enable-delete  在 danger profile 下启用删除工具

环境变量:
  MAIL_MCP_PASSWORD     应用专用密码（必填）
  MAIL_MCP_IMAP_HOST    自定义 IMAP 主机
  MAIL_MCP_SMTP_HOST    自定义 SMTP 主机
"""


def _load_policy_file(path: str):
    import yaml

    try:
        with open(path, encoding="utf-8") as f:
            return load_policy(yaml.safe_load(f) or {})
    except FileNotFoundError:
        return load_policy({})


async def serve(cfg: RuntimeConfig) -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    from .adapters.registry import build_adapter
    from .tools.handlers import HandlerContext, build_handlers

    from dataclasses import replace

    profile = replace(get_profile(cfg.profile), account=cfg.account)
    cfg.ensure_dirs()
    policy = _load_policy_file(cfg.policy_path)
    adapter = build_adapter(cfg.provider or "imap", cfg.account)
    audit = AuditLog(cfg.home)

    registered = profile.registered(enable_delete=cfg.enable_delete)
    ctx = HandlerContext(profile=profile, policy=policy, adapter=adapter, audit=audit)
    handlers = build_handlers(ctx)

    app = Server("mail-mcp")

    @app.list_tools()
    async def list_tools():
        return [
            Tool(name=n, description=TOOL_SCHEMAS[n]["description"], inputSchema=TOOL_SCHEMAS[n]["inputSchema"])
            for n in registered
            if n in TOOL_SCHEMAS
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name not in registered:
            err = MailMCPError("E_PROFILE_DENIED", f"{name} 未在 profile {profile.name} 中注册")
            return [TextContent(type="text", text=json.dumps(err.to_dict(), ensure_ascii=False))]
        try:
            result = handlers[name](arguments or {})
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
        except MailMCPError as e:
            return [TextContent(type="text", text=json.dumps(e.to_dict(), ensure_ascii=False))]
        except Exception as e:  # 兜底，避免把栈暴露给模型
            audit.write({"op": name, "error": type(e).__name__})
            return [TextContent(type="text", text=json.dumps({"code": "E_INTERNAL", "message": str(e)}, ensure_ascii=False))]

    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


def main() -> None:
    cfg = parse_argv(sys.argv[1:])
    if cfg.extra.get("help"):
        print(HELP)
        return
    asyncio.run(serve(cfg))


if __name__ == "__main__":
    main()
