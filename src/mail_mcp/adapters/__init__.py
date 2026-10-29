# 适配器层：吸收各家协议差异，对外只暴露统一接口。
from .base import Adapter, Capabilities
from .registry import build_adapter

__all__ = ["Adapter", "Capabilities", "build_adapter"]
