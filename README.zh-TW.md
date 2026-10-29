<div align="center">

<img src="docs/banner.svg" alt="Mail-Mcp" width="100%">

# Mail-Mcp

### Email, as tools an agent can actually use

透過 IMAP/SMTP 讀取、搜尋、回覆與歸檔郵件——由一個確定性的原則引擎決定 Agent 能做什麼，由一道閘門守住它的寄件匣。

<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-3772FF?logo=python&logoColor=white" alt="Python 3.10+">
<img src="https://img.shields.io/badge/MCP-2024--11--05-8A2BE2" alt="MCP 2024-11-05">
<img src="https://img.shields.io/badge/providers-IMAP%20%7C%20SMTP-22D3EE" alt="IMAP / SMTP">
<img src="https://img.shields.io/badge/profiles-3-5B8CFF" alt="三組 profile">
<img src="https://img.shields.io/badge/tests-44%20passing-success" alt="44 項測試通過">
<a href="https://github.com/Faixiang/mail-mcp/stargazers"><img src="https://img.shields.io/github/stars/Faixiang/mail-mcp?style=social" alt="GitHub stars"></a>
<img src="https://img.shields.io/badge/version-0.1.0-1f6feb" alt="Version 0.1.0">

<p>
<a href="README.md">English</a> ·
<a href="README.zh-CN.md">简体中文</a> ·
<b>繁體中文</b>
</p>

</div>

