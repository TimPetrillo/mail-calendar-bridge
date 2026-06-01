# Mail-Calendar-Bridge

从 USTC 学校邮箱自动读取邮件，用 Claude API 智能分析内容，将识别出的 DDL（截止日期、考试时间、会议安排等）自动生成 `.ics` 日历文件，可一键导入 Android 手机日历。

## 工作原理

### 本地运行模式

```
USTC 邮箱 --IMAP--> 读取新邮件 --> Claude API 分析 --> 提取 DDL 事件 --> 生成 .ics 文件 --> 导入 Android 日历
```

### 全自动模式（推荐）

```
GitHub Actions (每日 9:00 定时)
  └─> IMAP 读取邮件 → Claude API 提取 DDL → 写入 docs/ddl_events.ics
        └─> 自动提交推送，GitHub Pages 部署
              └─> Android 日历 webcal:// 订阅，自动同步
```

本地运行步骤（仅供调试）：
1. 通过 IMAP SSL 连接 `mail.ustc.edu.cn`，读取最近 N 天的邮件
2. 每封邮件的正文送入 Claude API，用结构化 Tool Use 提取截止日期和日程事件
3. 提取到的事件写入 SQLite 数据库（避免重复处理）并追加到 `.ics` 日历文件
4. 将 `.ics` 文件传输到手机，点击即可导入系统日历

## 环境要求

- Python 3.10 或以上
- Windows 10/11、macOS 或 Linux
- USTC 邮箱账号
- Anthropic API Key（用于 Claude API 调用）

## 安装

### Windows PowerShell

```powershell
cd mail-calendar-bridge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS / Linux / Git Bash

```bash
cd mail-calendar-bridge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

然后用文本编辑器编辑 `.env` 文件，填入真实值。

## 配置

编辑 `.env` 文件，填入以下必要信息：

```ini
# 邮件配置
MAIL_HOST=mail.ustc.edu.cn
MAIL_PORT=993
MAIL_USERNAME=your_username@mail.ustc.edu.cn    # 替换为你的 USTC 邮箱
MAIL_PASSWORD=your_password                      # 替换为客户端专用密码（见下方获取方式）
MAIL_SEARCH_DAYS=7                               # 每次搜索最近几天

# Claude API（支持 Anthropic 官方 API 及第三方兼容 API）
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx           # 替换为你的 API Key
ANTHROPIC_BASE_URL=https://api.anthropic.com     # 可选：API 地址，使用第三方兼容 API 时替换
ANTHROPIC_MODEL=claude-sonnet-4-6                # 可选：模型名称

# 置信度阈值（0.0-1.0），低于此值的事件不会写入日历
DDL_CONFIDENCE_THRESHOLD=0.6
```

### 获取 USTC 邮箱客户端专用密码

USTC 邮箱不支持直接用登录密码连接 IMAP，需要单独生成一个客户端专用密码（授权码）。步骤如下：

1. 登录 <https://mail.ustc.edu.cn>
2. 进入 **设置** → **邮箱安全** 或 **客户端授权密码**
3. 点击 **生成授权密码**，系统会生成一串客户端专用授权码（不依赖 2FA）
4. 将生成的授权码填入 `.env` 的 `MAIL_PASSWORD`

> **注意**：这个授权码是专门给邮件客户端（如 IMAP/SMTP）使用的，与你的邮箱登录密码不同。授权码仅在生成时显示一次，请及时保存。

> **安全提醒**：`.env` 文件包含密码和 API Key，已加入 `.gitignore`，不会提交到 Git。请勿将 `.env` 分享给他人。

## 使用方式

### 基本用法

```bash
# 检查最近 7 天的新邮件，提取 DDL 并生成 .ics 文件
python main.py

# 搜索最近 14 天的邮件
python main.py --days 14

# 干跑模式：只预览会提取什么，不实际写入
python main.py --dry-run

# 只记录高置信度（≥80%）的事件
python main.py --confidence 0.8

# 强制重新处理所有邮件（忽略已处理记录）
python main.py --force-all

# 从数据库完全重建 .ics 文件
python main.py --rebuild-ics
```

本地默认写入 `output/ddl_events_<date>.ics` 和 `data/mail_cache.db`。GitHub Actions 会覆盖输出配置，生成用于 Pages 订阅的 `docs/ddl_events.ics`。

