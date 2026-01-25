# LangChain 重构版设计文档

## 1. 目标与范围

- 目标: 在保持现有 CLI 与输出结构兼容的前提下，将章节生成流程重构为 LangChain/LCEL 链式编排，提升可维护性、可观测性与可测试性。
- 范围: 计划生成、角色贡献、成稿、编辑复核、修订、反 AI 清理、终审、状态落盘、日志追踪。
- 非目标: 修改提示词语义、改变输出目录结构、引入在线训练或微调。

## 2. 现状梳理（来自 docs/architecture.md）

- 入口: `src/cli.py` 负责参数解析与 `ChapterPipeline` 调度。
- 核心: `src/pipeline.py` 组织多阶段生成与状态更新。
- 提示词: `src/prompting.py` 组装计划/成稿/修订/终审/复核提示词。
- 客户端: `src/deepseek_client.py` 直接请求 DeepSeek API，支持流式输出。
- 数据输出: 计划 JSON、章节正文、历史归档、`data/state.json`。

## 3. 设计原则

- **兼容优先**: 保持 CLI 命令、配置路径、输出文件结构不变。
- **结构化输出**: 计划与复核必须严格 JSON，解析失败可自修复重试。
- **可观测性**: 保留 trace 日志格式与关键信息颗粒度。
- **最小侵入**: 尽量复用现有提示词与配置结构。

## 4. 输入契约

输入由配置与运行参数组成:

- 配置文件
  - `config/project.yaml`（API、生成参数、路径）
  - `config/outline.yaml`（章节大纲）
  - `config/agents.yaml`（角色与 traits）
  - `config/style_guide/**`（风格规则、角色提示语、组件）
  - `config/style_guide/draft_examples.yaml`（成稿示例段落）
- 运行参数
  - `--chapter`、`--force`、`--trace`、`--no-stream`
- 状态输入
  - `data/state.json`（上一章摘要、版本索引）

## 5. 输出契约

输出保持与现有实现一致:

- 章节计划: `data/plans/{chapter_id}.json`
- 章节正文: `chapters/{chapter_id}_{slug}.md`
- 历史归档: `chapters/history/{chapter_id}_{slug}_{成稿|修订X|终审}.md`
- 状态索引: `data/state.json`（summary/issues/suggestions/pacing_score/versions）
- trace 日志: `logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log`

## 6. LangChain 组件与链路设计

### 6.1 组件划分

- **LLM Client**
  - 使用 LangChain LLM 包装 DeepSeek API（保持 base_url、model、api_key_env）。
- **Prompt Templates**
  - 复用 `src/prompting.py` 的文本内容，改为 `ChatPromptTemplate`。
- **Output Parsers**
  - `PlanParser`: 计划 JSON（chapter_id/title/goal/beats/cast/conflicts/pacing_notes/word_target）
  - `PostCheckParser`: 复核 JSON（summary/issues/suggestions/pacing_score）
- **Agent Runtime**
  - 主链路与角色贡献优先使用 structured-chat + LCEL Chain + Parser。
  - 角色对话/记忆由 LangGraph 编排，节点使用 structured-chat（不采用 ReAct）。
- **Validators**
  - JSON 校验、字段完备性校验、字数范围校验、禁用词命中检查。
- **Stores**
  - `PlanStore`、`DraftWriter`、`HistoryArchiver`、`StateStore`。
- **Callbacks**
  - Trace 记录提示词与响应，保持现有日志结构。

### 6.2 链路编排（LCEL）

```
StyleGuideComposer
  -> PlanChain
  -> AgentContributionChain (map over agents)
  -> DraftChain (stream optional)
  -> PostCheckChain
  -> RevisionChain (conditional)
  -> AntiAiCleanupChain (conditional)
  -> FinalChain
  -> PersistChain (plan/versions/state)
```

### 6.3 条件与分支

- `RevisionChain`: 当 `max_turns > 1` 且 `suggestions` 非空时触发。
- `AntiAiCleanupChain`: 禁用词命中时触发，仅重写命中段落。
- `Retry`: 解析失败或字数不达标触发自修复重试（1-2 次）。

