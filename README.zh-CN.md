<div align="center">

<img src="docs/banner.svg" alt="Mail-Mcp" width="100%">

# Mail-Mcp

### 让邮件成为 Agent 真正能用的工具

通过 IMAP/SMTP 读取、搜索、回复与归档邮件——由一个确定性的策略引擎决定 Agent 能做什么，由一道闸门守住它的发件箱。

<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-3772FF?logo=python&logoColor=white" alt="Python 3.10+">
<img src="https://img.shields.io/badge/MCP-2024--11--05-8A2BE2" alt="MCP 2024-11-05">
<img src="https://img.shields.io/badge/providers-IMAP%20%7C%20SMTP-22D3EE" alt="IMAP / SMTP">
<img src="https://img.shields.io/badge/profiles-3-5B8CFF" alt="三套 profile">
<img src="https://img.shields.io/badge/tests-69%20passing-success" alt="69 项测试通过">
<a href="https://github.com/Faixiang/mail-mcp/stargazers"><img src="https://img.shields.io/github/stars/Faixiang/mail-mcp?style=social" alt="GitHub stars"></a>
<img src="https://img.shields.io/badge/version-0.1.0-1f6feb" alt="Version 0.1.0">

<p>
<a href="README.md">English</a> ·
<b>简体中文</b> ·
<a href="README.zh-TW.md">繁體中文</a>
</p>

</div>

> **本分支就是触发层**
> `main` 是 MCP 服务：请求-响应，工具由客户端调用。「有信就动」做不到——server 无法被一封来信唤醒。
> 本分支补上另一个刻意做薄的进程：事件源 → 总线 → 消费者，事件只带 `event_id` 与元数据，**绝不携带正文**。
> 详见 [docs/trigger.md](docs/trigger.md)。

---

