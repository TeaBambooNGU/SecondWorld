# SecondWorld

> 本地运行的多 Agent 小说创作流水线：从章节计划到成稿、修订、终审，并支持基于 LlamaIndex 的 RAG 行文参考。

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)](#)
[![Package Manager](https://img.shields.io/badge/Package-uv-DE5FE9?style=flat-square)](#)
[![Test](https://img.shields.io/badge/Test-Pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white)](#)
[![Orchestration](https://img.shields.io/badge/Orchestration-LangGraph-0E9F6E?style=flat-square)](#)
[![RAG](https://img.shields.io/badge/RAG-LlamaIndex-7C3AED?style=flat-square)](#)
[![Vector Store](https://img.shields.io/badge/Vector%20Store-Chroma%20%7C%20Milvus-4C51BF?style=flat-square)](#)
[![LLM](https://img.shields.io/badge/LLM-DeepSeek%20%7C%20OpenAI%20%7C%20Anthropic-10B981?style=flat-square)](#)

## 项目简介

SecondWorld 是一个面向中文网文创作的 CLI 工程。它将“计划 → 角色贡献 → 导演成稿 → 编辑复核 → 修订 → 终审”串成可追踪的流水线，
并通过世界观素材筛选与小说语料 RAG 检索，降低跑偏和 AI 味。

- 支持 `deepseek / openai / anthropic` 多 Provider 切换
- 支持章节连续性上下文与剧情摘要缓存
- 支持世界观素材筛选缓存（按章节相关性抽取）
- 支持 Chroma / Milvus 向量库（LlamaIndex）
- 支持 trace 日志与可选 LangSmith 跟踪

> 详细架构请参考 [`docs/architecture.md`](docs/architecture.md)。

## 核心能力

- **章节计划生成**：根据 `config/outline.yaml` 产出结构化计划（JSON）
- **角色贡献并发生成**：多角色并发输出冲突点、动机与细节素材
- **导演链路写作**：成稿、编辑复核、修订、反 AI 清理、终审
- **版本留存**：最新章 + 历史版本（成稿/修订/终审）全量归档
- **RAG 行文参考**：从本地小说语料召回表达片段，仅“学表达，不抄句子”

## 快速开始

### 1) 环境要求

- Python `>=3.12`
- [uv](https://docs.astral.sh/uv/)

### 2) 安装依赖

```bash
uv venv .venv
uv sync
```

### 3) 配置环境变量

```bash
cp config/.env.example .env
```

按需填写：

- `DEEPSEEK_API_KEY`（默认 provider）
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`（切换 provider 时使用）
- `ZHIPUAI_API_KEY`（启用 RAG embedding 时建议配置）
- `LANGSMITH_*`（可选，链路追踪）

### 4) 检查核心配置

重点查看 [`config/project.yaml`](config/project.yaml)：

- `api.provider`：当前模型提供方（默认 `deepseek`）
- `providers.*`：各 provider 的 endpoint / model / key 环境变量映射
- `generation.*`：章节字数、并发、采样参数
- `rag.*`：RAG 开关、向量库类型、检索策略
- `paths.*`：大纲、输出、状态文件、RAG 数据路径

## 命令行用法

### 生成章节计划

```bash
uv run python -m src.cli plan --chapter 0001
```

### 生成章节（缺计划会自动补跑）

```bash
uv run python -m src.cli chapter --chapter 0001
```

常用参数：

- `--trace`：记录完整提示词/响应日志
- `--log-file`：自定义日志文件路径
- `--no-stream`：关闭流式输出
- `--force`：覆盖已存在章节

### 自动续写下一章

```bash
uv run python -m src.cli chapter
```

### 构建/重建 RAG 索引

```bash
uv run python -m src.cli rag-index --rebuild
```

可选参数：

- `--source-dir`：覆盖 `paths.rag_source_dir`

## 输出产物

- `chapters/`：当前章节最新版本
- `chapters/history/`：历史归档（成稿/修订/终审）
- `data/plans/`：章节计划 JSON
- `data/state.json`：章节进度与版本索引
- `data/chapter_plot_summaries.json`：剧情摘要缓存
- `data/world_refs/{chapter_id}/`：世界观素材筛选缓存与 `manifest.json`
- `logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log`：trace 日志

## 目录结构

```text
.
├── config/         # 项目配置、角色配置、风格提示语、.env 示例
├── data/           # 状态、计划、缓存、RAG 数据
├── chapters/       # 最新章节与历史版本
├── docs/           # 架构与设计文档
├── src/            # 核心代码（CLI、流水线、RAG、提示词等）
├── tests/          # 单元测试
└── README.md
```

## 开发与测试

```bash
uv run pytest
```

如果你改动了 RAG 或配置解析逻辑，建议重点回归：

```bash
uv run pytest tests/test_rag_service.py tests/test_rag_retriever.py tests/test_config_loader.py
```

## 常见问题

### 1) 报错缺少 API Key

请检查 `.env` 是否与 `api.provider` 对应；例如 provider 为 `deepseek` 时必须配置 `DEEPSEEK_API_KEY`。

### 2) 使用 Milvus 但无法检索

确认 Milvus 服务可连通；若暂时只想本地跑通，可将 `rag.vector_store` 改为 `chroma` 并执行一次 `rag-index --rebuild`。

### 3) RAG 未生效但章节仍能生成

这是预期行为：RAG 异常会被降级跳过，不会阻断主写作流程。

## 贡献建议

欢迎通过 Issue / PR 提交改进，建议附上：

- 复现步骤
- 预期与实际行为
- 关键日志（可脱敏）
- 对应配置片段（`config/project.yaml`）