## 7. 数据结构

### 7.1 计划 JSON

```
{
  "chapter_id": "0001",
  "title": "...",
  "goal": "...",
  "beats": ["..."],
  "cast": ["agent_id"],
  "conflicts": ["..."],
  "pacing_notes": "...",
  "word_target": 4000
}
```

### 7.2 复核 JSON

```
{
  "summary": "...",
  "issues": ["..."],
  "suggestions": ["..."],
  "pacing_score": 8
}
```

### 7.3 角色贡献 JSON

```
{
  "agent_id": "a001",
  "name": "某角色",
  "highlights": ["要点1", "要点2", "要点3"]
}
```

- `highlights` 长度 6-10，保持要点粒度一致。

### 7.4 状态索引（摘要）

- `chapters.{chapter_id}.file`
- `chapters.{chapter_id}.summary`
- `chapters.{chapter_id}.versions[]`
- `chapters.{chapter_id}.updated_at`

## 8. 提示词与输出解析规范

- 计划/复核输出必须严格 JSON，可使用格式自修复提示词。
- 角色贡献输出必须严格 JSON（含 6-10 条要点数组）。
- 成稿/修订/终审输出为 Markdown 正文，不包含代码围栏。
- 风格提示语注入 system，章节计划与素材注入 user。
- 复用现有提示词逻辑，保持“先预演三版再择优输出”指令。

## 9. 质检与去 AI 味策略

参考 `docs/deepseek_novel_agent_design.md`:

- 句首重复率阈值、禁用词命中、节拍覆盖率。
- 高频套话清理（`anti_ai_rules.md` 中禁用词列表）。
- 质检不通过时，精确指出失败项进行定向重写。

## 10. 配置与依赖

- 继续使用 `config/project.yaml` 的 `api`/`generation`/`paths`。
- 依赖建议:
  - `uv add langchain`
  - `uv add langchain-deepseek`
  - `uv add langchain-openai`（可选）
  - `uv add langgraph`（角色对话/记忆子系统）
- 环境变量:
  - `DEEPSEEK_API_KEY`
- 建议新增配置（不变更现有字段）:
  - `api.provider`（默认 deepseek，可选 openai）
  - `generation.agent_concurrency`（默认 3-5）
  - `dialogue.max_concurrency`（默认 2-4，单会话串行）
  - `dialogue.memory_summary_every`（默认 10）
  - `dialogue.memory_summary_threshold`（默认 30）

## 11. 日志与可观测

- 使用 LangChain Callback 记录:
  - Prompt 组装结果
  - LLM 响应原文
  - 解析后 JSON
- 保持 `logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log` 格式，方便回放与定位。
- 角色对话日志: `logs/dialogue_{character_id}_{session_id}_{YYYY-MM-DD_HH:mm:ss}.log`。

## 12. 异常与失败处理

- API Key 缺失: 启动即报错，提示配置位置。
- JSON 解析失败: 启动自修复输出提示词重试 1-2 次。
- 字数不足: 追加补写指定节拍。
- 文件已存在且未 `--force`: 直接中止。
- 流式失败: 回退为非流式请求。
- 角色记忆更新 JSON 解析失败: 触发自修复重试 1-2 次，仍失败则跳过写回并记录告警。

## 13. 迁移步骤

1. 将 `prompting.py` 的提示词改造为 LangChain `ChatPromptTemplate`。
2. 新增 `parsers.py` 与 `validators.py`，封装 JSON 解析与校验。
3. 新增 `chains/` 目录，按阶段拆分链路。
4. 新建 `langchain_pipeline.py`，与现有 `ChapterPipeline` 并行运行对比。
5. 在 CLI 中增加切换开关（默认保持旧实现，灰度验证）。

## 14. 验收标准

- plan 与 post_check JSON 100% 可解析。
- 章节输出路径、命名、日志结构与现有保持一致。
- 计划、成稿、修订、终审均能在 LangChain 链路中复现。
- trace 日志可完整回放提示词与响应。
- 角色记忆更新 JSON 100% 可解析。
- 读者对话不包含未发布设定或大纲内容。
- 角色对话日志可回放、可按 session 回滚。

