# SecondWorld - 多 Agent 小说草稿工具

使用 DeepSeek API 的本地 CLI 多 Agent 章节生成流水线，包含导演 Agent 统一风格与节奏。

## 快速开始

1) 创建虚拟环境并安装依赖：

```bash
uv venv .venv
uv sync
```

后续命令可直接使用 `uv run ...`，无需手动激活环境。

2) 配置 API Key：

```bash
cp config/.env.example .env
# 编辑 .env，设置 DEEPSEEK_API_KEY
```

3) 检查并编辑配置：
- `config/project.yaml`
- `config/agents.yaml`
- `config/character_components/`（性格/背景/身份组件）
- `config/outline.yaml`
- `config/style_guide/`（共享规则在 `anti_ai_rules.md`，各角色提示语在 `agents/`）
- `config/style_guide/components/`（性格/背景/身份提示语）

4) 生成章节草稿：

```bash
uv run python -m src.cli chapter --chapter 0001
```

输出：
- `chapters/`：Markdown 草稿
- `data/state.json`：进度与摘要

## 命令

- 只生成章节计划：

```bash
uv run python -m src.cli plan --chapter 0001 --trace
```

- 生成章节草稿：

```bash
uv run python -m src.cli chapter --chapter 0001 --trace
```

- 自动续写下一章：

```bash
uv run python -m src.cli chapter --trace
```

## 说明

- 流式输出由 `config/project.yaml` 中的 `api.stream` 控制，也可用 `--no-stream` 关闭。
- 章节字数由 `generation.chapter_min_chars` 与 `generation.chapter_max_chars` 控制。
