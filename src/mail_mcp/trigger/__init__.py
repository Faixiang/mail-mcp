# 触发层：把"邮箱有新信"变成"Agent 被唤醒"。
# 刻意与 MCP 能力层分离——本包不 import mcp SDK，也不含任何模型逻辑。
from .contracts import MailEvent, make_event_id
from .bus import EventBus
from .consumer import Consumer, DeliveryResult, SubprocessConsumer

__all__ = [
    "MailEvent",
    "make_event_id",
    "EventBus",
    "Consumer",
    "DeliveryResult",
    "SubprocessConsumer",
]
