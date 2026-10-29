# 邮件 MCP · Profile 与工具接口规格 v1

定位：多邮箱统一适配层。本文件定义 `reader` 与 `full` 两套 profile 的工具清单、数据契约、闸门语义。

---

## 0. 设计原则

1. **结构性隔离优先于运行时拒绝**：`reader` profile 下写工具**不注册**，而非注册后拒绝调用。工具不存在，模型无法编造调用。
2. **工具不接受"从邮件内容推导出的参数"**：写工具的正文、收件人必须由调用方显式给出，禁止传 `message_id` 让服务端自动取正文。
3. **所有入站内容标 `trust: untrusted`**：消毒在服务端完成，客户端拿到的即为消毒后文本。
4. **策略评估确定性**：判定由代码执行，模型只能读解释，不能改判定。
5. **幂等**：写工具全部接受 `idempotency_key`，同键重复调用返回首次结果。

---

## 1. Profile 定义

| profile | 工具数 | 写能力 | 用途 |
|---|---|---|---|
| `reader` | 8 | 无 | 默认值，可公开分发、只读会话 |
| `full` | 15 | 有（含 destructive 子开关） | 需显式开启 + 配置策略 |

启动方式：

```bash
mail-mcp --profile reader
mail-mcp --profile full --enable-delete=false
```

`initialize` 返回的 `instructions` 必须写明当前 profile 与禁用的工具，避免模型臆测。

---

## 2. 工具清单

### 2.1 reader（8）

| 工具 | 作用 | 只读 |
|---|---|---|
| `mail_get_profile` | 账号、后端类型、scope、配额余量、能力限制 | 是 |
| `mail_list_folders` | 文件夹/标签列表（含系统文件夹映射） | 是 |
| `mail_list_messages` | 按文件夹列信，游标分页 | 是 |
| `mail_search_messages` | 结构化搜索 | 是 |
| `mail_get_message` | 读单封（消毒后正文 + 认证结果 + taint 标记） | 是 |
| `mail_get_thread` | 读会话串（剥离引用，按时间排序） | 是 |
| `mail_get_attachment` | 下载附件到沙箱，返回本地路径 | 是（落盘限沙箱） |
| `mail_explain_policy` | 无参：返回当前策略摘要；带 `message_id`：返回该封判定与依据 | 是 |

### 2.2 full 追加（7）

| 工具 | 作用 | 风险级 | 默认 |
|---|---|---|---|
| `mail_save_draft` | 存草稿 | 低 | 开 |
| `mail_send_message` | 新发 | 高 | 开（过闸门） |
| `mail_reply_message` | 回复 / 全部回复 | 高 | 开（过闸门） |
| `mail_forward_message` | 转发 | 高 | 开（过闸门） |
| `mail_update_flags` | 已读 / 星标 / 重要 | 中 | 开 |
| `mail_move_messages` | 移动 / 归档 | 中 | 开 |
| `mail_delete_messages` | 删除（进回收站，不永久） | 高 | **关**，需 `--enable-delete` |

---

## 3. 通用响应包裹

