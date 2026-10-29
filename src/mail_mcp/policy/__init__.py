# 策略层：确定性规则引擎。无 IO、无网络，同一输入必同一输出。
from .schema import PolicyConfig, Rule, load_policy
from .engine import evaluate

__all__ = ["PolicyConfig", "Rule", "load_policy", "evaluate"]
