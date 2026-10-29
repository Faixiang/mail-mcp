# 消费者。极薄：只负责把 event_id 交出去，不解释邮件、不拼提示词。
# 想换成别的 Agent 框架，实现 Consumer 协议即可，触发层不用改。
from __future__ import annotations

import json
import subprocess
import sys
from typing import Protocol

from .contracts import DeliveryResult, MailEvent


class Consumer(Protocol):
    name: str

    def dispatch(self, event: MailEvent) -> DeliveryResult: ...


class SubprocessConsumer:
    # 通过子进程唤醒 Agent。事件 JSON 从 stdin 进去，正文永远不在这里
    name = "subprocess"

    def __init__(self, command: list[str], timeout: int = 120, env: dict | None = None) -> None:
        if not command:
            raise ValueError("command 不能为空")
        self.command = command
        self.timeout = timeout
        self.env = env or {}

    def dispatch(self, event: MailEvent) -> DeliveryResult:
        payload = json.dumps(event.to_dict(), ensure_ascii=False)
        import os

        env = dict(os.environ)
        env.update({k: str(v) for k, v in self.env.items()})
        env["MAIL_MCP_EVENT_ID"] = event.event_id
        try:
            proc = subprocess.run(
                self.command,
                input=payload,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return DeliveryResult(False, self.name, {"timeout": self.timeout}, error="timeout")
        if proc.returncode != 0:
            return DeliveryResult(
                False,
                self.name,
                {"returncode": proc.returncode, "stderr_tail": (proc.stderr or "")[-500:]},
                error="nonzero_exit",
            )
        return DeliveryResult(True, self.name, {"stdout_tail": (proc.stdout or "")[-500:]})


class CallbackConsumer:
    # 进程内回调，便于测试与嵌入现有调度器
    name = "callback"

    def __init__(self, fn, name: str = "callback") -> None:
        self.fn = fn
        self.name = name

    def dispatch(self, event: MailEvent) -> DeliveryResult:
        try:
            self.fn(event)
            return DeliveryResult(True, self.name, {})
        except Exception as e:
            return DeliveryResult(False, self.name, {}, error=f"{type(e).__name__}: {e}")


class LoggingConsumer:
    # 只打印事件元数据，用于联调确认"确实有信、但没拿到正文"
    name = "logging"

    def dispatch(self, event: MailEvent) -> DeliveryResult:
        print(json.dumps(event.to_dict(), ensure_ascii=False), file=sys.stdout, flush=True)
        return DeliveryResult(True, self.name, {})
