# 工程架构梳理

- 当前梳理时间: 2026-02-28 22:17:40

## 项目概览

- 项目定位: 本地 CLI 多 Agent 小说草稿生成流水线
- 主要能力: 章节计划生成、角色贡献汇总、导演成稿、修订与终审、状态记录、基于 LlamaIndex 的知识库 RAG 行文参考
- 关键输出: `chapters/` 最新正文、`chapters/history/` 成稿/修订/终审归档（命名: 成稿/成稿二...、修订一/修订二...、终审/终审二...）、`data/plans/` 计划、`data/state.json` 进度与版本索引、`data/chapter_plot_summaries.json` 章节剧情摘要缓存、`data/world_refs/{chapter_id}/` 世界观素材缓存与 `manifest.json`、`data/rag/chroma/`（Chroma 本地索引，可选）或 Milvus 集合（默认）小说知识库向量索引、`logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log` 追踪日志

## 工程逻辑梳理

### 入口与启动

- 入口文件/命令: `src/cli.py`，通过 `uv run python -m src.cli plan|chapter` 启动
- 启动流程概述: CLI 解析参数 -> 初始化 `LangChainPipeline` -> 执行计划或成稿流程

### 核心模块

- `src/langchain_pipeline.py`: LangChain/LCEL 主流水线，组织计划生成、角色贡献、贡献清洗（移除 `sensory_anchor`）、成稿、复核、修订、反AI清理、终审与状态落盘
- `src/langchain_client.py`: 多 Provider LLM 客户端工厂，按 provider 构建 DeepSeek/OpenAI/Anthropic 实例，并透传温度、采样与 Anthropic thinking 参数
- `src/chains/*`: 分阶段 LCEL 链（计划/角色贡献/成稿/复核/修订/反AI/终审）
- `src/prompting.py`: ChatPromptTemplate 提示词与风格提示语拼接，包含暗线字段注入、计划/成稿均为 3 版预演择优、角色锚点双注入、成稿字数修正与玄幻编辑复核提示词
- `src/world_reference_manager.py`: 世界观素材管理，基于章节关键词排序候选素材，调用“素材筛选 Agent”决定迁移全篇或节选，并将结果落盘到工程缓存
- `src/rag/embeddings.py`: 智谱 Embedding 适配层，基于 LangChain 社区版 `ZhipuAIEmbeddings`，并加入 64 条上限分批
- `src/rag/indexer.py`: 小说 `.txt` 语料读取、清洗与切分（章节标题识别 + 段落优先 + 长段兜底滑窗）并写入 LlamaIndex（支持 Chroma/Milvus 切换）
- `src/rag/retriever.py`: 基于 LlamaIndex 的多路检索融合（`default+mmr`），通过 `QueryFusionRetriever(mode=reciprocal_rerank)` 做 RRF 融合（支持 Chroma/Milvus 切换），并记录 query 改写结果到日志
- `src/rag/service.py`: RAG 配置解析（含 `rag.vector_store` 与 `rag.milvus.*`）、检索 query 构建、检索结果格式化、CLI 索引构建入口
- `src/parsers.py`: JSON 提取与自修复解析
- `src/validators.py`: 计划/复核/贡献 JSON 校验与正文长度检查
- `src/config_loader.py`: 读取 YAML/文本配置与环境变量，统一解析 `api + providers` 生效配置（含 Anthropic `model_name` 与 `thinking`）
- `src/utils.py`: 通用工具、角色画像合成、禁用词提取/命中检测与日志写入

### 依赖关系

- 外部依赖: `langchain`、`langchain-deepseek`、`langchain-openai`、`langchain-anthropic`、`langgraph`、`pyyaml`、`python-dotenv`、`llama-index`、`chromadb`、`llama-index-vector-stores-chroma`、`pymilvus`、`llama-index-vector-stores-milvus`、`langchain-community`、`zhipuai`
- 内部依赖: `src/langchain_pipeline.py` 调用 chains/prompting/parsers/validators/langchain_client/config_loader/utils 协作完成主流程

### 数据流/控制流

