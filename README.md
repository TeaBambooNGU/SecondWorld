# SecondWorld - 多 Agent 小说草稿工具

使用多模型 API 的本地 CLI 多 Agent 章节生成流水线，包含导演 Agent 统一风格与节奏，并支持基于 LlamaIndex 的小说知识库 RAG 行文参考。

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
# 编辑 .env，设置对应 provider 的 API Key（例如 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 或 `ANTHROPIC_API_KEY`）
# 若启用 RAG，请额外设置 `ZHIPUAI_API_KEY`（用于智谱 Embedding）
# 可选：填写 LANGSMITH_* 环境变量；当设置 LANGSMITH_API_KEY 且未显式设置 LANGSMITH_TRACING 时默认开启追踪
```

3) 检查并编辑配置：
- `config/project.yaml`
- `config/agents.yaml`
- `config/character_components/`（性格/背景/身份组件）
- `config/outline.yaml`
- `config/style_guide/`（共享规则在 `anti_ai_rules.md`，各角色提示语在 `agents/`）
- `config/style_guide/components/`（性格/背景/身份提示语）
- `paths.world_materials_dir`（外部小说素材目录，默认 `/Users/teabamboo/Documents/NGU_Notes/我的小说`）
- `paths.world_materials_exclude_patterns`（素材过滤规则，支持通配符）
- `rag.*` 与 `paths.rag_*`（LlamaIndex RAG 检索配置与向量库路径）

4) 生成章节草稿：

```bash
uv run python -m src.cli chapter --chapter 0001
```

输出：
- `chapters/`：Markdown 草稿
- `data/state.json`：进度与摘要
- `data/world_refs/{chapter_id}/`：世界观素材筛选缓存（含 `manifest.json`）

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

- 构建/更新小说知识库索引（txt -> 向量库）：

```bash
uv run python -m src.cli rag-index --rebuild
```

## 说明

- 流式输出由 `config/project.yaml` 中的 `api.stream` 控制，也可用 `--no-stream` 关闭。
- 章节字数由 `generation.chapter_min_chars` 与 `generation.chapter_max_chars` 控制。
- 模型类型由 `api.provider` 控制，默认 `openai`（中转站 `https://code.ppchat.vip/v1` + `gpt-5.2-codex`），可选 `deepseek`、`anthropic`。
- `openai` 可使用中转站 endpoint（例如 `https://code.ppchat.vip/v1`），并通过环境变量读取密钥（例如 `OPENAI_API_KEY`）。
- `anthropic` 支持中转站 endpoint（例如 `https://code.ppchat.vip`），并通过环境变量读取密钥（例如 `ANTHROPIC_API_KEY`）。
- `anthropic` 默认开启 `thinking`（`providers.anthropic.thinking.type=enabled` + `budget_tokens`），可在配置中调整或关闭。
- 当使用 `anthropic` 时，请先安装依赖：`uv add langchain-anthropic`。
- Chapter 流程会先运行“世界观素材筛选 Agent”：从 `paths.world_materials_dir` 批量读取素材并决定迁移全篇或节选到工程缓存（超出输入预算自动分批），再由写作 Agent 仅使用缓存内容进行成稿/修订/终审。
- 世界观素材读取仅扫描 `world_materials_dir` 当前目录，不递归子目录；可通过 `world_materials_exclude_patterns` 过滤指定文件。
- RAG 成稿增强：在成稿阶段根据章节计划/角色贡献构造检索 query，从小说知识库（`paths.rag_vector_db_dir`）召回行文片段，注入提示词用于“学表达、学节奏”，禁止照抄句子或复用原情节。
- RAG 入库来源：`paths.rag_source_dir` 下 `.txt` 文件（递归扫描）；命令为 `uv run python -m src.cli rag-index [--source-dir ...] [--rebuild]`。

## 切换 Provider（简版）

1) 在 `config/project.yaml` 修改 `api.provider`（如 `openai`、`anthropic` 或 `deepseek`，`chatgpt` 也会自动映射到 `openai`）。
   - `anthropic` 使用 `providers.anthropic.model_name`
   - `deepseek/openai` 使用 `providers.<provider>.model`
2) 在 `.env` 配置对应密钥（如 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 或 `DEEPSEEK_API_KEY`）。
3) 重新执行命令（如 `uv run python -m src.cli chapter --chapter 0001`）。