## 15. 角色对话与记忆子系统（LangGraph）

### 15.1 目标与边界

- 提供角色 agent 的长期记忆与读者对话能力，独立于主写作流水线。
- 读者对话仅引用已生成章节内容，不注入计划/大纲。
- 对话子系统仅面向读者交流，默认 reader 模式，不影响主写作链路（含角色贡献）。

### 15.2 规模与检索约束

- 角色规模 200+；每章平均出场约 5 人，仅对 `cast` 做记忆更新。
- 暂不引入向量检索，使用规则检索（最近章节、关系相关、最近对话）。

### 15.3 输入与上下文拼装

- 已发布章节正文: `chapters/**`
- 角色设定: `config/agents.yaml`
- 风格卡: `config/style_guide/**`
- 上一章摘要/状态: `data/state.json`
- 由链路负责确定性读取与注入，不依赖模型自行选择工具。

### 15.4 记忆数据结构与落盘

- `data/characters/{character_id}.json`
- `data/character_index.json`
- `data/chapter_events/{chapter_id}.json`
- `data/dialogues/{character_id}/{session_id}.json`

```
{
  "character_id": "c001",
  "profile": {
    "background": "...",
    "personality": ["..."],
    "speech_style": "...",
    "taboos": ["..."]
  },
  "goals": {
    "long_term": "...",
    "short_term": "..."
  },
  "relationships": [
    {"target_id": "c002", "relation": "盟友", "trust": 0.7, "tension": 0.2, "last_event": "..."}
  ],
  "beliefs": [
    {"topic": "...", "belief": "...", "confidence": 0.8, "evidence": ["chapter_012"]}
  ],
  "episode_memories": [
    {"chapter_id": "0012", "facts": ["..."], "feelings": ["..."], "decisions": ["..."], "consequences": ["..."]}
  ],
  "recent_dialogs": [
    {"with": "reader", "summary": "...", "chapter_scope": "0012"}
  ],
  "spoiler_guard": {"max_reveal_chapter": "0012"},
  "updated_at": "2025-01-01T00:00:00Z"
}
```

### 15.5 LangGraph 节点与流程

```
LoadContext
  -> RetrieveMemories(rule-based)
  -> GenerateReply
  -> MemoryUpdate(JSON)
  -> ValidateUpdate
  -> PersistState
  -> End
```

### 15.6 记忆更新与压缩

- 终审后运行角色事件提取，仅处理本章 `cast`。
- 事实写入 `episode_memories`，主观感受写入 `beliefs`，关系变化写入 `relationships`。
- 每 N 章生成角色长记忆摘要，归档旧条目，保留关键事件与关系变化。
- 默认 N=10；或当 `episode_memories` > 30 条时触发压缩。
- 压缩策略: 最近 N 章汇总 + 旧条目归档（保留索引与关键事件）。

### 15.7 并发与限流

- 角色贡献并发上限建议 3-5。
- 角色对话单会话串行，跨角色/多会话全局并发上限建议 2-4。
- 记忆写回需串行或加锁，避免冲突与回滚困难。

### 15.8 一致性校验与剧透防护

- 世界观一致性: 设定与规则不冲突。
- 战力体系一致性: 等级/能力不越级、不自相矛盾。
- 人设一致性: 性格、动机、口癖不漂移。
- 读者对话仅引用已生成章节内容，禁止引用计划/大纲/未发布设定。

### 15.9 可观测与回滚

- 每次对话记录输入上下文、输出正文、记忆增量与校验报告。
- 支持按 `session_id` 回滚角色记忆版本，便于分支实验。

### 15.10 节点映射与文件结构