- 大纲 `config/outline.yaml` -> 计划链路 -> 计划 `data/plans/{chapter}.json`（JSON 解析与自修复）
- 计划提示词中的 Series outline 仅使用系列/世界观概要，不包含 chapters，章节种子单独传入
- 角色组件 `config/style_guide/components/{personality|background|identity}/*.md` + 角色配置 `config/agents.yaml`（主角/配角按角色名，龙套使用 archetype） -> 角色画像（含 traits）
- 启动阶段由 `resolve_api_config` 合并 `api` 与 `providers`：按 `api.provider` 选中 provider 配置，解析 `baseUrl/base_url`、`apiKeyEnv/api_key_env`、`timeout`、`max_retries`、`stream` 与 `thinking`
- Provider 模型字段按类型区分：Anthropic 要求 `model_name`；DeepSeek/OpenAI 使用 `model`（或 `models[].id`）
- 角色画像 + 角色提示语 -> 角色贡献链路（`generation.agent_concurrency`>1 时并行执行；JSON 解析与自修复） -> 贡献结果清洗（移除 `highlights[*].sensory_anchor`） -> 导演成稿链路 -> 编辑复核 JSON -> 修订（`max_turns`>1 且 suggestions 非空时触发） -> 反AI高频词审核清理 -> 终审 -> 状态写入 `data/state.json`
- 编辑复核输出 JSON（summary/issues/suggestions/pacing_score），并作为后续修订与状态摘要来源
- 成稿字数不达标时触发补写/压缩修正链路
- 计划提示词与成稿提示词均要求“内部预演 3 版择优输出”
- Chapter 流程新增“素材筛选 Agent”：从 `paths.world_materials_dir` 读取素材后，按相关性排序并优先批量调用筛选提示词；当批次内容超出输入预算时自动分批调用，决定 `full/excerpt/skip` 后写入 `data/world_refs/{chapter_id}/` 再组装为计划/成稿/复核阶段可选参考
- 世界观素材读取仅扫描 `paths.world_materials_dir` 当前目录，不递归子目录，并按 `paths.world_materials_exclude_patterns` 过滤文件（支持通配符）
- 计划/写作相关 Agent（计划/成稿/复核）只读取工程缓存中的提取结果，不直接读取外部素材目录，以降低噪音与上下文漂移
- 成稿提示词 = 章节计划 + 角色贡献 + 风格提示语 + 成稿示例段落（学习特点）+ RAG 行文参考（来自小说知识库检索）
- 计划提示词新增“连续性上下文”：按章节顺序读取已生成章节，紧邻当前章节的前 3 章注入全文，其余章节注入剧情摘要（来自摘要缓存）
- 计划/成稿/编辑复核提示词 = 原有输入 + 可选世界观参考（来自缓存，允许直接引用设定内容，禁止生造设定）
- `rag-index` 命令读取 `paths.rag_source_dir`（可被 `--source-dir` 覆盖）的 `.txt` 文件，先清洗抓取噪声（过滤 `ps*`/`（ps:）`、`(本章完)`、分隔线、相邻重复章节标题）后按“章节标题->段落优先”切分，超长段落再按 `rag.chunk_*` 兜底滑窗，最终按 `rag.vector_store` 写入 Chroma（`paths.rag_vector_db_dir`）或 Milvus（`rag.milvus.*` + `paths.rag_collection`）
- RAG 语料读取编码按 `utf-8 -> utf-8-sig -> gb18030` 依次尝试，兼容 GB2312 文本
- 成稿前基于章节计划与角色贡献构造 RAG query，按 `rag.retrieval_modes` 组装子检索器（默认 `default+mmr`），再由 `QueryFusionRetriever(mode=reciprocal_rerank)` 做 RRF 融合；`rag.fusion_num_queries>1` 时触发 query 改写，改写结果写入 trace 日志；最终按 `rag.retriever_top_k` 与 `rag.max_reference_chars` 截断后注入提示词，要求“学表达，不抄句，不复用情节”
- 成稿/修订/终审正文 -> 最新正文写入 `chapters/{chapter_id}_{slug}.md` -> 版本归档写入 `chapters/history/{chapter_id}_{slug}_{成稿|成稿二...|修订一|修订二...|终审|终审二...}.md` -> 版本索引写入 `data/state.json`
- 风格提示语由 `config/style_guide/anti_ai_rules.md`、`config/style_guide/agents/{角色名}.md`（主角/配角）与 `config/style_guide/agents/{暴烈型|谨慎型|仁善型|冷静型}.md`（龙套类）、`config/style_guide/agents/director/{plan|draft|revision|final}.md` 与 `config/style_guide/components/{type}/{id}.md` 组合后注入 system 提示词
- 计划/成稿/修订/终审/字数修正提示词统一启用“双锚点角色一致性策略”：在 user 中段注入“内部确认仍遵守 system 角色”，并在 user 末尾再注入一次自检提示，以降低后文偏置导致的角色约束漂移（确认语不写入最终输出）
- 剧情摘要缓存采用文件持久化：`paths.plot_summary_cache_path`（默认 `data/chapter_plot_summaries.json`）；已存在摘要优先复用，避免重复生成
- 编辑复核阶段由 `build_post_check_prompt` 组装复核提示词，在 `LangChainPipeline._post_check` 中通过 `build_post_check_chain` 调用，阶段标记为“修订-复核”
- 反AI清理阶段在命中高频词后触发，`build_anti_ai_cleanup_prompt` 组装清理提示词，在 `LangChainPipeline.run_chapter` 中通过 `build_anti_ai_cleanup_chain` 调用，阶段标记为“修订-反AI”
- 所有主生成链路（计划/角色贡献/成稿/复核/修订/终审）统一透传 `temperature`、`top_p` 与可选 `top_k`；JSON 修复链路固定 `temperature=0`、`top_p=1`、`top_k=None`
- Anthropic provider 默认透传 `thinking` 参数（当前配置为 `{"type":"enabled","budget_tokens":2048}`），并支持在 `providers.anthropic.thinking` 覆盖

