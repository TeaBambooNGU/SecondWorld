# 变更记录

## 未发布
- 初始化多 Agent 小说草稿工具。
- 改用 uv 管理依赖，新增 `pyproject.toml` 并更新安装指引，移除 `requirements.txt`。
- 依赖改为不固定版本，改由 `uv add` 自行安装。
- 补充 `requires-python` 以消除 uv 提示。
- 更新 `docs/architecture.md` 并新增 LangChain 重构版设计文档。
- 补充 LangChain 重构设计文档中的角色 Agent 策略、模式与并发约束。
- 简化对话子系统为固定 reader 模式，移除对话模式参数与检测描述。
