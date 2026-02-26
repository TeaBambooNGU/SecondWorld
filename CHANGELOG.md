# 变更记录

## 未发布
- 连续性上下文注入阶段调整为计划阶段：读取已生成章节时前 3 章注入全文，其余章节注入剧情摘要以提升剧情连贯性。
- 可选世界观参考注入范围调整为仅计划/成稿/编辑复核阶段，修订与终审阶段不再注入。
- 新增剧情摘要持久化缓存 `data/chapter_plot_summaries.json`（可通过 `paths.plot_summary_cache_path` 配置），已存在摘要优先复用，避免重复生成。
- 新增世界观素材筛选链路：可配置 `paths.world_materials_dir`，由独立“素材筛选 Agent”批量决策迁移全篇或节选到 `data/world_refs/{chapter_id}/`，超出输入预算时自动分批，写作 Agent 仅读取缓存内容以降低噪音。
- 世界观素材读取新增过滤规则配置 `paths.world_materials_exclude_patterns`，并固定只扫描素材目录当前层级（不递归子目录）。
- 初始化多 Agent 小说草稿工具。
- 改用 uv 管理依赖，新增 `pyproject.toml` 并更新安装指引，移除 `requirements.txt`。
- 依赖改为不固定版本，改由 `uv add` 自行安装。
- 补充 `requires-python` 以消除 uv 提示。
- 更新 `docs/architecture.md` 并新增 LangChain 重构版设计文档。
- 补充 LangChain 重构设计文档中的角色 Agent 策略、模式与并发约束。
- 简化对话子系统为固定 reader 模式，移除对话模式参数与检测描述。
- 架构文档新增 LangSmith 跟踪与环境变量示例。
- 当设置 LANGSMITH_API_KEY 且未显式配置 LANGSMITH_TRACING 时默认开启追踪。
