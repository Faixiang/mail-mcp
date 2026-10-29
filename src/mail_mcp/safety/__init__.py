# 安全层：消毒 / taint / 闸门 / 审计。
# 约束：本包不做网络与凭据访问，全部可在无 IO 条件下单测。
from .sanitize import sanitize_body, strip_quoted, html_to_text
from .taint import detect_injection
from .gates import evaluate_send_gate, GateInput

__all__ = [
    "sanitize_body",
    "strip_quoted",
    "html_to_text",
    "detect_injection",
    "evaluate_send_gate",
    "GateInput",
]
