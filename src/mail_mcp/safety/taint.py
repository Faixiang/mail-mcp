# 注入识别。只做标记不做裁决：命中后由闸门与调用方决定降级方式。
from __future__ import annotations

import re

# 指令性语句：命中即 taint。宁可误报，不可漏报。
_PATTERNS: list[tuple[str, str]] = [
    (r"\bignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", "ignore_previous"),
    (r"忽略(以上|之前|前述|上面).{0,12}(指令|要求|提示)", "ignore_previous_zh"),
    (r"\bsystem\s*prompt\b", "system_prompt_ref"),
    (r"系统提示词|系统指令", "system_prompt_ref_zh"),
    (r"你现在是|从现在开始你是|扮演一个", "role_override_zh"),
    (r"\byou\s+are\s+now\b|\bact\s+as\b.{0,40}\badmin", "role_override"),
    (r"执行以下(操作|指令|步骤)", "directive_zh"),
    (r"请(立即|马上|尽快)?(转发|回复|发送)给.{0,40}@", "forward_directive_zh"),
    (r"\b(forward|send|reply)\b.{0,30}\bto\b.{0,30}@", "forward_directive"),
    (r"不要(告诉|通知|告知)(用户|老板|我)", "concealment"),
    (r"\bdo\s+not\s+(tell|inform|notify)\b", "concealment_en"),
    (r"<(important|admin|system|assistant)>", "fake_role_tag"),
    (r"\[/?INST\]|<<SYS>>", "llm_control_token"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), name) for p, name in _PATTERNS]


def detect_injection(text: str) -> list[str]:
    # 返回命中的规则名列表，空列表表示未命中
    if not text:
        return []
    hits: list[str] = []
    for rx, name in _COMPILED:
        if rx.search(text):
            hits.append(name)
    return hits