> **配套層 —— 觸發層**
> MCP 是請求—回應模型：server 無法被一封來信喚醒。凡是「有信就動」的需求，都放在另一個刻意做薄的行程裡，
> 位於 [`feat/trigger-layer`](https://github.com/Faixiang/mail-mcp/tree/feat/trigger-layer) 分支——事件源 → 匯流排 → 消費者，
> 事件只帶 `event_id` 與中介資料，**絕不攜帶正文**。
> 詳見 [docs/trigger.md](https://github.com/Faixiang/mail-mcp/blob/feat/trigger-layer/docs/trigger.md)。

---

> **目前狀態：早期，但可以跑。** IMAP/SMTP 服務商已端到端可用，讀取工具、原則評估與寄信閘門均已落地。
> Gmail API、Microsoft Graph 與騰訊 QQ 官方端點只做了宣告，並未實作——它們會直接拋出 `E_PROVIDER_UNSUPPORTED`，
> 而不是假裝能用。見[藍圖](#藍圖-)。

## 預覽 🖥️

<img src="docs/preview.svg" alt="範例工作階段：讀取、攔下、確認、寄出" width="100%">

---

## 為什麼做這個 🎯

現有的郵件 MCP 大致落在兩類：單一服務商封裝，或直接包一層 IMAP。前者換不了第二個帳號；後者等於把 `send()` 交給模型並指望它自重——一封來信裡的提示注入，就足夠變成你替自己寄出的郵件。

本專案站在第三個位置：**統一的工具語意、單一原則層、寫入路徑上的一道硬閘門。**

```text
讀:  消毒 → 標記 untrusted → 回傳
寫:  呼叫端顯式參數 → 原則 → 閘門 → 轉接器 → 稽核
```

兩條路徑不共用上下文。整個設計就是這一句話。

## 與其他方案的差別 ✨

| | 單一服務商 MCP | 裸 IMAP 封裝 | Mail-Mcp |
|---|---|---|---|
| 帳號 / 服務商 | 一個 | 一個 | 一個註冊表，目前支援 IMAP/SMTP |
| 寫入安全 | 無 | 無 | 原則引擎 + 十步閘門 |
| 來信內容 | 原樣交給模型 | 原樣交給模型 | 消毒後標記 `untrusted`，並做 taint 追蹤 |
| 能否拿郵件內容當指令去回信 | 能 | 能 | **不能**——結構上就做不到 |
| 稽核 | 無 | 無 | 每次寫入一行，不含正文 |

## 特性 ✨

### 讀取
- **預設不可信**——每封來信都以 `trust: "untrusted"` 回傳，引文段已剝離，隱藏文字與零寬字元已清除
- **列表不回傳正文**——`include_body` 預設關閉，列一次收件匣不會把上下文灌滿
- **以會話為單位，而非整封郵件**——`get_thread` 解析對話、剝掉引用的歷史、依時間排序
- **附件落到沙箱**——回傳本機路徑而不是 base64，檔名由伺服器端產生

### 寫入
- **結構性隔離**——在 `reader` 之下，寫入工具**根本不會註冊**。模型無法呼叫不存在的工具
- **沒有 `source_message_id`**——`send_message` 沒有任何參數能讓伺服器端從收件匣裡把正文取出來
- **兩段式確認**——第一次呼叫回傳 `E_NEED_CONFIRM` 與預覽，帶 `confirmed: true` 才執行
- **冪等**——同一個 `idempotency_key` 回傳首次結果，不會重複寄信
- **迴路安全**——所有外寄郵件帶 `X-Agent-Origin` 與 `Auto-Submitted: auto-replied`；帶這兩個標頭的來信永不被自動回覆

### 工程
- **原則確定**——`policy.yaml` 由程式碼評估，不由模型裁決；判定附帶可讀依據
- **服務商預設**——QQ、Foxmail、163、126、Gmail、Outlook 的 host/port 由位址自動解析
- **安全層是純函式**——`safety/` 與 `policy/` 收發 dataclass：不碰網路、不碰磁碟、不寫日誌，因此可以完整單元測試
- **錯誤是結構化的**——每次失敗都回傳錯誤碼（`E_POLICY_DENIED`、`E_TAINT_WRITE_BLOCKED` 等）與 `retryable`、`detail`

## 工具 🧰

工具依 profile 分組。不屬於目前 profile 的工具不會出現在工具清單裡。

### `reader` —— 8 個工具，無寫入能力

| 工具 | 作用 | 參數 |
|---|---|---|
| `list_mailboxes` | 帳號下的郵件匣，含系統資料夾對應 | — |
| `list_messages` | 依郵件匣列出摘要，最新在前，**不含正文** | `folder`（預設 `INBOX`）、`limit`（預設 20，上限 100）、`unread_only` |
| `search_messages` | 伺服器端搜尋，回傳 id 而非內容 | `query`、`folder`、`limit` |
| `get_message` | 單封郵件：消毒後正文、認證結果、taint 標記 | `message_id`、`folder` |
| `get_thread` | 整個會話，引文已剝離、依時間排序 | `thread_id` |
| `get_attachment` | 下載到沙箱並回傳本機路徑 | `message_id`、`attachment_id`、`max_bytes`（預設 10 MB） |
| `get_quota` | 配額（若服務商提供，IMAP 下多為不可用） | — |
| `get_me` | 目前帳號、服務商、profile | — |

### `full` —— 追加 5 個寫入工具

| 工具 | 作用 | 風險 | 說明 |
|---|---|---|---|
| `send_message` | 新寄 | 高 | 過閘門；`intent` 必填 |
| `reply_message` | 回覆 / 全部回覆 | 高 | 引文由伺服器端拼接，不進入模型上下文 |
| `forward_message` | 轉寄 | 高 | 收件人必須顯式給出 |
| `mark_message` | 已讀 / 星號 / 重要 | 中 | — |
| `move_message` | 移動 / 歸檔 | 中 | — |

### `danger` —— 追加 2 個破壞性工具，僅在 `--enable-delete` 時註冊

| 工具 | 作用 | 預設 |
|---|---|---|
| `delete_message` | 刪除單封（進垃圾桶，非永久） | **不註冊** |
| `purge_messages` | 批次清除 | **不註冊** |

## 架構 🧱

```text
transport/   stdio                  只做協定搬運
tools/       reader | write         參數校驗與編排
policy/      規則引擎               只做決策，無 IO
safety/      消毒 / taint / 閘門 / 稽核   純函式，可單元測試
adapters/    imap | gmail | graph | qq    只處理協定差異
store/       憑證 / 游標 / 稽核庫     唯一碰磁碟的一層
```

相依方向嚴格單向：`transport → tools → (policy, safety) → adapters → store`。
因為 `policy` 與 `safety` 從不 import 轉接器，專案裡最有價值的一半可以在無網路、無信箱的情況下測完。
細節見 [docs/architecture.md](docs/architecture.md) 與 [docs/profiles.md](docs/profiles.md)。

## 環境需求 📦

| 元件 | 說明 |
|---|---|
| Python | 3.10+ |
| MCP 協定 | `2024-11-05` |
| 相依套件 | `mcp`、`pyyaml`、`python-dateutil`（非同步 IMAP 需 `aioimaplib`） |
| 信箱 | 已開啟 IMAP + SMTP，並已簽發應用程式專用密碼 |
| 實測 | QQ 信箱 `imap.qq.com:993` / `smtp.qq.com:465` |

## 快速開始 🚀

### ① 取得應用程式專用密碼

不要用帳號密碼。QQ 信箱、163、Gmail 都為用戶端簽發獨立憑證；先在網頁端開啟 IMAP，再產生授權碼。

```bash
export MAIL_MCP_PASSWORD="你的應用程式專用密碼"
```

Windows PowerShell：

```powershell
$env:MAIL_MCP_PASSWORD = "你的應用程式專用密碼"
```

### ② 安裝

```bash
git clone https://github.com/Faixiang/mail-mcp.git
cd mail-mcp
pip install -e ".[dev]"
```

### ③ 寫原則

```bash
mkdir -p ~/.mail-mcp
cp examples/policy.yaml ~/.mail-mcp/policy.yaml
```

至少要改 `owner` 與 `allowlist`。其餘都有安全預設值——未命中的寄件者一律落到 `draft_for_review`。

### ④ 註冊到用戶端

Claude Desktop / Cursor（`mcp.json`）：

```json
{
  "mcpServers": {
    "mail": {
      "command": "mail-mcp",
      "args": ["--profile", "reader", "--provider", "imap", "--account", "you@qq.com"],
      "env": { "MAIL_MCP_PASSWORD": "你的應用程式專用密碼" }
    }
  }
}
```

先用 `reader`。等你確認原則檔裡寫的正是「我願意讓它替我寄出去的東西」，再切到 `full`。

### ⑤ 驗證

讓用戶端呼叫 `get_me`，再呼叫 `list_messages`。兩者都正常回應，代表帳號、憑證與 profile 都對了。有問題見[疑難排解](#疑難排解-)。

## 設定說明 ⚙️

| 參數 | 預設 | 含義 |
|---|---|---|
| `--profile` | `reader` | `reader` / `full` / `danger` |
| `--account` | — | 信箱位址，同時作為預設值的比對鍵 |
| `--provider` | `imap` | `imap`（別名 `imap_smtp`、`qq`、`163`、`gmail_imap`） |
| `--home` | `~/.mail-mcp` | 狀態根目錄：`state/`、`sandbox/`、稽核資料庫 |
| `--policy` | `<home>/policy.yaml` | 原則檔 |
| `--enable-delete` | 關 | `danger` 之下註冊破壞性工具需顯式開啟 |

| 環境變數 | 必填 | 含義 |
|---|---|---|
| `MAIL_MCP_PASSWORD` | 是 | 應用程式專用密碼，只從環境讀取，絕不寫進原則檔 |
| `MAIL_MCP_IMAP_HOST` | 否 | 覆寫預設 host |
| `MAIL_MCP_SMTP_HOST` | 否 | 覆寫預設 host |

內建預設：`qq.com`、`foxmail.com`、`163.com`、`126.com`、`gmail.com`、`outlook.com`、`hotmail.com`。
未識別的網域需顯式指定 host。

## 原則參考 📜

```yaml
owner: me@example.com           # 單一擁有者宣告，非 owner 的消費者強制唯讀
default_action: draft_for_review    # auto_reply | draft_for_review | read_only | drop
require_auth_pass: true         # SPF/DKIM/DMARC 未通過時，auto_reply 降為草稿
allowlist: [wife@example.com, boss@company.com]
allowlist_domains: []
rules:
  - match: { subject_contains: ["取消訂閱", "unsubscribe", "newsletter"] }
    action: drop
    priority: 100
limits:
  max_sends_per_hour: 10
  max_sends_per_day: 50
  max_recipients_per_send: 3
  max_auto_replies_per_thread: 2
quiet_hours: { start: "23:00", end: "07:30" }
subaddress_tag: agent           # you+agent@example.com 用來區分人手寄出與 Agent 寄出
```

優先序：主旨否決 → 精確位址 → 網域 → 預設。引擎確定性且可解釋：模型可以讀判定依據，不能改判定結果。

## 寄信閘門 🚦

十步，順序固定。任何 `deny` 立即短路；`confirm` 回傳 `E_NEED_CONFIRM` 並附預覽。

```text
1. profile 允許?          否 → E_PROFILE_DENIED
2. 原則判定?              deny → E_POLICY_DENIED
3. 收件人白名單           未知 → confirm
4. 收件人數量             > 3 → confirm
5. 內容審查               疑似憑證 / 長段引文外寄 → confirm 或 deny
6. 頻率與配額             超限 → E_RATE_LIMITED / E_QUOTA_EXCEEDED
7. taint 檢查             來源訊息被標記 → E_TAINT_WRITE_BLOCKED
8. 迴路檢查               含 Auto-Submitted / X-Agent-Origin → E_LOOP_DETECTED
9. 已確認?                否 → E_NEED_CONFIRM（回傳預覽）
10. 執行 + 稽核落庫
```

在此之前的所有消毒都按「盡力而為」對待：**只有閘門是硬性約束。**

## 使用範例 💬

> 「這兩天有什麼重要郵件？」

Agent 先 `list_messages`（不取正文），再對關鍵的幾封呼叫 `get_message`。正文以 `trust: untrusted` 回傳，引文段已去除——所以信裡那句「忽略先前的指令」落地時只是一段普通文字，而不是乾淨上下文裡的新指令。

| 你說 | 落到哪個工具 |
|---|---|
| 「昨晚來了哪些郵件？」 | `list_messages` → `get_message` |
| 「找一下十月那張發票」 | `search_messages` |
| 「這個會話在講什麼，總結一下」 | `get_thread` |
| 「把 PDF 附件存下來」 | `get_attachment`（回傳沙箱路徑） |
| 「回他，我明天確認」 | `reply_message` → 閘門 → `confirmed: true` |
| 「我剛那封為什麼被攔了？」 | 原則判定 + 稽核裡的 `gate_hit` |

## 疑難排解 🤔

<details>
<summary><b>啟動時回報 <code>E_AUTH_MISSING</code></b></summary>

用戶端啟動的那個環境裡沒有 `MAIL_MCP_PASSWORD`。桌面用戶端不會繼承你的 shell——把變數寫進 server 設定的 `env` 區塊，並確認用戶端已重新啟動。
</details>

<details>
<summary><b>服務商拒絕登入</b></summary>

三種常見原因：用了帳號密碼而不是應用程式專用密碼；網頁端的 IMAP 還沒開；服務商要求 OAuth（開啟兩步驗證的 Gmail、多數企業租戶），IMAP 轉接器做不到。先換應用程式專用密碼，或等 Gmail/Graph 轉接器。
</details>

<details>
<summary><b>gmail / graph / qq_official 回報 <code>E_PROVIDER_UNSUPPORTED</code></b></summary>

只有宣告，沒有實作。註冊表直接拋錯，而不是退到一條半可用的路徑——這樣設定錯誤在啟動時就暴露，而不是等到某封信寄不出去。
</details>

<details>
<summary><b>每次寄信都回傳 <code>E_NEED_CONFIRM</code></b></summary>

這是設計行為：收件人不在白名單，或超過批次／內容限制。要嘛帶 `confirmed: true` 重試，要嘛對方是長期聯絡人，就加進 `policy.yaml` 的 `allowlist`。
</details>

<details>
<summary><b><code>E_TAINT_WRITE_BLOCKED</code></b></summary>

被回覆的那封信帶有注入標記。寫入路徑拒絕把被污染的訊息當作來源。改用顯式正文寫回覆——這道閘門保護的是你，不是模型。
</details>

<details>
<summary><b>主控台中文亂碼</b></summary>

輸出是 UTF-8。傳統 Windows 主控台先執行 `chcp 65001`，或改用 Windows Terminal。
</details>

## 觸發層 🔔

刻意不在本分支。見 [`feat/trigger-layer`](https://github.com/Faixiang/mail-mcp/tree/feat/trigger-layer) 與
[docs/trigger.md](https://github.com/Faixiang/mail-mcp/blob/feat/trigger-layer/docs/trigger.md)。

```text
事件源(IMAP 輪詢)  →  匯流排(SQLite 去重/游標)  →  消費者(子行程)
```

三條保命規則：

- 事件**不帶正文**——只有 `event_id`、資料夾、uid、寄件者、大小、是否有附件
- `subject` 只存 **sha256 前綴**，因為主旨行是注入的高頻載體
- 投遞語意是**至少一次 + 冪等消費**；連續失敗 3 次標記 `dead`，不靜默重試

該分支測試：69 passed（44 能力層 + 25 觸發層）。

## 安全說明 🔒

- 密碼是憑證：只走環境變數，不進原則檔、不進稽核庫；`.gitignore` 已涵蓋本機狀態目錄
- 來信正文不落盤。稽核只記目標、`intent` 與命中的閘門，**不含郵件內容**
- 附件寫到 `~/.mail-mcp/sandbox/<uuid>/`，檔名由伺服器端產生；原始檔名只是中介資料，不是路徑
- `trust: untrusted` 是對用戶端的契約：郵件裡的內容是資料，不是指令
- 閘門是緩解措施，不是證明。把 `full` profile 理解為「一個 Agent 可以用我的名義寄信」，白名單越短越好

## 相容性 ✅

| 用戶端 / 平台 | 狀態 |
|---|---|
| Claude Desktop | 可用（stdio） |
| Cursor | 可用（`mcp.json`） |
| Marvis | 可用（MCP 註冊表） |
| 任意 MCP 用戶端 | 可用——標準 JSON-RPC 2.0 over stdio |
| Windows / macOS / Linux | 可用——無平台相關程式碼 |

## 藍圖 🗺️

- [x] Profile 註冊表與結構性隔離（不註冊，而非註冊後拒絕）
- [x] 消毒、taint 追蹤、十步閘門、稽核
- [x] IMAP/SMTP 轉接器與服務商預設
- [x] 獨立觸發層（獨立分支）
- [ ] Gmail API 轉接器（OAuth broker）
- [ ] Microsoft Graph 轉接器（OAuth broker）
- [ ] 騰訊 QQ 官方端點轉接器
- [ ] 憑證持久化儲存（DPAPI / Keychain），取代環境變數
- [ ] 觸發層的 IMAP IDLE 長連線與雲端 Webhook 來源
- [ ] 死信重放工具

## 變更記錄 📌

| 版本 | 日期 | 重點 |
|---|---|---|
| **0.1.0** | 2026-10-30 | 骨架完成：profile、消毒、原則引擎、寄信閘門、稽核、IMAP/SMTP 轉接器，44 項測試。觸發層單獨落在 `feat/trigger-layer`（另 25 項測試）。 |

## 參與貢獻 🤝

- `policy/` 與 `safety/` 必須保持純函式——無網路、無磁碟、內部不寫日誌
- 不過閘門的寫入工具不收；回傳裸 HTML 的讀取工具不收
- 永遠不要加一個「讓伺服器端從來信裡推導正文或收件人」的參數
- 新服務商：實作轉接器介面、在 `registry.py` 接上，未實作的特性維持拋出 `E_PROVIDER_UNSUPPORTED`，而不是靜默降級

## 意見回饋 📢

問題與建議：[開 issue](https://github.com/Faixiang/mail-mcp/issues)。

## 授權 📝

MIT——見 [LICENSE](LICENSE)。
