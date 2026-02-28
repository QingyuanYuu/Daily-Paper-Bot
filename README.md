# Daily Paper Bot

每天自动从 **arXiv** 和 **Hugging Face** 抓取与你的研究方向相关的论文，通过社区热度 + 时效性 + 关键词匹配进行排名，使用 **Claude** 生成中英混合的结构化摘要，最终写入 **Notion** 形成可长期沉淀的知识库。

> 默认配置面向 **机器人 / 具身智能** 方向（humanoid、world model、diffusion、dexterous manipulation），但你可以通过修改关键词将它适配到任何研究领域。

## Pipeline 总览

```
┌──────────────┐     ┌──────────────┐
│   arXiv API  │     │ HF Daily     │
│  (按关键词搜索) │     │ Papers API   │
│  最近 7 天     │     │ + HTML 爬虫   │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └────────┬───────────┘
                ▼
       ┌────────────────┐
       │  Merge & Dedupe │  按 arXiv ID 去重（fallback: 标题哈希）
       │  合并 HF likes   │  补全缺失的 abstract / authors / 日期
       └────────┬───────┘
                ▼
       ┌────────────────┐
       │     Rank       │  score = 0.6·log(1+likes)
       │   打分 & 排序    │       + 0.3·recency_bonus
       │   取 Top-K      │       + 0.1·keyword_match
       └────────┬───────┘
                ▼
       ┌────────────────┐
       │   Summarize    │  Claude 生成两种摘要：
       │   (Claude API)  │  · Digest 短摘要（今日锐评 + 要点速览）
       │                │  · Note 详细笔记（方法详解 + 复现计划）
       └────────┬───────┘
                ▼
       ┌────────────────┐
       │  Notion Writer │  · 创建/更新 Daily Digest 页面
       │                │  · 创建/更新 Paper Note 页面
       │                │  · 自动关联（Digest ↔ Note）
       └────────────────┘
```

## 各阶段详解

### 1. Fetch — 论文抓取

**arXiv**：对每个关键词构造 `all:"keyword"` 查询，搜索最近 N 天（默认 7 天）的论文，按提交日期倒序，每个关键词最多返回 50 篇。一篇论文如果同时命中多个关键词（例如同时包含 "humanoid" 和 "world model"），会被多次搜到，后续合并阶段会将它们合为一条并保留所有匹配到的关键词标签。

**Hugging Face**：调用 HF Daily Papers JSON API 获取当天全部热门论文（包含 likes 数），在标题 + 摘要中进行关键词子串匹配，筛选出相关论文。如果 API 失败，自动 fallback 到 HTML 页面爬虫。

### 2. Merge & Dedupe — 合并去重

将两个来源的论文合并为一份列表：
- **去重键**：优先用 arXiv ID（如 `2401.12345`），没有 arXiv ID 时用标题规范化后的哈希值
- **合并策略**：HF likes 取最大值；matched_keywords 做并集；缺失的 abstract、authors、published 日期从另一来源补全

### 3. Rank — 打分排名

每篇论文的综合得分：

```
score = 0.6 × log(1 + hf_likes)      # 社区热度（对数衰减，避免极端值主导）
      + 0.3 × recency_bonus           # 时效性（今天=1.0，7天前=0.0，线性衰减）
      + 0.1 × keyword_match_strength  # 关键词匹配度（匹配数 / 总关键词数）
```

按得分降序取前 `top_k` 篇（默认 5，可通过 `.env` 中的 `TOP_K` 覆盖）。

**关于多关键词匹配**：一篇论文可以同时匹配多个关键词。例如一篇涉及 humanoid + diffusion 的论文，`keyword_match_strength = 2/4 = 0.5`，比只匹配一个的论文（0.25）得分更高。实际效果中 HF likes 占主导地位，关键词匹配作为辅助信号。

### 4. Summarize — Claude 结构化摘要

对每篇入选论文，调用 Claude API 生成两种摘要（中英混合输出）：

| 类型 | Prompt | 用途 | 内容 |
|------|--------|------|------|
| **Digest 摘要** | `skills/digest_prompt.md` | Daily Digest 页面 | 今日锐评、要点速览、每篇论文的问题设定 / 创新点 / 核心方法 / 机器人启示 / 风险局限 / 复现建议 |
| **Note 笔记** | `skills/note_prompt.md` | Paper Note 独立页面 | 一句话结论、方法详解（Pipeline / 表征结构 / 训练目标 / 推理流程 / 关键设计选择）、创新点、局限、复现计划（~1000字） |