### 成稿版本留存

- 最新版本: `chapters/{chapter_id}_{slug}.md`
- 历史版本: `chapters/history/{chapter_id}_{slug}_{成稿|成稿二...}.md`、`chapters/history/{chapter_id}_{slug}_{修订一|修订二...}.md`、`chapters/history/{chapter_id}_{slug}_{终审|终审二...}.md`
- 版本索引: `data/state.json` 记录版本路径、标签与生成时间

### 关键配置

- `config/project.yaml`: API、生成参数与路径
- `config/project.yaml` 现采用“双层配置”：`api` 仅声明当前生效 provider，`providers.*` 维护各 provider 的 endpoint/模型/密钥环境变量
- `config/project.yaml` 新增 `rag.*`：是否启用、向量库类型（`rag.vector_store`）、Milvus 连接参数（`rag.milvus.*`）、Embedding 模型/分批、文本切分、检索模式（`rag.retrieval_modes`）、融合 query 数（`rag.fusion_num_queries`）、融合异步开关（`rag.fusion_use_async`）、MMR 参数（`rag.mmr_lambda`/`rag.mmr_prefetch_factor`）、检索 top_k（统一使用 `rag.retriever_top_k`）与参考字符预算
- `config/project.yaml` 新增 `paths.plot_summary_cache_path`，用于章节剧情摘要持久化缓存
- `config/project.yaml` 新增 `paths.rag_source_dir`、`paths.rag_vector_db_dir`、`paths.rag_collection`，用于知识库语料与索引存储
- 当前 RAG 语料目录配置: `paths.rag_source_dir=data/rag/novel_txt`
- `config/agents.yaml`: 角色档案、组件引用与 traits
- `config/style_guide/components/`: 性格/背景/身份组件
- `config/outline.yaml`: 章节大纲
- `config/style_guide/`: 反AI规则与各角色独立提示语
- `config/style_guide/agents/{角色名}.md`: 主角/配角提示语（非 director）
- `config/style_guide/agents/{暴烈型|谨慎型|仁善型|冷静型}.md`: 龙套类提示语
- `config/style_guide/agents/director/plan.md`: 导演计划提示语
- `config/style_guide/agents/director/draft.md`: 导演成稿提示语
- `config/style_guide/agents/director/revision.md`: 导演修订提示语
- `config/style_guide/agents/director/final.md`: 导演终审提示语
- `config/style_guide/draft_examples.yaml`: 成稿示例段落与学习特点列表
- `paths.world_materials_dir`: 可配置的外部小说素材目录（默认 `/Users/teabamboo/Documents/NGU_Notes/我的小说`）
- `paths.world_materials_exclude_patterns`: 世界观素材过滤规则（如 `CLAUDE.md`、`AGENTS.md`、`*第*卷*.md` 等）
- `config/style_guide/components/`: 性格/背景/身份提示语
- `.env`: API Key（`DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY`）
- `.env`: RAG Embedding Key（`ZHIPUAI_API_KEY`）
- 当前生效配置: `api.provider=anthropic`，使用中转站 endpoint `https://code.ppchat.vip`，模型字段为 `providers.anthropic.model_name`
- `config/project.yaml` 新增/扩展 `providers.*`、`generation.agent_concurrency`、`generation.top_k`、`generation.world_selector_batch_chars` 与 `dialogue.*` 并保持向后兼容

