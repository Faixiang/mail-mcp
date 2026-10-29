# 按 provider 构建适配器。凭据从环境变量读取，不落配置文件。
from __future__ import annotations

import os

from ..errors import E_AUTH_MISSING, E_PROVIDER_UNSUPPORTED, MailMCPError


def build_adapter(provider: str, account: str):
    provider = (provider or "").strip().lower()
    if provider in ("imap", "imap_smtp", "qq", "163", "gmail_imap"):
        from .imap_smtp import ImapCredentials, ImapSmtpAdapter

        pwd = os.environ.get("MAIL_MCP_PASSWORD")
        if not pwd:
            raise MailMCPError(
                E_AUTH_MISSING,
                "缺少 MAIL_MCP_PASSWORD 环境变量",
                {"hint": "请使用应用专用密码，切勿使用主账号密码"},
            )
        return ImapSmtpAdapter(
            ImapCredentials(
                address=account,
                password=pwd,
                imap_host=os.environ.get("MAIL_MCP_IMAP_HOST", ""),
                smtp_host=os.environ.get("MAIL_MCP_SMTP_HOST", ""),
            )
        )
    if provider in ("gmail", "graph", "outlook", "qq_official"):
        raise MailMCPError(
            E_PROVIDER_UNSUPPORTED,
            f"{provider} 适配器尚未实现，当前可用: imap_smtp",
            {"roadmap": "见 README 状态表"},
        )
    raise MailMCPError(E_PROVIDER_UNSUPPORTED, f"未知 provider: {provider}")