### 运行测试

单元测试使用假环境变量和 mock，不需要真实邮箱密码或 API Key。

```bash
python -m pytest -q
python -m pytest tests/test_mail_reader.py -q
```

如果 Windows 环境中的 `python` 指向 Microsoft Store alias，可改用 `py -m pytest -q`。

### 运行输出示例

```
2026-05-31 10:30:00 [INFO] main: Mail-Calendar-Bridge 启动
2026-05-31 10:30:01 [INFO] mail_reader: 正在连接 mail.ustc.edu.cn:993 ...
2026-05-31 10:30:02 [INFO] mail_reader: 搜索 31-May-2026 以来 (近 7 天) 的邮件...
2026-05-31 10:30:02 [INFO] mail_reader: 找到 15 封邮件，开始按 UID 解析...
2026-05-31 10:30:03 [INFO] main: 开始处理 3 封新邮件（共 15 封，12 封已处理）...
2026-05-31 10:30:03 [INFO] ddl_extractor: 分析邮件 [1/3]: 关于数值分析课程作业提交的通知
2026-05-31 10:30:05 [INFO] ddl_extractor:   → 提取到 1 个事件 (阈值过滤后)
2026-05-31 10:30:05 [INFO] ddl_extractor:     - [homework_deadline] 提交数值分析作业 @ 2026-06-05T23:59:00+08:00 (置信度: 0.95)
2026-05-31 10:30:07 [INFO] calendar_writer: 已追加 1 个事件到 output/ddl_events_YYYY-MM-DD.ics

============================================================
  Mail-Calendar-Bridge 运行摘要
============================================================
  扫描邮件总数:      15
  其中新邮件:        3
  包含事件的邮件:    1
  提取的事件总数:    1
  写入日历的事件:    1
  错误数:            0
============================================================
  日历文件:          output/ddl_events_YYYY-MM-DD.ics
  日历中事件总数:    5
============================================================

提示: 将日历文件传输到手机后，在文件管理器中点击 .ics 文件即可导入日历。
```

### 定时执行

在 Windows 上设置定时任务，让脚本自动运行：

1. 打开 **任务计划程序** (Task Scheduler)
2. 点击 **创建基本任务**
3. 名称：`Mail-Calendar-Bridge`
4. 触发器：**每天**，选择一个合适的时间（如早上 9:00）
5. 操作：**启动程序**
   - 程序：`python`
   - 参数：`main.py`
   - 起始于：`C:\Users\<你的用户名>\mail-calendar-bridge\`

或者使用批处理脚本 `run.bat`：

```bat
@echo off
cd /d C:\Users\<你的用户名>\mail-calendar-bridge
call .venv\Scripts\activate
python main.py >> output\run.log 2>&1
```

## 将日历导入 Android 手机

### 方法一：webcal 订阅（推荐，全自动）

利用 GitHub Pages 部署 .ics 文件后，Android 系统日历原生支持 webcal 订阅，无需安装任何额外 App：

1. **确保 .ics 文件已部署到 Pages**（通过 GitHub Actions 自动完成，或手动推送到 `/docs` 目录）
2. **在手机浏览器中打开** `https://<你的GitHub用户名>.github.io/<仓库名>/ddl_events.ics`
   - 注意：直接在浏览器地址栏输入，文件会自动下载或弹出导入选项
3. **或者**在系统日历 App 中：
   - 打开日历 App -> 设置 -> 添加日历 -> 通过 URL 添加
   - 输入 URL：`https://<你的GitHub用户名>.github.io/<仓库名>/ddl_events.ics`
   - Android 系统会订阅此 URL，之后自动定期拉取更新
4. 日历事件会出现在你的系统日历 App 中，每次脚本运行后自动更新

> **注意**：GitHub Pages 对 **private 仓库**有使用限制（需要 GitHub Pro）。如果仓库设为 public，代码和 GitHub Secrets 仍不会暴露密码，但 `docs/ddl_events.ics` 会作为公开文件发布，里面可能包含课程、会议、地点和邮件主题等个人日程信息。请根据隐私需求选择 public Pages、private 仓库或仅本地使用。

### 方法二：云盘同步