### 运行流程

- 运行步骤: chapter 命令先读取计划（缺失则自动补跑 plan；plan 阶段会注入章节连续性上下文并引入可选世界观参考）-> 世界观素材筛选 Agent 按需迁移全篇/片段到 `data/world_refs/{chapter_id}/` -> 按并发配置生成角色贡献 -> RAG 检索知识库行文片段并注入成稿提示词 -> 成稿并可流式输出（含可选世界观参考与 RAG 参考） -> 编辑复核 JSON（含可选世界观参考） -> 修订（满足条件时，不注入世界观参考） -> 反AI高频词审核清理 -> 终审（无条件执行，不注入世界观参考） -> 生成当前章剧情摘要并写入缓存 -> 每次成稿/修订/终审归档版本
- 异常/边界处理: 缺少 API Key 直接报错；provider 缺少必填模型字段（Anthropic `model_name` / 其他 provider `model`）时报配置错误；章节文件已存在且未 `--force` 则中止；流式失败自动回退为非流式；计划/贡献/复核 JSON 多轮修复后仍不合法则中止；RAG 缺少 `ZHIPUAI_API_KEY` 或向量库为空时仅跳过 RAG 参考，不中断成稿主流程
- 观测与日志: `--trace` 写入 `logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log`，章节状态写入 `data/state.json`，RAG 阶段额外记录 query 与 QueryFusion 改写结果（`RAG Query 改写结果`），可选启用 LangSmith 跟踪

### 观测与追踪（LangSmith）

- 能力说明: 通过环境变量开启 LangSmith 跟踪，将链路执行追踪写入 LangSmith 项目
- 默认行为: 设置 `LANGSMITH_API_KEY` 且未显式配置 `LANGSMITH_TRACING` 时，程序自动开启追踪
- 环境变量示例:
```
export LANGSMITH_TRACING=true
export LANGSMITH_ENDPOINT=https://api.smith.langchain.com
export LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export LANGSMITH_PROJECT=your_langsmith_project
```

## 改动概要/变更记录

### 2026-02-28 22:17:40

- 本次新增/更新要点: RAG 检索策略升级为 LlamaIndex 官方多路融合：`src/rag/retriever.py` 使用 `QueryFusionRetriever(mode=reciprocal_rerank)` 融合 `default+mmr` 子检索器；删除多余 top_k 变量，仅保留 `rag.retriever_top_k`；配置更新为 `rag.retrieval_modes`、`rag.fusion_num_queries`、`rag.fusion_use_async`、`rag.mmr_lambda`、`rag.mmr_prefetch_factor`；新增 query 改写日志落盘（`RAG Query 改写结果`）
- 变更动机/需求来源: 用户要求将“多路召回 + RRF”切换为 LlamaIndex 内置实现，并开启多 query 改写可观测日志，便于定位检索行为
- 当前更新时间: 2026-02-28 22:17:40

### 2026-02-28 22:03:29

- 本次新增/更新要点: RAG 向量库新增 Milvus 扩展并保留 Chroma：`rag.vector_store` 支持 `chroma|milvus`；`src/rag/indexer.py` 与 `src/rag/retriever.py` 按配置动态切换后端；`config/project.yaml` 默认切换为 `milvus` 并新增 `rag.milvus.*` 连接配置
- 变更动机/需求来源: 用户本地已部署 Milvus Docker，要求在不移除 Chroma 的前提下通过配置切换后端并重建索引
- 当前更新时间: 2026-02-28 22:03:29

