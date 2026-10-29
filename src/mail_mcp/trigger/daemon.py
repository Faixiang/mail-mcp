# 主循环：拉事件 → 入总线 → 投递 → 前进游标。
# 刻意做得笨：宁可重复投递（消费方幂等），也不丢事件。
from __future__ import annotations

import time
from dataclasses import dataclass

from .bus import EventBus
from .consumer import Consumer
from .source_imap import ImapPoller

MAX_ATTEMPTS = 3


@dataclass
class DaemonConfig:
    poll_interval: float = 30.0
    batch_size: int = 50
    once: bool = False


class TriggerDaemon:
    def __init__(
        self,
        poller: ImapPoller,
        bus: EventBus,
        consumers: list[Consumer],
        cfg: DaemonConfig | None = None,
    ) -> None:
        self.poller = poller
        self.bus = bus
        self.consumers = consumers
        self.cfg = cfg or DaemonConfig()

    def poll_once(self) -> int:
        cur = self.bus.get_cursor(self.poller.account, self.poller.folder)
        res = self.poller.poll(
            last_uid=cur.last_uid if cur else None,
            uidvalidity=cur.uidvalidity if cur else None,
            limit=self.cfg.batch_size,
        )

        if res.resync_required:
            # 不猜、不删、不重扫：交给调用方决定，这里只重置游标起点
            self.bus.set_cursor(self.poller.account, self.poller.folder, res.uidvalidity, "0")
            return 0

        fresh = 0
        for ev in res.events:
            if self.bus.ingest(ev):
                fresh += 1

        self._deliver()
        self.bus.set_cursor(self.poller.account, self.poller.folder, res.uidvalidity, res.last_uid)
        return fresh

    def _deliver(self) -> None:
        for c in self.consumers:
            for ev in self.bus.pending(c.name, limit=self.cfg.batch_size):
                attempts = self.bus.attempt_count(ev.event_id, c.name)
                if attempts >= MAX_ATTEMPTS:
                    self.bus.mark(ev.event_id, c.name, "dead", {"reason": "max attempts", "attempts": attempts})
                    continue
                result = c.dispatch(ev)
                if result.delivered:
                    self.bus.mark(ev.event_id, c.name, "ok", result.detail)
                else:
                    self.bus.mark(
                        ev.event_id,
                        c.name,
                        "failed",
                        {"attempts": attempts + 1, "error": result.error, **result.detail},
                    )

    def run(self) -> None:
        while True:
            try:
                self.poll_once()
            except Exception as e:
                # 单次失败不退出：网络抖动不该让服务停掉
                print(f"[trigger] poll failed: {type(e).__name__}: {e}")
            if self.cfg.once:
                return
            time.sleep(self.cfg.poll_interval)
