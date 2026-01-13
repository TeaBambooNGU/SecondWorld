# 工程架构梳理

- 当前梳理时间: 2026-01-13 23:37:46

## 项目概览

- 项目定位: 本地 CLI 多 Agent 小说草稿生成流水线
- 主要能力: 章节计划生成、角色贡献汇总、导演成稿、修订与终审、状态记录
- 关键输出: `chapters/` 最新正文、`chapters/history/` 成稿/修订/终审归档（命名: 成稿/修订一/终审）、`data/plans/` 计划、`data/state.json` 进度与版本索引、`logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log` 追踪日志

## 工程逻辑梳理

### 入口与启动

- 入口文件/命令: `src/cli.py`，通过 `uv run python -m src.cli plan|chapter` 启动
- 启动流程概述: CLI 解析参数 -> 初始化 `ChapterPipeline` -> 执行计划或成稿流程

### 核心模块

- `src/pipeline.py`: 负责加载配置与素材，组织计划生成、角色贡献、成稿、修订、终审与状态落盘
- `src/prompting.py`: 组装导演计划/成稿/修订/终审提示词与风格提示语，风格提示语注入 system 提示词
- `src/deepseek_client.py`: 与 DeepSeek API 通讯，支持流式输出
- `src/config_loader.py`: 读取 YAML/文本配置与环境变量
- `src/utils.py`: 通用工具、角色画像合成与日志写入

### 依赖关系

- 外部依赖: `requests`、`pyyaml`、`python-dotenv`
- 内部依赖: `src` 下的 pipeline/prompting/config_loader/utils 相互协作

### 数据流/控制流

- 大纲 `config/outline.yaml` -> 计划 `data/plans/{chapter}.json`
- 计划提示词中的 Series outline 仅使用系列/世界观概要，不包含 chapters，章节种子单独传入
- 角色组件 `config/style_guide/components/{personality|background|identity}/*.md` + 角色配置 `config/agents.yaml`（主角/配角按角色名，龙套使用 archetype） -> 角色画像（含 traits）
- 角色画像 + 角色提示语 -> 角色贡献 -> 导演成稿 -> 修订（编辑复核 + 导演修订） -> 反AI高频词审核清理 -> 终审 -> 状态写入 `data/state.json`
- 成稿/修订/终审正文 -> 最新正文写入 `chapters/{chapter_id}_{slug}.md` -> 版本归档写入 `chapters/history/{chapter_id}_{slug}_成稿.md` / `chapters/history/{chapter_id}_{slug}_修订一.md` / `chapters/history/{chapter_id}_{slug}_终审.md` -> 版本索引写入 `data/state.json`
- 风格提示语由 `config/style_guide/anti_ai_rules.md`、`config/style_guide/agents/{角色名}.md`（主角/配角）与 `config/style_guide/agents/{暴烈型|谨慎型|仁善型|冷静型}.md`（龙套类）、`config/style_guide/agents/director/{plan|draft|revision|final}.md` 与 `config/style_guide/components/{type}/{id}.md` 组合后注入 system 提示词

### 成稿版本留存

- 最新版本: `chapters/{chapter_id}_{slug}.md`
- 历史版本: `chapters/history/{chapter_id}_{slug}_成稿.md`、`chapters/history/{chapter_id}_{slug}_修订一.md`、`chapters/history/{chapter_id}_{slug}_终审.md`
- 版本索引: `data/state.json` 记录版本路径、标签与生成时间

### 关键配置

- `config/project.yaml`: API、生成参数与路径
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
- `config/style_guide/components/`: 性格/背景/身份提示语
- `.env`: API Key（`DEEPSEEK_API_KEY`）

### 运行流程

- 运行步骤: plan 生成计划 -> chapter 生成成稿并可流式输出 -> 修订（编辑复核 + 导演修订） -> 反AI高频词审核清理 -> 终审（无条件执行） -> 每次成稿/修订/终审归档版本
- 异常/边界处理: 缺少 API Key 直接报错；章节文件已存在且未 `--force` 则中止
- 观测与日志: `--trace` 写入 `logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log`，章节状态写入 `data/state.json`

## 改动概要/变更记录

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
