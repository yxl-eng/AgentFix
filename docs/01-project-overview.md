# AgentFix 项目概览

AgentFix 是一个多语言 Web 服务自动修复 Agent。它把线上错误日志或 GitHub bug issue 转成结构化修复任务，自动完成代码定位、LLM 根因分析、补丁生成、验证、Draft PR 创建、修复记录生成和飞书通知。

## 工作流

```text
Webhook / GitHub Issue / Log Watch
  -> Read Log
  -> Read Code
  -> Analysis Agent
  -> Patch Agent
  -> Patch Engine
  -> Run Test / Service Verification
  -> GitHub Draft PR
  -> Repair Record
  -> Feishu Card
```

## 主要模块

- `cli.py`：命令入口，包含 `doctor`、`analyze`、`run`、`validate`、`pr`、`serve`。
- `agent_server.py`：常驻 Agent 服务，处理 webhook、GitHub issue、日志 watch、事件去重。
- `incident_ingest.py`：解析 Python traceback，并为其他语言日志保留 raw log。
- `repo_context.py`：收集仓库上下文，支持 `.py`、`.ts`、`.js`、`.java`、`.go` 等常见源码。
- `services/analysis.py`：LLM 根因分析阶段。
- `services/patching.py`：LLM 补丁生成阶段。
- `patch_engine.py`：应用完整文件补丁并执行 guardrails。
- `validator.py`：执行测试命令、启动服务、健康检查、验证请求和日志复扫。
- `publisher.py`：创建修复分支、commit、push、GitHub Draft PR。
- `repair_records.py`：写入 `records/<incident_id>.json` 和 `.md`。
- `feishu.py`：发送飞书群机器人交互卡片。
- `event_state.py`：使用 SQLite 记录事件处理状态，防止重复修复。

## 当前支持范围

- Python traceback 自动解析。
- 非 Python 服务的 raw log 输入。
- 常见源码文件定位：Python、Node/TypeScript、Java、Go、Ruby、PHP、Rust、C# 等。
- 已配置 target 的 webhook 事故上报。
- 已配置仓库的 GitHub `bug` issue 触发。
- 本地服务日志轮询 watch。
- GitHub Draft PR。
- 飞书群机器人通知。

## 交付产物

- Agent 逻辑代码在 `src/agentfix/`。
- 自动修复中间产物在 `.agentfix-artifacts/`。
- 事件去重状态在 `.agentfix-state/events.sqlite3`。
- 自动生成的修复记录在 `records/`。

## 重要限制

- 第一版目标仓库必须提前 clone 到本地，并在 `targets` 中配置 `repo_path`。
- webhook 不允许直接传 `repo_path` 或 `repo_url`。
- 非 Python 日志不保证完整结构化解析，主要依赖 raw log 和路径线索。
- 服务启动和验证请求需要在 target 配置中显式声明。
