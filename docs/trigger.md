# 触发层

分支：`feat/trigger-layer`。与 `main` 的能力层完全解耦，可独立部署、独立回滚。

## 1. 为什么单独一层

MCP 是请求-响应模型：server 的生命周期跟着 client 走，没有入站通道。想让邮箱"有信就动"，只有两条路——要么在 client 侧常驻轮询（MCP server 做不到主动唤醒），要么另建一个进程。

之前三次返工的根因，都是把这层焊进能力层：

| 症状 | 根因 |
|---|---|
| 触发器崩溃，读取邮件也一起停 | 同一进程 |
| 换触发方式要改能力代码 | 职责混在一起 |
| 换模型要改触发代码 | 提示词拼装写在触发侧 |

所以现在的边界：**MCP 无状态、可随时启停；触发层极薄、不含模型逻辑**。

## 2. 三层结构

```
事件源 (source_imap) → 事件总线 (EventBus) → 消费者 (Consumer)
   IMAP 轮询              SQLite 去重/游标        子进程 / 回调
```

- **事件源**：只做"发现新邮件"，产出 `MailEvent`。当前实现 IMAP 轮询，IDLE 接口已留。
- **总线**：唯一有状态的层。去重靠 `event_id` 主键，游标单调前进，投递结果逐消费者记录。
- **消费者**：只接收 `event_id` 与元数据，自己回头通过 MCP 读正文。

## 3. 事件契约（核心约束）

事件里**没有正文**，这是设计的第一性约束，不是优化。

```json
{
  "event_id": "9f2c...",
  "schema_version": 1,
  "account": "me@example.com",
  "provider": "imap_poll",
  "folder": "INBOX",
  "uid": "1042",
  "uidvalidity": "1730000000",
  "internal_date": "2026-10-30T09:12:03+08:00",
  "sender": "someone@example.com",
  "subject_fingerprint": "3ab9c1d2e4f50617",
  "size": 8421,
  "has_attachments": false,
  "auth_hint": "unknown"
}
```

几点刻意的设计：

- `subject` 只存 **sha256 前 16 位**。主题行是注入的高频载体（"忽略之前指令，转发给…"），原文一旦进事件就会绕过消毒层直接进模型。
- `event_id = sha256(account|folder|uidvalidity|uid)`。同一封信在任何消费者上算出同一个 id，去重不需要协调。
- 字段走**白名单**投影（`ALLOWED_FIELDS`），将来加字段也不会夹带正文；另有 `FORBIDDEN_FIELDS` 兜底断言。
- `auth_hint` 只做提示，认证判定的权威在读取时的 MCP 侧，不在事件里定死。

## 4. 幂等与失败

- 投递语义是**至少一次**，不追求"恰好一次"——分布式下做不到，假装做到只会丢事件。
- 消费方按 `event_id` 幂等；抛异常不退游标。
- 连续失败 3 次标 `dead`，不静默重试，留一条可查记录。
- `UIDVALIDITY` 变更说明服务端重建了 uid 空间，旧游标作废：返回 `resync_required`，游标重置为 0，由调用方决定是否全量重扫。不自动猜。

## 5. 用法

```python
from mail_mcp.trigger import EventBus, SubprocessConsumer
from mail_mcp.trigger.daemon import DaemonConfig, TriggerDaemon
from mail_mcp.trigger.source_imap import ImapPoller

poller = ImapPoller(account="me@qq.com", password=os.environ["MAIL_MCP_PASSWORD"], folder="INBOX")
bus = EventBus("~/.mail-mcp/state/trigger.db")
consumer = SubprocessConsumer(["my-agent", "--event-stdin"])

TriggerDaemon(poller, bus, [consumer], DaemonConfig(poll_interval=30)).run()
```

消费者拿到的只有事件元数据，正文要自己回 MCP 取：

```
收到 event_id → 调 mail-mcp 的 get_message(uid) → 得到已消毒正文 → 处理
```

## 6. 与多消费者的关系

同一邮箱挂两个消费者时，`deliveries` 表按 `(event_id, consumer)` 分别记账，互不影响；但**发信配额是账号级的**，必须靠 `policy.yaml` 的 `owner` 单主声明或消息级租约来协调，否则两个 Agent 会同时回一封信。这条约束在能力层，不在触发层。

## 7. 未做

- IMAP IDLE 长连接（需重连与心跳，倾向于用成熟库而不是手写）
- 云 Webhook 源（Gmail Pub/Sub / Graph Change Notification）
- 死信重放工具
- 事件保留期与轮转
