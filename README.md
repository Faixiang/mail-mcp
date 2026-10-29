# mail-mcp

多邮箱统一适配层（Unified Multi-Provider Email MCP Server）。

不是"万能邮箱客户端"，而是给 AI Agent 提供**受控的邮件访问能力**：统一工具语义、统一安全边界、统一策略裁决。协议层能统一，授权层各家用各家的——本项目不假装这件事可以被抹平。

## 定位

市面上现有的邮箱 MCP 大致两类：单家绑定（某个邮箱专用）或裸 IMAP 封装（能读写但不设边界）。本项目占的位置是第三类：

- **多账号 / 多协议统一**：IMAP/SMTP、Gmail API、Microsoft Graph、腾讯 QQ 官方端点
- **安全边界是一等公民**：入站消毒、taint 追踪、出站闸门
- **策略交给用户**：白名单、动作分级、静默时段、配额，全部落配置文件，由确定性代码执行

## 两套 Profile

| profile | 工具数 | 写能力 | 用途 |
|---|---|---|---|
| `reader` | 8 | 无 | 默认值，可公开分发、只读会话 |
| `full` | 15 | 有 | 需显式开启 + 配置策略 |

关键：`reader` 下写工具**不注册**，而不是注册后拒绝调用。工具不存在，模型无法编造调用。

```bash
mail-mcp --profile reader
mail-mcp --profile full --enable-delete=false
```

## 安全模型（摘要）

三道防线，顺序即优先级：

1. **读时消毒** — HTML 隐藏文本、注释、属性夹带、引用段污染、零宽字符，全部白名单化处理
2. **会话隔离** — 只读会话不挂写工具；写会话不接受"从邮件里读来的内容"作为参数
3. **出站闸门** — 白名单、批量阈值、内容审查、配额、taint、环路，十步判定，硬拦截

不假装消毒能挡住一切。**只有闸门是硬约束，前面都可以被绕过**，所以设计重心压在闸门上。

## 快速开始

```bash
git clone https://github.com/Faixiang/mail-mcp.git
cd mail-mcp
pip install -e ".[dev]"
cp examples/policy.yaml ~/.mail-mcp/policy.yaml
mail-mcp --profile reader --account you@example.com
```

客户端配置（Claude Desktop / Cursor / Marvis 等）：

```json
{
  "mcpServers": {
    "mail": {
      "command": "mail-mcp",
      "args": ["--profile", "reader", "--account", "you@example.com"]
    }
  }
}
```

## 状态

骨架阶段。已完成：

- [x] 接口规格 [`docs/profiles.md`](docs/profiles.md)
- [x] 消毒模块（引用剥离 / HTML 白名单 / 隐藏文本）
- [x] 策略引擎（规则优先级 + 可解释判定）
- [x] 出站闸门（十步判定）
- [x] 审计落库
- [ ] IMAP/SMTP 适配器（接口已定，实现中）
- [ ] Gmail / Graph 适配器（OAuth broker 待做）
- [ ] 腾讯 QQ 官方端点适配器
- [ ] 触发层（刻意独立，见 docs/architecture.md §4）

## 为什么触发层不在 MCP 里

MCP 是请求-响应模型，server 生命周期随 client，没有入站通道。想让邮箱"有信就动"，必须另建触发层。把它们焊死在一起是过去返工三次的根因：

- 进程崩 → 能力全停
- 换触发方式 → 要改能力代码
- 换模型 → 又要改触发代码

所以：MCP 无状态、可随时启停；触发层极薄、不含模型逻辑；两者只通过事件契约通信，且**事件不携带正文**。

### 触发层实现在哪

不在 `main`，在 [`feat/trigger-layer`](https://github.com/Faixiang/mail-mcp/tree/feat/trigger-layer) 分支：

- 代码：`src/mail_mcp/trigger/`（contracts / bus / source_imap / consumer / daemon）
- 说明：[docs/trigger.md](https://github.com/Faixiang/mail-mcp/blob/feat/trigger-layer/docs/trigger.md)
- 测试：4 个文件、25 条用例，与主仓 44 条一并跑通（69 passed）

它是可独立部署的进程，不 import `mcp`，也不含任何提示词逻辑。消费者只收到 `event_id` 与元数据，正文要回头经 MCP 读取，从而必然经过消毒层。

## License

MIT
