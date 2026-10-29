# 运行时配置解析。凭据只从环境或 keystore 读，绝不写进仓库与日志。
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_HOME = os.path.join(os.path.expanduser("~"), ".mail-mcp")


@dataclass
class RuntimeConfig:
    profile: str = "reader"
    account: str = ""
    home: str = DEFAULT_HOME
    enable_delete: bool = False
    policy_path: str = ""
    provider: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def state_dir(self) -> str:
        return os.path.join(self.home, "state")

    @property
    def sandbox_dir(self) -> str:
        return os.path.join(self.home, "sandbox")

    def ensure_dirs(self) -> None:
        for d in (self.home, self.state_dir, self.sandbox_dir):
            os.makedirs(d, exist_ok=True)


def default_policy_path(home: str = DEFAULT_HOME) -> str:
    return os.path.join(home, "policy.yaml")


def parse_argv(argv: list[str]) -> RuntimeConfig:
    # 手写极简解析，避免引入 click 依赖
    cfg = RuntimeConfig()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--profile" and i + 1 < len(argv):
            cfg.profile = argv[i + 1]
            i += 2
        elif a == "--account" and i + 1 < len(argv):
            cfg.account = argv[i + 1]
            i += 2
        elif a == "--home" and i + 1 < len(argv):
            cfg.home = argv[i + 1]
            i += 2
        elif a == "--policy" and i + 1 < len(argv):
            cfg.policy_path = argv[i + 1]
            i += 2
        elif a == "--provider" and i + 1 < len(argv):
            cfg.provider = argv[i + 1]
            i += 2
        elif a == "--enable-delete":
            cfg.enable_delete = True
            i += 1
        elif a in ("-h", "--help"):
            cfg.extra["help"] = True
            i += 1
        else:
            i += 1
    if not cfg.policy_path:
        cfg.policy_path = default_policy_path(cfg.home)
    return cfg