1. 将 `output/` 目录放在 OneDrive 或 Google Drive 的同步文件夹中
2. 在手机上打开对应的云盘 App
3. 找到 `ddl_events_YYYY-MM-DD.ics` 文件，点击打开
4. 系统会自动弹出"添加到日历"对话框，确认导入
5. 日历事件会出现在你的系统日历 App 中

### 方法三：USB 传输

1. 用 USB 数据线连接手机和电脑
2. 将 `output/ddl_events_YYYY-MM-DD.ics` 复制到手机的 `Download` 或任意文件夹
3. 在手机上打开**文件管理器**，找到该文件并点击
4. 选择用**日历**打开，确认导入

### 方法四：微信/QQ 传输

1. 通过微信或 QQ 将 `ddl_events_YYYY-MM-DD.ics` 发送到手机
2. 在手机上下载文件并点击打开
3. 选择日历 App 导入

### 去重说明

每次导入 `.ics` 文件时，Android 日历 App 会根据事件 UID 自动去重。同一个事件（同一封邮件提取出的同一 DDL）不会被重复添加。如果你已经导入过一次，再次导入相同的事件会被自动跳过。

## 事件类型说明

| 类型 | 说明 | 示例 |
|------|------|------|
| `homework_deadline` | 作业、实验报告、课程设计截止 | "提交数值分析作业，截止日期 6月5日" |
| `exam` | 考试安排 | "期末考试时间: 6月20日 14:00-16:00" |
| `meeting` | 会议、组会、讨论 | "本周五下午 2 点组会，地点西区 3A102" |
| `thesis` | 论文提交、开题、答辩 | "博士论文盲审提交截止: 7月1日" |
| `registration` | 报名、选课、注册 | "研究生暑期学校报名截止: 6月10日" |
| `payment` | 缴费 | "学费缴纳截止日期: 6月15日" |
| `activity` | 讲座、活动、比赛 | "学术报告: 6月8日 10:00 东区报告厅" |
| `other` | 其他日程 | 无法归入以上类别但有明确时间的事件 |

## 项目结构

```
mail-calendar-bridge/
├── .env.example                  # 配置模板
├── .env                          # 实际配置（不提交）
├── .gitignore
├── requirements.txt              # Python 依赖
├── README.md                     # 本文件
├── main.py                       # 主入口
├── config.py                     # 配置管理
├── mail_reader.py                # IMAP 邮件读取
├── ddl_extractor.py              # Claude API DDL 提取
├── calendar_writer.py            # .ics 文件生成
├── db.py                         # SQLite 数据库
├── .github/workflows/            # GitHub Actions CI
│   └── daily-sync.yml            # 每日定时同步工作流
├── docs/                         # GitHub Pages 部署源
│   └── ddl_events.ics            # Actions 生成的日历文件
├── output/                       # 本地运行时的 .ics 输出目录（不提交）
├── data/                         # 本地数据库文件目录（不提交）
└── tests/                        # 单元测试
    ├── test_mail_reader.py
    ├── test_ddl_extractor.py
    └── test_calendar_writer.py
```

## GitHub Actions 全自动部署 + Pages webcal 订阅

### 概述

将代码推送到 GitHub 后，GitHub Actions 每天定时运行流水线：
1. 连接邮箱读新邮件
2. Claude API 提取 DDL
3. 生成 `docs/ddl_events.ics`
4. 自动提交推送日历文件到仓库
5. GitHub Pages 部署，手机通过 webcal 订阅

**不再需要**手动运行脚本、手动传输 .ics 文件到手机。Actions 只提交 `docs/ddl_events.ics`；`data/mail_cache.db` 是运行缓存，不提交到仓库。

### 首次配置

#### 步骤 1：创建 GitHub 仓库

1. 在 GitHub 创建一个新仓库（建议命名为 `mail-calendar-bridge`）
2. 仓库可见性建议选择 **public**（private 仓库使用 GitHub Pages 需要 GitHub Pro）
3. 不要勾选 "Initialize this repository with a README"（已有代码）

#### 步骤 2：推送代码

```bash
cd mail-calendar-bridge
git init
git add .env.example .gitignore README.md requirements.txt main.py config.py mail_reader.py ddl_extractor.py calendar_writer.py db.py .github/workflows/daily-sync.yml docs/.gitkeep tests
git commit -m "feat(mail-calendar-bridge): init"
git branch -M main
git remote add origin https://github.com/<你的用户名>/mail-calendar-bridge.git
git push -u origin main
```