- LoadContext: 读取已发布章节与对话上下文（`chapters/**`、`data/state.json`、`config/**`），对应 StyleGuideComposer 与配置读取逻辑。
- 读者模式固定: 对话子系统只读取已发布章节与状态，不进入模型推断。
- RetrieveMemories: 新增 MemoryStore，读取 `data/characters/**`、`data/chapter_events/**`、`data/dialogues/**`，规则检索最近章节与关系相关条目。
- GenerateReply: 复用 `src/prompting.py` 的角色提示词，改为 `ChatPromptTemplate`。
- MemoryUpdate: 新增 `MemoryUpdateParser`（与 Plan/PostCheck 同类结构化解析器）。
- ValidateUpdate: 复用 `validators.py` 的 JSON 与一致性校验规则，补充剧透防护。
- PersistState: 复用 Store 写入风格（PlanStore/StateStore 的落盘方式），新写入 `data/characters/**` 与 `data/dialogues/**`。
- Graph 入口: 与 `langchain_pipeline.py` 并行，作为独立子系统入口，不影响主写作流水线。

## 16. 附录：角色事件提取与记忆增量字段字典

### 16.1 章节角色事件提取 JSON（`data/chapter_events/{chapter_id}.json`）

- `chapter_id` (string, required): 章节编号。
- `cast` (array, required): 本章出场角色列表。
- `cast[].character_id` (string, required): 角色 ID。
- `cast[].events` (array, optional): 角色本章关键事件列表。
- `cast[].events[].fact` (string, required): 客观事实描述。
- `cast[].events[].impact` (string, optional): 对角色或剧情的影响。
- `cast[].emotions` (array, optional): 角色本章主要情绪词。
- `cast[].decisions` (array, optional): 角色关键决策。
- `cast[].consequences` (array, optional): 决策带来的后果。
- `cast[].relationship_changes` (array, optional): 关系变化列表。
- `cast[].relationship_changes[].target_id` (string, required): 关系对象角色 ID。
- `cast[].relationship_changes[].trust_delta` (number, optional): 信任变化值（-1.0 ~ 1.0）。
- `cast[].relationship_changes[].tension_delta` (number, optional): 紧张变化值（-1.0 ~ 1.0）。
- `cast[].relationship_changes[].event` (string, optional): 触发变化的事件描述。
- `cast[].tags` (array, optional): 主题标签（如“背叛/成长/牺牲”）。

### 16.2 角色记忆增量 JSON（MemoryUpdate 输出）

- `character_id` (string, required): 角色 ID。
- `append_episode_memories` (array, optional): 追加到 `episode_memories` 的条目。
- `append_episode_memories[].chapter_id` (string, required): 来源章节。
- `append_episode_memories[].facts` (array, required): 客观事实。
- `append_episode_memories[].feelings` (array, optional): 主观感受。
- `append_episode_memories[].decisions` (array, optional): 关键决策。
- `append_episode_memories[].consequences` (array, optional): 后果。
- `relationship_delta` (array, optional): 关系变化增量。
- `relationship_delta[].target_id` (string, required): 关系对象角色 ID。
- `relationship_delta[].relation` (string, optional): 关系描述。
- `relationship_delta[].trust_delta` (number, optional): 信任变化值。
- `relationship_delta[].tension_delta` (number, optional): 紧张变化值。
- `relationship_delta[].last_event` (string, optional): 触发事件摘要。
- `beliefs_delta` (array, optional): 信念变化增量。
- `beliefs_delta[].topic` (string, required): 主题。
- `beliefs_delta[].belief` (string, required): 新/变更的信念。
- `beliefs_delta[].confidence_delta` (number, optional): 置信度变化值。
- `beliefs_delta[].evidence` (array, optional): 证据章节列表。
- `recent_dialogs_append` (array, optional): 追加到 `recent_dialogs` 的对话摘要。
- `recent_dialogs_append[].with` (string, required): `reader`。
- `recent_dialogs_append[].summary` (string, required): 对话摘要。
- `recent_dialogs_append[].chapter_scope` (string, optional): 允许引用的章节范围。
- `spoiler_guard_update` (object, optional): 更新剧透边界。
- `spoiler_guard_update.max_reveal_chapter` (string, optional): 读者对话可引用的最晚章节。
- `updated_at` (string, optional): ISO 时间戳。

注: 未提供的字段视为无变化；对话子系统不得写入未发布设定或计划内容。