两个 prompt 文件可自行编辑定制。

### 5. Write to Notion — 写入 Notion

- **Daily Digest 页面**：在指定的父页面下创建当天的子页面（标题格式：`Daily Digest – 2026-02-28`），包含所有入选论文的概览、摘要和到详细笔记的链接
- **Paper Note 页面**：在指定的数据库中为每篇论文创建独立页面，包含完整的结构化笔记
- **幂等写入**：通过 Key 字段（arXiv ID 或标题哈希）去重，重复运行不会产生重复页面，而是更新已有页面

---

## 快速上手

### 前置条件

- Python 3.11+
- 一个 [Notion](https://www.notion.so) 账号
- 一个 [Anthropic](https://console.anthropic.com) API Key

### 第一步：克隆 & 安装

```bash
git clone https://github.com/QingyuanYuu/Daily-Paper-Bot.git
cd Daily-Paper-Bot
pip install -r requirements.txt
```

### 第二步：配置 Notion

1. **创建 Notion Integration**
   - 前往 [My Integrations](https://www.notion.so/my-integrations)，点击 "New integration"
   - 起个名字（如 "Paper Bot"），选择你的 workspace，点击 "Submit"
   - 复制生成的 **Internal Integration Token**（以 `ntn_` 或 `secret_` 开头）

2. **创建 Digest 父页面**
   - 在 Notion 中新建一个页面，作为所有 Daily Digest 的"总目录"（例如取名 "Daily Digests"）
   - 点击页面右上角 `···` → "Connections" → 添加你刚创建的 integration
   - 获取页面 ID：点击 "Share" → "Copy link"，URL 中最后的 32 位十六进制字符串就是 ID
     ```
     https://www.notion.so/Your-Page-Title-{这里就是32位ID}
     ```

3. **创建 Paper Notes 数据库**
   - 新建一个 **Full Page Database**（完整页面数据库）
   - 添加以下属性（Properties）：

     | 属性名 | 类型 | 说明 |
     |--------|------|------|
     | `Name` | Title | 论文标题（自带的） |
     | `URL` | URL | 论文链接 |
     | `Key` | Rich text | 去重键（系统自动填写） |
     | `ArXiv ID` | Rich text | arXiv 编号 |

   - 同样将 integration 连接到此数据库
   - 获取数据库 ID：打开数据库页面，"Share" → "Copy link"，URL 中 `?v=` 之前的 32 位十六进制串
     ```
     https://www.notion.so/{这里是32位DB_ID}?v=...
     ```

### 第三步：配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的实际值：

```env
# 必填
NOTION_API_KEY=ntn_你的integration_token
DIGEST_PARENT_PAGE_ID=你的digest父页面ID
NOTES_DB_ID=你的paper_notes数据库ID
ANTHROPIC_API_KEY=sk-ant-你的anthropic_key

# 选填 — 覆盖 config.yaml 中的默认值
# TOP_K=3                  # 每天选几篇论文（默认 5）
# WINDOW_DAYS=7             # arXiv 搜索最近几天（默认 7）
# KEYWORDS=humanoid,world model,diffusion   # 自定义关键词（逗号分隔）
# TZ=America/Los_Angeles    # 时区
```

### 第四步：运行

```bash
# 正常运行（抓取 → 排名 → 摘要 → 写入 Notion）
python -m app.daily_digest

# 先试一下 dry run（只打印到终端，不写 Notion）
python -m app.daily_digest --dry-run

# 指定日期和论文数
python -m app.daily_digest --date 2026-02-27 --top_k 5
```

---

## 自定义关键词

关键词决定了你能收到哪些论文。修改方式（二选一）：

**方式 A**：编辑 `.env`（推荐，环境变量优先级最高）
```env
KEYWORDS=reinforcement learning,transformer,LLM agent
```

**方式 B**：编辑 `config.yaml`
```yaml
keywords:
  - reinforcement learning
  - transformer
  - LLM agent
```

**关键词工作方式**：
- arXiv 对每个关键词做短语搜索（`all:"keyword"`），所以 `world model` 会精确匹配这个短语
- HF 在标题 + 摘要中做子串匹配（大小写不敏感）
- 一篇论文可以匹配多个关键词，匹配越多得分越高

---

## 调整排名权重

编辑 `config.yaml` 中的 `ranking.weights`：

```yaml
ranking:
  top_k: 5
  weights:
    hf_likes: 0.6       # 社区热度权重
    recency: 0.3         # 时效性权重
    keyword_match: 0.1   # 关键词匹配权重
```

例如，如果你更看重最新论文而非热门论文：
```yaml
  weights:
    hf_likes: 0.3
    recency: 0.6
    keyword_match: 0.1
```

---

## 定制摘要 Prompt

两个 prompt 文件控制 Claude 的输出格式和内容：

- `skills/digest_prompt.md` — Daily Digest 页面的摘要风格（今日锐评、要点速览、每篇论文概述）
- `skills/note_prompt.md` — Paper Note 页面的分析深度（方法详解、复现计划、约 1000 字）

直接编辑这两个 Markdown 文件即可。当前默认 prompt 以中英混合输出，面向机器人/具身智能方向。如果你的研究方向不同，建议修改 prompt 中的"目标读者"描述和领域相关段落。

---

## GitHub Actions 自动化

项目自带 GitHub Actions 工作流，每天自动运行。

### 配置步骤

1. 将项目推送到 GitHub
2. 进入仓库 **Settings → Secrets and variables → Actions → New repository secret**
3. 添加以下 4 个 secret：

   | Secret 名 | 值 |
   |-----------|---|
   | `NOTION_API_KEY` | 你的 Notion integration token |
   | `DIGEST_PARENT_PAGE_ID` | Digest 父页面 ID |
   | `NOTES_DB_ID` | Paper Notes 数据库 ID |
   | `ANTHROPIC_API_KEY` | Anthropic API key |

### 自动运行

工作流每天 **太平洋时间 09:00**（UTC 17:00）自动执行。

### 手动触发

在 **Actions** 标签页 → 选择 **Daily Paper Digest** → 点击 **Run workflow**，可选参数：

- `date` — 指定日期（`YYYY-MM-DD` 格式，默认当天）
- `top_k` — 论文数量（默认 5）

---

## 测试

```bash
python -m pytest tests/ -v
```

当前覆盖：
- `test_merger.py` — 去重逻辑（按 arXiv ID / 标题哈希）、字段合并（likes / keywords / abstract / published）、边界情况
- `test_ranker.py` — 评分公式正确性、top-k 截取、自定义权重、边界情况

---

## 项目结构

```
app/
  __main__.py              # python -m app 入口
  daily_digest.py          # CLI 参数解析 + 5 阶段 pipeline 编排
  config.py                # 加载 config.yaml，支持 .env 环境变量覆盖
  models.py                # PaperCandidate（论文候选）& PaperSummary（摘要结构）
  providers/
    arxiv_provider.py      # arXiv API 按关键词 + 时间窗口搜索
    hf_provider.py         # HF Daily Papers JSON API + HTML 爬虫 fallback
  services/
    merger.py              # 多来源合并 & 去重
    ranker.py              # 打分公式 & 排序截取
    summarizer.py          # Claude API 调用 + 结构化响应解析
    notion_writer.py       # Notion API: upsert 页面 + block 构建
skills/
  digest_prompt.md         # Digest 摘要的 system prompt
  note_prompt.md           # Paper Note 详细分析的 system prompt
tests/
  test_merger.py           # 合并去重单元测试
  test_ranker.py           # 评分排名单元测试
config.yaml                # 关键词、搜索参数、排名权重配置
.env.example               # 环境变量模板
.github/workflows/
  daily_digest.yml         # GitHub Actions 每日定时任务
```

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | — |
| LLM | Anthropic Claude (`claude-sonnet-4-20250514`) | 论文摘要生成 |
| 知识库 | Notion API (`notion-client`) | 结构化输出 & 长期沉淀 |
| 学术搜索 | arXiv API (`arxiv` 包) | 全字段关键词搜索 |
| 社区热度 | Hugging Face (`requests` + `beautifulsoup4`) | Daily Papers + likes |
| 自动化 | GitHub Actions | 每日定时触发 |
| 配置 | YAML + dotenv | 灵活的多层配置 |

## License

MIT
