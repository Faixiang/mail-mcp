# 审计落库。只记元数据，不记正文与 token。
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

AUDIT_DIR_NAME = "audit"


class AuditLog:
    def __init__(self, base_dir: str) -> None:
        self.dir = os.path.join(base_dir, AUDIT_DIR_NAME)
        os.makedirs(self.dir, exist_ok=True)

    def _path(self) -> str:
        # 按日切分，便于轮转与保留期管理
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return os.path.join(self.dir, f"audit-{day}.jsonl")

    def write(self, record: dict[str, Any]) -> None:
        safe = dict(record)
        # 防御性剔除：任何字段名含这些词的都不落盘
        for k in list(safe):
            lk = k.lower()
            if any(t in lk for t in ("body", "token", "secret", "password", "credential")):
                safe.pop(k, None)
        safe.setdefault("ts", datetime.now(timezone.utc).isoformat())
        with open(self._path(), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(safe, ensure_ascii=False) + "\n")