### 2026-02-28 16:21:54

- 本次新增/更新要点: 同步 RAG 清洗规则增强：新增抓取网文噪声过滤（`（ps:）`、`(本章完)`、分隔线、相邻重复章节标题），用于适配“章节标题重复 + 新书求票 + 本章完”这类文本格式
- 变更动机/需求来源: 用户提供新样例并要求“这种格式也过滤”，并同步更新架构文档
- 当前更新时间: 2026-02-28 16:21:54

### 2026-02-28 16:15:28

- 本次新增/更新要点: 同步 RAG 入库切分优化：`src/rag/indexer.py` 新增 `ps*`/分隔线清洗、章节标题识别、段落优先分块与长段滑窗兜底；补充编码读取策略 `utf-8/utf-8-sig/gb18030`（兼容 GB2312）；同步当前 `paths.rag_source_dir=data/rag/novel_txt`
- 变更动机/需求来源: 用户提供《剑来》样例并询问格式适配，要求按建议优化 RAG 读取与切分策略后更新架构文档
- 当前更新时间: 2026-02-28 16:15:28

### 2026-02-28 15:38:40

- 本次新增/更新要点: 新增 LlamaIndex RAG 框架能力（`src/rag/*`）：支持小说 txt 入库到 Chroma 向量库（`rag-index` 命令）与成稿阶段检索注入；Embedding 采用智谱 `embedding-3` 并实现 64 条分批；配置新增 `rag.*` 与 `paths.rag_*`
- 变更动机/需求来源: 用户要求“添加 LlamaIndex 框架做数据接入/索引/检索，用知识库小说行文示例降低 AI 味，并提供 txt 入库逻辑”
- 当前更新时间: 2026-02-28 15:38:40

### 2026-02-28 14:58:22

- 本次新增/更新要点: 同步最新代码实现：成稿预演策略统一为“内部 3 版择优”；补充角色贡献清洗（移除 `sensory_anchor`）与提示词约束（禁解释腔/禁拆分感官字段）；更新 Anthropic `thinking` 当前配置为 `{"type":"enabled","budget_tokens":2048}`；补充 `generation.world_selector_batch_chars` 配置项
- 变更动机/需求来源: 用户要求“根据最新代码更新 architecture.md”
- 当前更新时间: 2026-02-28 14:58:22

### 2026-02-25 15:38:52

- 本次新增/更新要点: 计划/成稿/修订/终审/字数修正提示词新增“双锚点角色一致性策略”，采用“中段确认 + 结尾再注入”的 user 提示结构，显式要求仅内部确认且不写入最终输出
- 变更动机/需求来源: 用户要求参考工程架构文档优化提示词结构，缓解 LLM 注意力偏移与后文偏置
- 当前更新时间: 2026-02-25 15:38:52

### 2026-02-25 11:30:07

- 本次新增/更新要点: “已生成章节连续性参考”从成稿阶段前移至计划阶段；“可选世界观参考”改为仅在计划/成稿/编辑复核阶段注入，修订与终审阶段不再注入
- 变更动机/需求来源: 用户要求调整阶段提示词输入边界，减少后续修订与终审阶段的外部参考干扰
- 当前更新时间: 2026-02-25 11:30:07

### 2026-02-24 21:50:42

- 本次新增/更新要点: 成稿阶段新增“连续性上下文”注入，按规则读取已生成章节（紧邻当前章节的前 3 章全文，其余章节剧情摘要）；新增 `data/chapter_plot_summaries.json` 作为剧情摘要持久化缓存，仅保留 LLM 生成来源，避免混入 `state` 回填摘要
- 变更动机/需求来源: 用户要求“成稿阶段读取已生成章节并保持剧情连贯；紧邻当前章节的前 3 章全文、其余摘要；摘要需持久化且已生成不重复”
- 当前更新时间: 2026-02-24 21:50:42

### 2026-02-24 17:57:31

