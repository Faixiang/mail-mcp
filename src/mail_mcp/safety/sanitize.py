# 入站内容消毒。原则：白名单保留语义，宁丢格式不漏内容。
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

# 引用段起始标记，命中即从此处截断
_QUOTE_MARKERS = [
    r"-{2,}\s*Original\s*Message\s*-{0,}",
    r"-{2,}\s*(原始|转发)\s*邮件\s*-{0,}",
    r"On .{0,120}wrote:",
    r"在\s*20\d{2}.{0,80}写道[：:]",
    r"发件人[：:].{0,200}发送时间[：:]",
    r"From:\s.{0,200}\nSent:",
]
_QUOTE_RE = re.compile("|".join(_QUOTE_MARKERS), re.IGNORECASE)

# 零宽与双向控制符
_INVISIBLE_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")

# 隐藏文本块：样式含 display:none / visibility:hidden / font-size:0
_HIDDEN_BLOCK_RE = re.compile(
    r"<(div|span|p|td|font)[^>]*style\s*=\s*[\"'][^\"']*"
    r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*[01]px|"
    r"color\s*:\s*#?fff(?:fff)?|height\s*:\s*0|width\s*:\s*0)[^\"']*[\"'][^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|head)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)

# 允许保留的标签，其余剥掉但保留文字
_ALLOWED_TAGS = {"p", "br", "div", "li", "ul", "ol", "table", "tr", "td", "th", "strong", "em", "b", "i"}
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_BLOCK_RE = re.compile(r"</\s*(p|div|li|tr|h[1-6])\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

# 超链接：把真实 href 附在文本后，避免显示文本伪装
_LINK_RE = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)


@dataclass
class SanitizeReport:
    quoted_stripped: bool = False
    hidden_blocks_removed: int = 0
    links_rewritten: int = 0
    invisible_chars_removed: int = 0
    truncated: bool = False
    flags: list[str] = field(default_factory=list)


def strip_quoted(text: str) -> tuple[str, bool]:
    # 截断引用段，并丢弃以 > 开头的引用行。返回 (新写正文, 是否剥离过)
    if not text:
        return "", False
    stripped = False
    m = _QUOTE_RE.search(text)
    if m and m.start() > 0:
        text = text[: m.start()]
        stripped = True
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            stripped = True
            continue
        lines.append(line)
    out = "\n".join(lines).strip()
    if not out and stripped:
        return "", True
    return out, stripped


def html_to_text(raw: str) -> tuple[str, SanitizeReport]:
    # HTML -> 纯文本，白名单化。返回 (text, report)
    rep = SanitizeReport()
    if not raw:
        return "", rep

    raw = _COMMENT_RE.sub("", raw)
    raw, n = _HIDDEN_BLOCK_RE.subn("", raw)
    rep.hidden_blocks_removed = n
    raw = _SCRIPT_STYLE_RE.sub("", raw)

    def _link_sub(m: re.Match) -> str:
        href, inner = m.group(1), m.group(2)
        rep.links_rewritten += 1
        label = _TAG_RE.sub("", inner).strip()
        return f"{label} [href: {href}]" if label else f"[href: {href}]"

    raw = _LINK_RE.sub(_link_sub, raw)
    raw = _BR_RE.sub("\n", raw)
    raw = _BLOCK_RE.sub("\n", raw)
    raw = _TAG_RE.sub("", raw)
    raw = html.unescape(raw)

    before = len(raw)
    raw = _INVISIBLE_RE.sub("", raw)
    rep.invisible_chars_removed = before - len(raw)

    lines = [ln.rstrip() for ln in raw.splitlines()]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, rep


def sanitize_body(
    plain: str | None,
    html_part: str | None,
    max_chars: int = 20000,
) -> tuple[str, SanitizeReport]:
    # 优先用 plain，缺失才回退到 html
    rep = SanitizeReport()
    if plain and plain.strip():
        text = plain
        if "\u200b" in text or _INVISIBLE_RE.search(text):
            before = len(text)
            text = _INVISIBLE_RE.sub("", text)
            rep.invisible_chars_removed = before - len(text)
    elif html_part:
        text, rep = html_to_text(html_part)
    else:
        return "", rep

    text, stripped = strip_quoted(text)
    rep.quoted_stripped = stripped

    if len(text) > max_chars:
        text = text[:max_chars]
        rep.truncated = True
        rep.flags.append("truncated")

    return text, rep
