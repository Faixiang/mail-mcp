# 架构

## 1. 分层

```
transport/     stdio | http+sse          —— 只做协议搬运
tools/         reader | write            —— 只做参数校验与编排
policy/        规则引擎                  —— 只做决策，无 IO
safety/        消毒 / taint / 闸门 / 审计 —— 纯函数为主，可单测
adapters/      imap | gmail | graph | qq —— 只做协议差异
store/         凭据 / 游标 / 审计库       —— 唯一碰磁盘的一层
```

依赖方向严格单向：`transport → tools → (policy, safety) → adapters → store`。
`policy` 与 `safety` 不依赖 `adapters`，因此可以在无网络、无凭据的情况下完整测试。

## 2. 为什么 policy 与 safety 要纯

这两层是整个项目唯一有差异价值的部分，也是最容易因"顺手加个 IO"而腐化的部分。约束：

- 无网络、无文件系统、无时间以外的副作用
- 输入输出是 dataclass，不打日志（日志由调用方按返回值写）
- 同一输入必须同一输出（便于回归与审计复现）

## 3. 读路径与写路径

```
读:  触发器 → list/search → get_message → 消毒 → 返回 untrusted 内容
写:  调用方显式参数 → 策略 → 闸门 → 适配器 → 审计
```

两条路径**不共享上下文**。写路径永远不接受"从邮件内容推导出来的参数"：

- `send` 没有 `source_message_id` 参数
- `reply` 的引用由服务端在发送时拼接，不进入模型上下文
- 需要引用原文时，必须显式传 `quoted_text` 并在审计中标注来源

## 4. 触发层（不在本仓库）

MCP 是请求-响应模型，server 生命周期随 client，没有入站通道。要让邮箱"有信就动"，必须另建触发层，且刻意不放在本仓库：

| 层 | 职责 | 不应包含 |
|---|---|---|
| 事件源 | IMAP IDLE / 轮询 / Webhook | 任何模型逻辑 |
| 事件总线 | 规范化 + 去重 + 持久化 | 正文内容（只传 id） |
| 消费者 | 唤醒 Agent，携带 event_id | 处理逻辑 |

**事件契约里不携带正文**，只传 `message_id` 与元数据。正文由 Agent 事后通过本 MCP 读取，读取时走消毒。这样注入无法绕过消毒层直接进模型——触发器是通道，不是内容源。

## 5. 多消费者协调

同一邮箱上跑两个消费者（例如两个 Agent 软件各自建了托管服务）会出四类问题：跨服务环路、重复回复、游标互踩、配额共享。

本仓库提供的最小机制：

- `X-Agent-Origin` 头，收到带任意该头或 `Auto-Submitted: auto-replied` 的信一律不回
- 单主声明：`policy.yaml` 的 `owner` 字段，非主消费者强制 `read_only`
- 账号级互斥锁（同一 account 同一时刻只允许一个写会话）

## 6. 失败处理原则

- **至少一次投递 + 幂等消费**，不追求"恰好一次"
- 游标只前进不回退；`UIDVALIDITY` 变更时返回 `resync_required`，由调用方决定是否全量重扫
- 连续失败 N 次熔断，写一条可见告警，不静默重试