- 本次新增/更新要点: 新增世界观素材筛选链路，支持从 `paths.world_materials_dir` 读取外部素材并由“素材筛选 Agent”按章节语义决定迁移全篇或节选，结果落盘 `data/world_refs/{chapter_id}/manifest.json`；成稿/修订/终审提示词新增缓存参考注入
- 变更动机/需求来源: 用户要求“写小说/优化时可自主查询世界观资料，并由独立 Agent 先降噪提取后给写作 Agent 使用”
- 当前更新时间: 2026-02-24 17:57:31

### 2026-02-24 14:16:35

- 本次新增/更新要点: 架构文档同步 Provider 双层配置（`api`+`providers`）、Anthropic `model_name` 约束、中转站 endpoint 与默认 `thinking=adaptive` 行为；补充 `langchain-anthropic` 依赖与对应异常处理
- 变更动机/需求来源: 用户要求“根据最新代码更新 architecture.md”
- 当前更新时间: 2026-02-24 14:16:35

### 2026-02-24 10:53:57

- 本次新增/更新要点: 同步 `top_k` 参数在客户端与全链路调用；补充角色贡献并行执行机制、计划/成稿“6版预演择优”提示策略、动态历史版本命名规则
- 变更动机/需求来源: 用户要求“根据最新代码更新 architecture.md”
- 当前更新时间: 2026-02-24 10:53:57

### 2026-01-25 15:19:29

- 本次新增/更新要点: 补充复核与反AI清理提示词的调用流程说明
- 变更动机/需求来源: 用户询问 build_post_check_prompt 与 build_anti_ai_cleanup_prompt 的调用位置
- 当前更新时间: 2026-01-25 15:19:29

### 2026-01-25 14:34:11

- 本次新增/更新要点: 补充 LangSmith 默认追踪开启逻辑说明
- 变更动机/需求来源: 用户要求默认开启追踪并更新文档
- 当前更新时间: 2026-01-25 14:34:11

### 2026-01-25 14:02:15

- 本次新增/更新要点: 架构文档新增 LangSmith 跟踪能力与环境变量说明
- 变更动机/需求来源: 用户要求支持 LANGSMITH 跟踪并记录配置方式
- 当前更新时间: 2026-01-25 14:02:15

### 2026-01-24 23:14:07

- 本次新增/更新要点: 新增 `api.provider` 与多模型类型工厂说明，补充 `langchain-deepseek` 依赖
- 变更动机/需求来源: 用户要求默认使用 DeepSeek 并保留 openai 作为可配置 provider
- 当前更新时间: 2026-01-24 23:14:07

### 2026-01-24 22:57:01

- 本次新增/更新要点: 主流水线切换为 LangChain/LCEL，新增链路/解析/校验模块并移除旧 pipeline/deepseek_client，实现流式回退与字数修正，CLI 仅保留新链路
- 变更动机/需求来源: 用户要求根据 LangChain 重构设计文档重构工程且无需保留旧接口旧代码
- 当前更新时间: 2026-01-24 22:57:01

### 2026-01-24 17:26:40

- 本次新增/更新要点: 补充编辑复核 JSON 与修订触发条件说明，更新运行流程与梳理时间
- 变更动机/需求来源: 用户要求梳理当前最新代码并生成 LangChain 重构设计文档
- 当前更新时间: 2026-01-24 17:26:40

### 2026-01-24 15:56:46

- 本次新增/更新要点: 计划与成稿提示词新增“先预演三版并择优输出”的质量指引，并同步架构说明
- 变更动机/需求来源: 用户要求提升生成质量，要求先预演三个版本再输出最佳版本
- 当前更新时间: 2026-01-24 15:56:46

### 2026-01-23 23:29:51

- 本次新增/更新要点: 成稿提示词支持示例段落与学习特点列表，并新增对应配置文件路径
- 变更动机/需求来源: 用户要求在成稿环节附上示例文章段落列表，每段落附带学习特点
- 当前更新时间: 2026-01-23 23:29:51

### 2026-01-13 23:37:46

- 本次新增/更新要点: Agent/导演 system 提示词移除英文说明与 Style guide 标签，仅保留提示语正文
- 变更动机/需求来源: 用户要求于皓 Agent 与导演 Agent 的 system 提示词只保留 Style guide 内容
- 当前更新时间: 2026-01-13 23:37:46