所有工具返回统一 envelope：

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "next_cursor": null,
  "request_id": "uuid"
}
```

失败：

```json
{
  "ok": false,
  "error": {
    "code": "E_POLICY_DENIED",
    "message": "send blocked: recipient not in allowlist",
    "retryable": false,
    "detail": {"gate": "whitelist", "recipient": "x@evil.com"}
  },
  "request_id": "uuid"
}
```

---

## 4. 核心对象

### 4.1 Message

```json
{
  "message_id": "<abc@qq.com>",
  "thread_id": "t-123",
  "account": "vmbp4685@agent.qq.com",
  "provider": "imap|gmail|graph|qq-official",
  "folder": "INBOX",
  "received_at": "2026-10-30T01:42:40+08:00",
  "from": {"name": "Q", "address": "qnm951@icloud.com"},
  "to": [{"name": "", "address": ""}],
  "cc": [],
  "subject": "介绍你自己",
  "flags": ["\\Seen"],
  "auth": {"spf": "pass", "dkim": "pass", "dmarc": "pass", "verified": true},
  "trust": "untrusted",
  "tainted": false,
  "taint_reasons": [],
  "body_text": "...",
  "body_truncated": false,
  "quoted_stripped": true,
  "attachments": [
    {"attachment_id": "a-1", "filename": "x.pdf", "size": 10240,
     "mime": "application/pdf", "sha256": "..."}
  ],
  "headers_of_interest": {
    "auto_submitted": null,
    "x_agent_origin": null,
    "list_id": null
  }
}
```

字段约束：

- `trust` 恒为 `untrusted`（对外部来信）；自身已发件为 `self`。
- `tainted=true` 时，该消息不得作为自动回复输入源，且同会话内写工具强制 `confirm`。
- `body_text` 为消毒后纯文本；原文不入库、不落日志。
- `quoted_stripped=true` 表示已剥离引用段，`body_text` 只含新写内容。

### 4.2 PolicyDecision

```json
{
  "decision": "allow|confirm|deny",
  "action": "auto_reply|draft_for_review|read_only|drop",
  "matched_rule": "address:qnm951@icloud.com",
  "priority": 100,
  "evaluated": {
    "auth_pass": true,
    "first_contact": false,
    "quiet_hours": false,
    "quota_ok": true,
    "tainted": false
  },
  "reasons": ["sender matched exact address", "dmarc pass"]
}
```

---

## 5. 参数 Schema（关键工具）

### 5.1 `mail_list_messages`

```json
{
  "type": "object",
  "properties": {
    "account": {"type": "string"},
    "folder": {"type": "string", "default": "INBOX"},
    "since": {"type": "string", "format": "date-time"},
    "until": {"type": "string", "format": "date-time"},
    "unread_only": {"type": "boolean", "default": false},
    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
    "cursor": {"type": "string"},
    "include_body": {"type": "boolean", "default": false}
  },
  "required": ["account"]
}
```

`include_body` 默认 `false`——列表不返回正文，降低单次上下文污染面。只有显式 `mail_get_message` 才取正文。

### 5.2 `mail_search_messages`

```json
{
  "type": "object",
  "properties": {
    "account": {"type": "string"},
    "text": {"type": "string"},
    "from": {"type": "string"},
    "to": {"type": "string"},
    "subject": {"type": "string"},
    "since": {"type": "string", "format": "date-time"},
    "until": {"type": "string", "format": "date-time"},
    "has_attachment": {"type": "boolean"},
    "unread_only": {"type": "boolean"},
    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
    "cursor": {"type": "string"}
  },
  "required": ["account"]
}
```

`text` 只匹配已消毒正文与主题，不匹配附件内容、不匹配 HTML 属性。

### 5.3 `mail_send_message`（full）

```json
{
  "type": "object",
  "properties": {
    "account": {"type": "string"},
    "to": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    "cc": {"type": "array", "items": {"type": "string"}},
    "bcc": {"type": "array", "items": {"type": "string"}},
    "subject": {"type": "string", "maxLength": 200},
    "body_text": {"type": "string", "maxLength": 20000},
    "in_reply_to": {"type": "string"},
    "attachments": {"type": "array", "items": {"type": "string"},
                    "description": "沙箱内绝对路径，服务端校验归属"},
    "intent": {"type": "string", "description": "一句话说明发信目的，必填"},
    "confirmed": {"type": "boolean", "default": false},
    "idempotency_key": {"type": "string"}
  },
  "required": ["account", "to", "subject", "body_text", "intent"]
}
```

**强约束**：

| 约束 | 说明 |
|---|---|
| 无 `source_message_id` 参数 | 不得由服务端自动取来信正文。要引用原文必须显式传 `quoted_text` 并标注来源 |
| `intent` 必填 | 用于审计与环路分析 |
| `confirmed` 语义 | 首次调用返回 `E_NEED_CONFIRM` + 预览摘要；带 `confirmed:true` 重试才执行 |
| 附件路径校验 | 必须落在沙箱目录内，且 sha256 与已下载记录一致 |

### 5.4 `mail_reply_message`（full）

```json
{
  "type": "object",
  "properties": {
    "account": {"type": "string"},
    "message_id": {"type": "string"},
    "body_text": {"type": "string"},
    "reply_all": {"type": "boolean", "default": false},
    "quote_original": {"type": "boolean", "default": true},
    "intent": {"type": "string"},
    "confirmed": {"type": "boolean", "default": false},
    "idempotency_key": {"type": "string"}
  },
  "required": ["account", "message_id", "body_text", "intent"]
}
```

`quote_original=true` 时，服务端自动加标准引用分隔，并在 outbound 记录中标注"含引用"。**引用内容不进模型上下文**，只在发送时拼接。

### 5.5 `mail_get_attachment`

```json
{
  "type": "object",
  "properties": {
    "account": {"type": "string"},
    "message_id": {"type": "string"},
    "attachment_id": {"type": "string"},
    "max_bytes": {"type": "integer", "default": 10485760}
  },
  "required": ["account", "message_id", "attachment_id"]
}
```

返回：

```json
{
  "ok": true,
  "data": {
    "path": "C:\\...\\sandbox\\<uuid>\\x.pdf",
    "filename": "x.pdf",
    "size": 10240,
    "sha256": "...",
    "mime": "application/pdf",
    "content_extractable": true
  }
}
```

返回路径而非 Base64；返回路径由服务端生成，不使用来信文件名。

---

## 6. 闸门语义

### 6.1 发送闸门判定顺序

```
1. profile 允许?            否 → E_PROFILE_DENIED（工具根本不存在，此步仅日志）
2. 策略层 decision?         deny → E_POLICY_DENIED
3. 收件人白名单            不在名单 → confirm（一次授权后可加入）
4. 批量阈值                > 3 收件人 → confirm
5. 内容审查                检出凭据样式 / 长段引用外发 → confirm 或 deny
6. 频率与配额              超限 → E_RATE_LIMITED / E_QUOTA_EXCEEDED
7. taint 检查              源消息 tainted → E_TAINT_WRITE_BLOCKED
8. 环路检查                目标含 Auto-Submitted / X-Agent-Origin → deny
9. confirmed?              false → E_NEED_CONFIRM（返回预览）
10. 执行 + 审计落库
```

### 6.2 错误码

| 码 | 含义 | 可重试 |
|---|---|---|
| `E_PROFILE_DENIED` | 当前 profile 无此能力 | 否 |
| `E_AUTH_MISSING` / `E_AUTH_EXPIRED` | 未授权 / 授权过期 | 需重新授权 |
| `E_PROVIDER_UNSUPPORTED` | 该邮箱不支持所需能力 | 否 |
| `E_POLICY_DENIED` | 策略拒绝 | 否 |
| `E_NEED_CONFIRM` | 需显式确认 | 是（带 confirmed） |
| `E_RATE_LIMITED` / `E_QUOTA_EXCEEDED` | 限流 / 超配额 | 延迟后 |
| `E_TAINT_WRITE_BLOCKED` | 源消息含注入标记 | 否 |
| `E_ATTACHMENT_REJECTED` | 附件类型/大小/路径非法 | 否 |
| `E_CURSOR_INVALID` | 游标失效（UIDVALIDITY 变更） | 重新全量 |

---

## 7. 游标规范

| provider | 游标编码（不透明字符串） |
|---|---|
| imap | `imap:<uidvalidity>:<last_uid>` |
| gmail | `gm:<historyId>` |
| graph | `gr:<deltaToken>` |
| qq-official | `qq:<page_token>` |

`E_CURSOR_INVALID` 时必须返回 `data.resync_required=true`，由调用方决定是否全量重扫，服务端不自动重扫。

---

## 8. 审计记录字段

每次写操作落一行：

```json
{
  "ts": "ISO8601",
  "account": "",
  "action": "send|reply|forward|draft|move|delete|flag",
  "targets": ["a@b.com"],
  "message_id_out": "<...>",
  "source_message_id": null,
  "intent": "",
  "policy_decision": "allow",
  "gate_hit": [],
  "client": "marvis|workbuddy|cli",
  "idempotency_key": ""
}
```

不含正文、不含 token。保留 90 天。

---

## 9. 待定项

1. `mail_get_thread` 的深度上限（建议 20 条，超限提示按需分页）。
2. 多账号并发时的账号级互斥锁粒度。
3. `reader` profile 是否保留 `mail_get_attachment`——有落盘副作用，需确认沙箱目录策略。
4. destructive 工具是否需要独立 profile（`danger`）而非开关。