#### 步骤 3：配置 GitHub Secrets

在仓库 Settings -> Secrets and variables -> Actions 中，添加以下 Repository secrets：

| Secret 名称 | 值 | 说明 |
|---|---|---|
| `MAIL_USERNAME` | `your_username@mail.ustc.edu.cn` | USTC 邮箱地址 |
| `MAIL_PASSWORD` | （你的授权码） | USTC 邮箱客户端授权码 |
| `ANTHROPIC_API_KEY` | （你的 API Key） | Claude API 密钥 |

如果需要自定义模型或 API 地址，还可添加：

| Secret 名称 | 值 | 默认值 |
|---|---|---|
| `MAIL_HOST` | `mail.ustc.edu.cn` | 已内置 |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | 已内置 |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | 已内置 |
| `DDL_CONFIDENCE_THRESHOLD` | `0.6` | 已内置 |
| `MAIL_SEARCH_DAYS` | `7` | 已内置 |

#### 步骤 4：启用 GitHub Pages

1. 进入仓库 Settings -> Pages
2. Source 选择 **Deploy from a branch**
3. 分支选择 **main**，文件夹选择 **/docs**
4. 点击 Save
5. 等待部署完成（GitHub 会显示通知）
6. 确认 Pages URL：`https://<你的用户名>.github.io/mail-calendar-bridge/ddl_events.ics`

#### 步骤 5：在 Android 手机上订阅

1. 打开手机上的日历 App（系统日历或 Google 日历）
2. 进入设置 -> 添加日历 -> 通过 URL 添加
3. 输入：`https://<你的用户名>.github.io/mail-calendar-bridge/ddl_events.ics`
4. 确认添加
5. 完成。之后系统自动定期拉取更新

### 验证

1. 在仓库 Actions 页面，点击 "Daily DDL Sync" -> Run workflow -> Run workflow
2. 观察运行日志，确认无错误
3. 运行完成后，检查 `docs/ddl_events.ics` 是否已推送到仓库，并确认 `data/mail_cache.db` 没有进入提交
4. 在浏览器打开 Pages URL，确认能下载 .ics 文件
5. 在手机上查看日历，确认事件已出现

### 故障排查

**IMAP 连接失败 (IMAP connect failed)**：
- USTC 邮件服务器 `mail.ustc.edu.cn` 已确认对公网开放，GitHub Actions runner 可以连接
- 检查 `MAIL_PASSWORD` 是否正确（注意：是授权码，不是邮箱登录密码）

**API 调用失败 (Anthropic API)**：
- 检查 `ANTHROPIC_API_KEY` 是否正确
- 检查 `ANTHROPIC_BASE_URL` 是否能从 GitHub Actions 访问（第三方代理通常支持）
- 如果 API 响应 timeout，可在 workflow 中增加 `ANTHROPIC_MODEL` Secret 换用更快的模型

**Pages 部署后看不到更新**：
- GitHub Pages 有 CDN 缓存，首次可能需要 1-2 分钟
- 在 URL 后加 `?v=1` 等参数可绕过部分缓存
- Android 日历的 webcal 刷新间隔取决于系统和 App 实现（通常 24 小时内至少拉取一次）

## 后续升级方向

- **CalDAV 自动同步**：部署 Radicale CalDAV 服务器 + Android DAVx5 客户端，实现全自动双向同步
- **Google Calendar API**：直接写入 Google 日历，Android 原生同步
- **邮件分类模型**：区分课程邮件、学院通知、垃圾邮件，提高提取准确率
- **Web 界面**：提供浏览器查看历史提取结果和手动校准功能
- **Web 订阅 URL**：生成可订阅的 .ics URL，日历 App 可定期拉取更新

## 安全说明

- 邮件密码和 API Key 仅存储在本地 `.env` 文件中，不通过网络传输
- IMAP 连接使用 SSL (port 993)，传输层加密
- 邮件内容仅发送到 Anthropic API（用于 Claude 分析），不发送到任何其他第三方
- 本地运行时的邮件缓存和事件记录存储在本地 SQLite 数据库中，默认路径为 `data/mail_cache.db`
- GitHub Actions 发布的 `docs/ddl_events.ics` 可能包含个人日程信息；如果仓库或 Pages 是公开的，这个文件也会公开