### 2026-01-13 22:25:07

- 本次新增/更新要点: 修订提示词移除 Chapter plan，Editor notes 前置到提示词开头
- 变更动机/需求来源: 用户要求在修订-改稿-提示词中删除 Chapter plan 并前置 Editor notes
- 当前更新时间: 2026-01-13 22:25:07

### 2026-01-13 20:46:15

- 本次新增/更新要点: 修订流程增加反AI高频词审核清理，shared.md 更名为 anti_ai_rules.md
- 变更动机/需求来源: 用户要求修订时清理高频网文词，并改名共享规则文件
- 当前更新时间: 2026-01-13 20:46:15

### 2026-01-13 19:47:59

- 本次新增/更新要点: 计划提示词的 Series outline 移除 chapters，仅保留系列/世界观概要
- 变更动机/需求来源: 用户要求 Series outline 不包含大纲 chapters
- 当前更新时间: 2026-01-13 19:47:59

### 2026-01-13 15:17:47

- 本次新增/更新要点: 风格提示语从 user 段落迁移到 system 段落
- 变更动机/需求来源: 用户要求 Style guide 的提示词放入 system，不写到 user
- 当前更新时间: 2026-01-13 15:17:47

### 2026-01-13 14:56:31

- 本次新增/更新要点: 角色提示语改为角色名文件，龙套沿用 archetype 提示语；同步更新 `config/agents.yaml` 角色清单
- 变更动机/需求来源: 用户要求按大纲重写主角与配角提示语，角色文件使用角色名命名，龙套不单独建角色文件
- 当前更新时间: 2026-01-13 14:56:31

### 2026-01-13 11:29:56

- 本次新增/更新要点: 移除导演提示语回退逻辑，删除 `config/style_guide/agents/director.md`
- 变更动机/需求来源: 用户要求仅使用分阶段提示语，不再回退到旧导演提示语文件
- 当前更新时间: 2026-01-13 11:29:56

### 2026-01-13 11:21:44

- 本次新增/更新要点: 导演提示语拆分为计划/成稿/修订/终审四文件，并新增终审阶段与归档命名
- 变更动机/需求来源: 用户要求分阶段提示语与终审流程，终审无条件执行且替代编辑二次复核
- 当前更新时间: 2026-01-13 11:21:44

### 2026-01-12 20:41:04

- 本次新增/更新要点: 历史章节命名规则调整为成稿/修订序号，不再使用时间戳
- 变更动机/需求来源: 用户要求优化 history 文件命名，采用成稿/修订一/修订二的规则
- 当前更新时间: 2026-01-12 20:41:04

### 2026-01-12 20:05:06

- 本次新增/更新要点: 增加导演成稿提示语的功能性符号规则说明，并补充架构配置说明
- 变更动机/需求来源: 用户要求在导演成稿阶段加入新的符号提示词
- 当前更新时间: 2026-01-12 20:05:06

### 2026-01-12 19:35:49

- 本次新增/更新要点: 增加成稿版本归档与版本索引的输出路径说明
- 变更动机/需求来源: 用户要求每次成稿保留完整正文，而非仅保留最终修订版
- 当前更新时间: 2026-01-12 19:35:49

### 2026-01-12 16:47:54

- 本次新增/更新要点: 追踪日志命名更新为 `logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log`（章节名+年月日时分秒）
- 变更动机/需求来源: 用户要求优化追踪日志命名格式
- 当前更新时间: 2026-01-12 16:47:54

### 2026-01-12 16:23:25

- 本次新增/更新要点: 引入角色组件 YAML 与组件提示语，按 traits 组合角色画像并拼接风格提示语
- 变更动机/需求来源: 用户要求性格/背景/身份组件化与 traits 独立化
- 当前更新时间: 2026-01-12 16:23:25

### 2026-01-12 15:45:30

- 本次新增/更新要点: 拆分风格提示语为共享与按角色独立文件，新增提示语组合逻辑与架构梳理文档
- 变更动机/需求来源: 用户要求共享规则独立、各 Agent 提示语彼此独立
- 当前更新时间: 2026-01-12 15:45:30