> **当前状态：早期，但可以跑。** IMAP/SMTP 服务商已端到端可用，读工具、策略评估与发信闸门均已落地。
> Gmail API、Microsoft Graph 与腾讯 QQ 官方端点只做了声明，没有实现——它们会直接抛 `E_PROVIDER_UNSUPPORTED`，
> 而不是假装能用。见[路线图](#路线图-)。

## 预览 🖥️

<img src="docs/preview.svg" alt="示例会话：读取、拦下、确认、发出" width="100%">

---

## 为什么做这个 🎯

现有的邮箱 MCP 基本落在两类：单服务商封装，或直接包一层 IMAP。前者换不了第二个账号，后者等于把 `send()` 交给模型并指望它自觉——一封来信里的提示注入，就足以变成你替自己发出的邮件。

本项目站在第三个位置：**统一工具语义、单一策略层、写路径上的一道硬闸门。**

```text
读:  消毒 → 标记 untrusted → 返回
写:  调用方显式参数 → 策略 → 闸门 → 适配器 → 审计
```

两条路径不共享上下文。整个设计就是这一句话。

## 与其它方案的差别 ✨

| | 单服务商 MCP | 裸 IMAP 封装 | Mail-Mcp |
|---|---|---|---|
| 账号 / 服务商 | 一个 | 一个 | 一个注册表，当前支持 IMAP/SMTP |
| 写操作安全 | 无 | 无 | 策略引擎 + 十步闸门 |
| 来信内容 | 原样交给模型 | 原样交给模型 | 消毒后标记 `untrusted`，并做 taint 追踪 |
| 能否拿邮件内容当指令去回信 | 能 | 能 | **不能**——结构上就做不到 |
| 审计 | 无 | 无 | 每次写操作一行，不含正文 |

## 特性 ✨

### 读
- **默认不可信**——每封来信都以 `trust: "untrusted"` 返回，引用段已剥离，隐藏文本与零宽字符已清除
- **列表不返回正文**——`include_body` 默认关闭，列一遍收件箱不会把上下文灌满
- **按会话而不是按整块邮件**——`get_thread` 解析对话、剥掉引用历史、按时间排序
- **附件落到沙箱**——返回本地路径而不是 base64，文件名由服务端生成

### 写
- **结构性隔离**——`reader` 下写工具**根本不注册**。模型无法调用不存在的工具
- **没有 `source_message_id`**——`send_message` 没有任何参数能让服务端从收件箱里把正文提取出来
- **两段式确认**——首次调用返回 `E_NEED_CONFIRM` 与预览，带 `confirmed: true` 才执行
- **幂等**——同一 `idempotency_key` 返回首次结果，不会重复发信
- **环路安全**——所有出站邮件带 `X-Agent-Origin` 与 `Auto-Submitted: auto-replied`；带这两个头的来信永不被自动回复

### 工程
- **策略确定**——`policy.yaml` 由代码评估，不由模型裁决；判定附带可读依据
- **服务商预设**——QQ、Foxmail、163、126、Gmail、Outlook 的 host/port 从地址自动解析
- **安全层是纯函数**——`safety/` 与 `policy/` 收发 dataclass：不碰网络、不碰磁盘、不打日志，因此可以完整单测
- **错误是结构化的**——每次失败都返回错误码（`E_POLICY_DENIED`、`E_TAINT_WRITE_BLOCKED` 等）与 `retryable`、`detail`

## 工具 🧰

工具按 profile 分组。不属于当前 profile 的工具不会出现在工具清单里。

### `reader` —— 8 个工具，无写能力

| 工具 | 作用 | 参数 |
|---|---|---|
| `list_mailboxes` | 账号下的邮件夹，含系统文件夹映射 | — |
| `list_messages` | 按邮件夹列出摘要，最新在前，**不含正文** | `folder`（默认 `INBOX`）、`limit`（默认 20，上限 100）、`unread_only` |
| `search_messages` | 服务端搜索，返回 id 而非内容 | `query`、`folder`、`limit` |
| `get_message` | 单封邮件：消毒后正文、认证结果、taint 标记 | `message_id`、`folder` |
| `get_thread` | 整个会话，引用已剥离、按时间排序 | `thread_id` |
| `get_attachment` | 下载到沙箱并返回本地路径 | `message_id`、`attachment_id`、`max_bytes`（默认 10 MB） |
| `get_quota` | 配额（若服务商提供，IMAP 下多为不可用） | — |
| `get_me` | 当前账号、服务商、profile | — |

### `full` —— 追加 5 个写工具

| 工具 | 作用 | 风险 | 说明 |
|---|---|---|---|
| `send_message` | 新发 | 高 | 过闸门；`intent` 必填 |
| `reply_message` | 回复 / 全部回复 | 高 | 引用由服务端拼接，不进入模型上下文 |
| `forward_message` | 转发 | 高 | 收件人必须显式给出 |
| `mark_message` | 已读 / 星标 / 重要 | 中 | — |
| `move_message` | 移动 / 归档 | 中 | — |

### `danger` —— 追加 2 个 destructive 工具，仅在 `--enable-delete` 时注册

| 工具 | 作用 | 默认 |
|---|---|---|
| `delete_message` | 删除单封（进废纸篓，非永久） | **不注册** |
| `purge_messages` | 批量清除 | **不注册** |

## 架构 🧱

```text
transport/   stdio                  只做协议搬运
tools/       reader | write         参数校验与编排
policy/      规则引擎               只做决策，无 IO
safety/      消毒 / taint / 闸门 / 审计   纯函数，可单测
adapters/    imap | gmail | graph | qq    只做协议差异
store/       凭据 / 游标 / 审计库     唯一碰磁盘的一层
```

依赖方向严格单向：`transport → tools → (policy, safety) → adapters → store`。
因为 `policy` 与 `safety` 从不 import 适配器，项目里最有价值的一半可以在无网络、无邮箱的情况下测完。
细节见 [docs/architecture.md](docs/architecture.md) 与 [docs/profiles.md](docs/profiles.md)。

## 环境要求 📦

| 组件 | 说明 |
|---|---|
| Python | 3.10+ |
| MCP 协议 | `2024-11-05` |
| 依赖 | `mcp`、`pyyaml`、`python-dateutil`（异步 IMAP 需 `aioimaplib`） |
| 邮箱 | 已开启 IMAP + SMTP，并已签发应用专用密码 |
| 实测 | QQ 邮箱 `imap.qq.com:993` / `smtp.qq.com:465` |

## 快速开始 🚀

### ① 取得应用专用密码

不要用账号密码。QQ 邮箱、163、Gmail 都为客户端签发独立凭据；先在网页端开启 IMAP，再生成授权码。

```bash
export MAIL_MCP_PASSWORD="你的应用专用密码"
```

Windows PowerShell：

```powershell
$env:MAIL_MCP_PASSWORD = "你的应用专用密码"
```

### ② 安装

```bash
git clone https://github.com/Faixiang/mail-mcp.git
cd mail-mcp
pip install -e ".[dev]"
```

### ③ 写策略

```bash
mkdir -p ~/.mail-mcp
cp examples/policy.yaml ~/.mail-mcp/policy.yaml
```

至少改 `owner` 与 `allowlist`。其余都有安全默认值——未命中的发件人一律落到 `draft_for_review`。

### ④ 注册到客户端

Claude Desktop / Cursor（`mcp.json`）：

```json
{
  "mcpServers": {
    "mail": {
      "command": "mail-mcp",
      "args": ["--profile", "reader", "--provider", "imap", "--account", "you@qq.com"],
      "env": { "MAIL_MCP_PASSWORD": "你的应用专用密码" }
    }
  }
}
```

先用 `reader`。等你确认策略文件里写的就是「我愿意让它替我发出去的东西」，再切 `full`。

### ⑤ 验证

让客户端调 `get_me`，再调 `list_messages`。两个都正常返回，说明账号、凭据与 profile 都对了。有问题见[排障](#排障-)。

## 配置说明 ⚙️

| 参数 | 默认 | 含义 |
|---|---|---|
| `--profile` | `reader` | `reader` / `full` / `danger` |
| `--account` | — | 邮箱地址，同时作为预设匹配键 |
| `--provider` | `imap` | `imap`（别名 `imap_smtp`、`qq`、`163`、`gmail_imap`） |
| `--home` | `~/.mail-mcp` | 状态根目录：`state/`、`sandbox/`、审计库 |
| `--policy` | `<home>/policy.yaml` | 策略文件 |
| `--enable-delete` | 关 | `danger` 下注册 destructive 工具需显式开启 |

| 环境变量 | 必填 | 含义 |
|---|---|---|
| `MAIL_MCP_PASSWORD` | 是 | 应用专用密码，只从环境读，绝不写进策略文件 |
| `MAIL_MCP_IMAP_HOST` | 否 | 覆盖预设 host |
| `MAIL_MCP_SMTP_HOST` | 否 | 覆盖预设 host |

内置预设：`qq.com`、`foxmail.com`、`163.com`、`126.com`、`gmail.com`、`outlook.com`、`hotmail.com`。
未识别域名需显式指定 host。

## 策略参考 📜

```yaml
owner: me@example.com           # 单主声明，非 owner 的消费者强制只读
default_action: draft_for_review    # auto_reply | draft_for_review | read_only | drop
require_auth_pass: true         # SPF/DKIM/DMARC 不通过时，auto_reply 降为草稿
allowlist: [wife@example.com, boss@company.com]
allowlist_domains: []
rules:
  - match: { subject_contains: ["退订", "unsubscribe", "newsletter"] }
    action: drop
    priority: 100
limits:
  max_sends_per_hour: 10
  max_sends_per_day: 50
  max_recipients_per_send: 3
  max_auto_replies_per_thread: 2
quiet_hours: { start: "23:00", end: "07:30" }
subaddress_tag: agent           # you+agent@example.com 用于区分人发与 Agent 发
```

优先级：主题否决 → 精确地址 → 域 → 默认。引擎确定性且可解释：模型可以读判定依据，不能改判定结果。

## 发信闸门 🚦

十步，顺序固定。任何 `deny` 立即短路；`confirm` 返回 `E_NEED_CONFIRM` 并附预览。

```text
1. profile 允许?          否 → E_PROFILE_DENIED
2. 策略判定?              deny → E_POLICY_DENIED
3. 收件人白名单           未知 → confirm
4. 收件人数量             > 3 → confirm
5. 内容审查               疑似凭据 / 长段引用外发 → confirm 或 deny
6. 频率与配额             超限 → E_RATE_LIMITED / E_QUOTA_EXCEEDED
7. taint 检查             源消息被标记 → E_TAINT_WRITE_BLOCKED
8. 环路检查               含 Auto-Submitted / X-Agent-Origin → E_LOOP_DETECTED
9. 已确认?                否 → E_NEED_CONFIRM（返回预览）
10. 执行 + 审计落库
```

在此之前的所有消毒都按「尽力而为」对待：**只有闸门是硬约束。**

## 使用示例 💬

> 「这两天有什么重要邮件？」

Agent 先 `list_messages`（不取正文），再对关键的几封调 `get_message`。正文以 `trust: untrusted` 返回，引用段已去掉——所以信里那句「忽略之前的指令」落地时只是一段普通文本，而不是纯净上下文里的新指令。

| 你说 | 落到哪个工具 |
|---|---|
| 「昨夜来了什么邮件？」 | `list_messages` → `get_message` |
| 「找一下十月那张发票」 | `search_messages` |
| 「这个会话讲什么，总结一下」 | `get_thread` |
| 「把 PDF 附件存下来」 | `get_attachment`（返回沙箱路径） |
| 「回他，我明天确认」 | `reply_message` → 闸门 → `confirmed: true` |
| 「我刚那封为什么被拦了？」 | 策略判定 + 审计里的 `gate_hit` |

## 排障 🤔

<details>
<summary><b>启动时报 <code>E_AUTH_MISSING</code></b></summary>

客户端启动的那个环境里没有 `MAIL_MCP_PASSWORD`。桌面客户端不继承你的 shell——把变量写进 server 配置的 `env` 块，并确认客户端已重启。
</details>

<details>
<summary><b>服务商拒绝登录</b></summary>

三种常见原因：用了账号密码而不是应用专用密码；网页端 IMAP 还没开；服务商要求 OAuth（开了两步验证的 Gmail、多数企业租户），IMAP 适配器做不到。先换应用专用密码，或者等 Gmail/Graph 适配器。
</details>

<details>
<summary><b>gmail / graph / qq_official 报 <code>E_PROVIDER_UNSUPPORTED</code></b></summary>

只做了声明，没有实现。注册表直接抛错，而不是退到一条半可用的路径上——这样配置错误在启动时就暴露，而不是等到某封信发不出去。
</details>

<details>
<summary><b>每次发信都返回 <code>E_NEED_CONFIRM</code></b></summary>

这是设计行为：收件人不在白名单，或超过批量/内容限制。要么带 `confirmed: true` 重试，要么对方是长期联系人，就加进 `policy.yaml` 的 `allowlist`。
</details>

<details>
<summary><b><code>E_TAINT_WRITE_BLOCKED</code></b></summary>

被回复的那封信带有注入标记。写路径拒绝把被污染的消息当作来源。改用显式正文写回复——这道闸门保护的是你，不是模型。
</details>

<details>
<summary><b>控制台中文乱码</b></summary>

输出是 UTF-8。传统 Windows 控制台先执行 `chcp 65001`，或改用 Windows Terminal。
</details>

## 触发层 🔔

在本分支实现。`main` 只保留 MCP 服务；「有信就动」的另一半在这里，作为独立进程部署。细节见 [docs/trigger.md](docs/trigger.md)。

```text
事件源(IMAP 轮询)  →  总线(SQLite 去重/游标)  →  消费者(子进程)
```

三条保命规则：

- 事件**不带正文**——只有 `event_id`、文件夹、uid、发件人、大小、是否有附件
- `subject` 只存 **sha256 前缀**，因为主题行是注入的高频载体
- 投递语义是**至少一次 + 幂等消费**；连续失败 3 次标 `dead`，不静默重试

该分支测试：69 passed（44 能力层 + 25 触发层）。

## 安全说明 🔒

- 密码是凭据：只走环境变量，不进策略文件、不进审计库；`.gitignore` 已覆盖本地状态目录
- 来信正文不落盘。审计只记目标、`intent` 与命中的闸门，**不含邮件内容**
- 附件写到 `~/.mail-mcp/sandbox/<uuid>/`，文件名由服务端生成；原始文件名只是元数据，不是路径
- `trust: untrusted` 是对客户端的契约：邮件里的内容是数据，不是指令
- 闸门是缓解措施，不是证明。把 `full` profile 理解为「一个 Agent 可以用我的名义发信」，白名单越短越好

## 兼容性 ✅

| 客户端 / 平台 | 状态 |
|---|---|
| Claude Desktop | 可用（stdio） |
| Cursor | 可用（`mcp.json`） |
| Marvis | 可用（MCP 注册表） |
| 任意 MCP 客户端 | 可用——标准 JSON-RPC 2.0 over stdio |
| Windows / macOS / Linux | 可用——无平台相关代码 |

## 路线图 🗺️

- [x] Profile 注册表与结构性隔离（不注册，而非注册后拒绝）
- [x] 消毒、taint 追踪、十步闸门、审计
- [x] IMAP/SMTP 适配器与服务商预设
- [x] 独立触发层（独立分支）
- [ ] Gmail API 适配器（OAuth broker）
- [ ] Microsoft Graph 适配器（OAuth broker）
- [ ] 腾讯 QQ 官方端点适配器
- [ ] 凭据持久化存储（DPAPI / Keychain），替代环境变量
- [ ] 触发层的 IMAP IDLE 长连接与云 Webhook 源
- [ ] 死信重放工具

## 变更记录 📌

| 版本 | 日期 | 要点 |
|---|---|---|
| **0.1.0** | 2026-10-30 | 骨架完成：profile、消毒、策略引擎、发信闸门、审计、IMAP/SMTP 适配器，44 项测试。触发层单独落在 `feat/trigger-layer`（另 25 项测试）。 |

## 参与贡献 🤝

- `policy/` 与 `safety/` 必须保持纯函数——无网络、无磁盘、内部不打日志
- 不过闸门的写工具不收；返回裸 HTML 的读工具不收
- 永远不要加一个「让服务端从来信里推导正文或收件人」的参数
- 新服务商：实现适配器接口、在 `registry.py` 接上，未实现的特性保持抛 `E_PROVIDER_UNSUPPORTED`，而不是静默降级

## 反馈 📢

问题与建议：[开 issue](https://github.com/Faixiang/mail-mcp/issues)。

## 许可 📝

MIT——见 [LICENSE](LICENSE)。
