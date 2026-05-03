# AgentFix

AgentFix 是一个面向 Web 服务仓库的环境感知自动修复 Agent。它可以接收服务报错日志、GitHub `bug` issue 或本地日志 watch 事件，先判断是否值得处理，再选择工具读取日志、代码和运行环境，最后自动修复并创建 PR，或生成清晰的人类处理报告。

成功修复时，AgentFix 会通过飞书卡片通知开发者：

> 我发现了一个 Bug 并已为您修复，请 Review

## 核心能力

- **Incident Planner**：把事件分诊为 `ignored`、`reported`、`needs_more_context` 或 `repair_attempt`。
- **Read Log**：读取 webhook payload、日志文件、GitHub issue body 或 watch 到的新增日志。
- **Read Code**：根据 traceback、`path:line`、错误 token 和仓库结构定位候选源码。
- **Generate Regression Test**：根据 incident 生成回归测试，要求修复前失败、修复后通过才提交进 PR。
- **Run Test / Verification**：运行测试命令、启动服务、健康检查、验证请求，并扫描新日志。
- **Git Commit / PR**：验证通过后创建修复分支、commit、push 和 GitHub Draft PR。
- **Record Repair**：写入 `records/<incident_id>.json` 和 `.md`。
- **Notify Feishu**：发送中文飞书机器人交互卡片。
- **桌面控制台**：通过 `python gui.py` 打开本地应用，查看事故、编辑配置和管理目标服务。

## 安装

推荐 Python 3.11+。

```powershell
python -m pip install -e ".[dev]"
```

检查环境：

```powershell
agentfix doctor
```

如果命令不可用：

```powershell
python -m agentfix doctor
```

## 配置

复制配置模板：

```powershell
copy agentfix.yaml.example agentfix.yaml
```

敏感配置建议写入 `agentfix.local.yaml`，它会覆盖 `agentfix.yaml`。

需要的环境变量：

```powershell
$env:ARK_API_KEY="your-model-key"
$env:GITHUB_TOKEN="your-github-token"
$env:FEISHU_WEBHOOK_URL="your-feishu-bot-webhook"
```

如果飞书机器人开启签名校验，还需要：

```powershell
$env:FEISHU_WEBHOOK_SECRET="your-feishu-bot-secret"
```

## 桌面控制台

启动桌面应用：

```powershell
python gui.py
```

桌面控制台支持：

- 总览：事件统计、最近事故、配置风险。
- 事故记录：查看分诊结论、根因类型、证据、工具调用、PR 和人工建议。
- 配置中心：编辑模型、GitHub、飞书、Planner、风控、server、records、全局验证命令；密钥默认隐藏，可点击“预览”临时查看。
- 目标服务：编辑本地仓库、GitHub 仓库名、启动命令、测试命令、健康检查、接口验证请求和自动生成回归测试配置。
- 手动运行：选择本地仓库和日志文件，触发一次 AgentFix 修复。

GUI 保存配置时会写入 `agentfix.local.yaml`，不会直接覆盖 `agentfix.yaml`。
GUI 使用桌面 Tkinter，不需要也不会启动网页控制台。

## 启动 Agent 服务

启动 webhook 服务和日志 watch：

```powershell
agentfix serve --host 127.0.0.1 --port 8080 --watch
```

健康检查：

```text
http://127.0.0.1:8080/health
```

发送 incident webhook：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8080/webhooks/incidents `
  -ContentType application/json `
  -Body '{"target":"fastapi-order-service","incident_id":"order-incident-001","log_text":"TypeError: boom at app/services.py:42"}'
```

## 订单履约运营服务

订单履约运营服务位于：

```text
demo_services/fastapi-order-service
```

启动：

```powershell
cd demo_services\fastapi-order-service
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8770
```

打开：

```text
http://127.0.0.1:8770/
```

切换处理身份、查看订单和库存，然后执行取消订单或退款申请。异常会按线上业务日志格式写入 `logs/app.log`，随后 AgentFix 可以通过 `--watch` 或 incident webhook 自动处理。

## 文档

- [项目概览](docs/01-project-overview.md)
- [环境与配置](docs/02-environment-setup.md)
- [命令与 Webhook](docs/03-command-reference.md)
- [V3 自动生成回归测试](docs/04-generated-regression-tests.md)
- [V3 测试指南](docs/05-v3-testing-guide.md)
- [V4 环境感知 Agent 使用指南](docs/07-v4-environment-aware-agent-guide.md)

## 输出产物

- `.agentfix-artifacts/`：每次修复的中间产物、补丁、验证结果和报告。
- `.agentfix-state/events.sqlite3`：事件去重状态库。
- `records/`：Agent 自动生成的修复记录和报告，适合复盘和审计。

## 安全边界

- webhook 不接受任意 `repo_path` 或 `repo_url`。
- 只处理 `agentfix.yaml` 中显式配置的 target。
- `Git Commit` 只在验证通过且 Planner 允许时执行。
- 自动补丁受最大文件数和最大行数限制。
- 环境、配置、外部依赖、生产数据问题会生成报告，而不是盲目改代码。
