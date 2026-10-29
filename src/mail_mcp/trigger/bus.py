# 事件总线。职责只有三件：去重、持久化、记录投递结果。
# 用 SQLite 单文件，不引外部依赖——这一层宁可笨，也不能丢事件。
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from .contracts import Cursor, MailEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    account      TEXT NOT NULL,
    folder       TEXT NOT NULL,
    uid          TEXT NOT NULL,
    payload      TEXT NOT NULL,
    ingested_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_account_folder ON events(account, folder, uid);

CREATE TABLE IF NOT EXISTS cursors (
    account      TEXT NOT NULL,
    folder       TEXT NOT NULL,
    uidvalidity  TEXT NOT NULL,
    last_uid     TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (account, folder)
);

CREATE TABLE IF NOT EXISTS deliveries (
    event_id     TEXT NOT NULL,
    consumer     TEXT NOT NULL,
    status       TEXT NOT NULL,
    detail       TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (event_id, consumer)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventBus:
    def __init__(self, db_path: str) -> None:
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- 入站 ----
    def ingest(self, event: MailEvent) -> bool:
        # 返回 True 表示新事件；False 表示重复（幂等键命中）
        try:
            self.conn.execute(
                "INSERT INTO events(event_id, account, folder, uid, payload, ingested_at) VALUES (?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.account,
                    event.folder,
                    event.uid,
                    json.dumps(event.to_dict(), ensure_ascii=False),
                    _now(),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get(self, event_id: str) -> MailEvent | None:
        row = self.conn.execute("SELECT payload FROM events WHERE event_id=?", (event_id,)).fetchone()
        return MailEvent.from_dict(json.loads(row[0])) if row else None

    def pending(self, consumer: str, limit: int = 50) -> list[MailEvent]:
        # 未被该消费者成功投递的事件，按入站顺序
        rows = self.conn.execute(
            """
            SELECT e.payload FROM events e
            LEFT JOIN deliveries d
              ON d.event_id = e.event_id AND d.consumer = ? AND d.status = 'ok'
            WHERE d.event_id IS NULL
            ORDER BY e.ingested_at ASC
            LIMIT ?
            """,
            (consumer, limit),
        ).fetchall()
        return [MailEvent.from_dict(json.loads(r[0])) for r in rows]

    # ---- 投递结果 ----
    def mark(self, event_id: str, consumer: str, status: str, detail: dict | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO deliveries(event_id, consumer, status, detail, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(event_id, consumer) DO UPDATE SET
                status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at
            """,
            (event_id, consumer, status, json.dumps(detail or {}, ensure_ascii=False), _now()),
        )
        self.conn.commit()

    def attempt_count(self, event_id: str, consumer: str) -> int:
        row = self.conn.execute(
            "SELECT status, detail FROM deliveries WHERE event_id=? AND consumer=?", (event_id, consumer)
        ).fetchone()
        if not row:
            return 0
        status, detail = row
        if status == "dead":
            # 已判死的事件不再参与重试
            return 1_000_000
        try:
            return int(json.loads(detail or "{}").get("attempts", 1))
        except Exception:
            return 1

    # ---- 游标 ----
    def get_cursor(self, account: str, folder: str) -> Cursor | None:
        row = self.conn.execute(
            "SELECT account, folder, uidvalidity, last_uid, updated_at FROM cursors WHERE account=? AND folder=?",
            (account, folder),
        ).fetchone()
        return Cursor(*row) if row else None

    def set_cursor(self, account: str, folder: str, uidvalidity: str, last_uid: str) -> None:
        # 单调前进：新 uid 不大于旧 uid 时忽略，防止事件乱序导致回退
        old = self.get_cursor(account, folder)
        if old and old.uidvalidity == uidvalidity:
            try:
                if int(last_uid) <= int(old.last_uid):
                    return
            except ValueError:
                pass
        self.conn.execute(
            """
            INSERT INTO cursors(account, folder, uidvalidity, last_uid, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(account, folder) DO UPDATE SET
                uidvalidity=excluded.uidvalidity, last_uid=excluded.last_uid, updated_at=excluded.updated_at
            """,
            (account, folder, uidvalidity, last_uid, _now()),
        )
        self.conn.commit()
