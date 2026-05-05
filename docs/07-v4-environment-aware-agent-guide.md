# PatchPilot V4 环境感知 Agent 使用指南

## 1. V4 做了什么

PatchPilot V4 把原来的固定自动修复流水线升级为“先分诊，再选择工具，最后修复或报告”的环境感知 Agent。

旧流程是：

```text
收到日志 -> 分析 -> 改代码 -> 验证 -> PR -> 飞书
```

V4 流程是：

```text
收到日志 -> Incident Planner 分诊 -> 选择工具计划 -> 忽略 / 只报告 / 自动修复
```

新增能力：

- `Incident Planner`：先判断日志是否值得处理。
- 四类对外状态：
  - `ignored`：日志包含 error，但属于预期业务/客户端错误，不修复。
  - `needs_manual_intervention`：确认异常，但更像环境、配置、数据、外部依赖或多轮修复失败，不盲目改代码。
  - `needs_human_verification`：代码补丁通过语法/编译检查，但自动生成的回归测试未通过，需要人工确认。
  - `fixed`：确认像代码 Bug，已自动生成补丁、完成验证，并在条件满足时创建 Draft PR。
- records 升级：每次事件都写 JSON 和 Markdown，包含分诊结论、证据、工具计划、根因类型、人工处理建议。
- 桌面控制台：基于 `gui.py`，支持事故查看、配置编辑、目标服务管理和手动运行。
- 订单履约运营服务：提供可交互页面，通过页面操作触发线上风格 traceback。

## 2. 环境配置

推荐 Python 3.11。

```powershell
conda activate patchpilot311
python -m pip install -e ".[dev]"
```

检查环境：

```powershell
patchpilot doctor
```

如果 `patchpilot` 命令不可用，可以使用：

```powershell
python -m patchpilot doctor
```

需要的环境变量：

```powershell
$env:ARK_API_KEY="你的模型 Key"
$env:GITHUB_TOKEN="你的 GitHub Token"
$env:FEISHU_WEBHOOK_URL="你的飞书机器人 Webhook"
```

如果飞书机器人配置了签名校验，还需要：

```powershell
$env:FEISHU_WEBHOOK_SECRET="你的飞书机器人 Secret"
```

## 3. 配置文件说明

默认读取：

```text
patchpilot.yaml
patchpilot.local.yaml
```

`patchpilot.local.yaml` 会覆盖 `patchpilot.yaml`，适合放本机密钥、本地路径和真实 GitHub 仓库名。

V4 新增配置：

```yaml
agent:
  planner:
    enabled: true
    max_steps: 8
    allowed_tools:
      - Read Log
      - Inspect Config
      - Check Runtime
      - Search Similar Fixes
      - Read Code
      - Generate Regression Test
      - Run Test
      - Git Commit
      - Record Repair
      - Notify Feishu
  risk:
    max_changed_files: 6
    max_changed_lines: 600
  report:
    notify_on_ignored: false
    notify_on_report_only: true
    notify_on_needs_more_context: true
```

含义：

- `planner.enabled`：是否启用环境感知分诊。
- `planner.allowed_tools`：Planner 可以选择的工具范围。
- `risk.max_changed_files`：自动修复最多修改几个业务文件。
- `risk.max_changed_lines`：自动补丁最多修改多少行。
- `report.notify_on_ignored`：忽略噪声日志时是否发飞书。
- `report.notify_on_report_only`：只生成报告时是否发飞书。
- `report.notify_on_needs_more_context`：信息不足时是否发飞书。

目标服务示例：

```yaml
targets:
  order-fulfillment-service:
    repo_full_name: yxl-eng/GuardianAI_Demo2
    repo_path: demo_services/fastapi-order-service
    base_branch: main
    service_log_file: logs/app.log
    start_command: uvicorn app.main:app --host 127.0.0.1 --port 8770
    working_dir: .
    healthcheck_url: http://127.0.0.1:8770/health
    test_commands:
      - python -m pytest tests
    verification_requests:
      - method: GET
        url: http://127.0.0.1:8770/health
        expected_status: 200
    generated_tests:
      enabled: true
      framework: auto
      commit_when_stable: true
```

目标 Web 服务要求：

- 必须提前 clone 到本地，并配置 `repo_path`。
- 如果要创建 PR，目标仓库必须有 GitHub remote，并配置 `repo_full_name`。
- 推荐提供 `test_commands`，例如 `python -m pytest tests`、`npm test`、`go test ./...`。
- 推荐提供 `start_command` 和 `healthcheck_url`，Agent 修复后可以启动服务验证。
- 推荐提供 `service_log_file`，用于 `--watch` 轮询新增错误。

## 4. 启动桌面控制台

```powershell
python gui.py
```

桌面控制台包含：

- 总览：事件统计、最近事故、配置风险。
- 事故记录：分诊结论、根因类型、证据、工具调用、PR、人工建议。
- 配置中心：模型、GitHub、飞书、Planner、风控、server、records、全局验证命令。
- 目标服务：本地仓库、GitHub 仓库名、启动命令、测试命令、健康检查、接口验证请求和自动生成回归测试。
- 手动运行：选择本地仓库和日志文件，触发一次修复。

保存配置时会写入：

```text
patchpilot.local.yaml
```

不会直接覆盖 `patchpilot.yaml`。`server.host`、`server.port`、`server.state_path` 这类服务级配置保存后建议重启 PatchPilot 才能完全生效。

## 5. 启动 PatchPilot 服务

```powershell
patchpilot serve --host 127.0.0.1 --port 8080 --watch
```

健康检查：

```text
http://127.0.0.1:8080/health
```

## 6. 启动订单履约运营服务

进入订单履约服务目录：

```powershell
cd demo_services\fastapi-order-service
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8770
```

打开：

```text
http://127.0.0.1:8770/
```

页面操作：

1. 选择 `user-2`。
2. 找到订单 `ord-200`。
3. 点击 `取消`。
4. 页面返回 HTTP 500。
5. `logs/app.log` 写入 traceback。

这个 Bug 的真实语义是：

- `ord-200` 是已支付的旧订单。
- 正确行为应该是返回 HTTP 409，并要求走退款流程。
- 现在代码先释放库存，再判断已支付状态。
- 旧订单缺少 `inventory_hold` 字段，所以抛出 `KeyError: 'inventory_hold'`。

## 7. 触发 PatchPilot

### 方式 A：watch 自动触发

先启动 PatchPilot：

```powershell
patchpilot serve --host 127.0.0.1 --port 8080 --watch
```

再在订单履约运营台点击触发错误。PatchPilot 会轮询 `logs/app.log`，发现新增 traceback 后自动处理。

### 方式 B：incident webhook 触发

也可以把日志主动发给 PatchPilot：

```powershell
$body = @{
  target = "order-fulfillment-service"
  incident_id = "fastapi-order-v4-001"
  log_text = Get-Content "demo_services\fastapi-order-service\logs\app.log" -Raw
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8080/webhooks/incidents `
  -ContentType "application/json" `
  -Body $body
```

## 8. 如何观察结果

查看桌面控制台：

```powershell
python gui.py
```

查看 records：

```text
records/<incident_id>.json
records/<incident_id>.md
```

成功修复时会看到：

- `status: fixed`
- `disposition: repair_attempt`
- `root_cause_type: code`
- `tool_plan` 包含 `Read Code`、`Generate Regression Test`、`Run Test`、`Git Commit`
- GitHub Draft PR 链接
- 飞书卡片：“PatchPilot 已修复一个 Bug，请 Review”

只报告时会看到：

- `status: needs_manual_intervention`
- `disposition: report_only`
- `human_action_required: true`
- `human_resolution_steps` 给出人工处理建议
- 不创建 PR

忽略噪声时会看到：

- `status: ignored`
- `disposition: ignored`
- 不调用修复流水线
- 默认不发飞书

## 9. 常见问题

### 为什么没有创建 PR？

常见原因：

- Planner 判断为需要人工处理或已忽略。
- 验证失败。
- GitHub Token 缺失。
- 目标仓库没有 remote。
- 超出 `agent.risk` 或 `guardrails` 限制。

### 为什么只生成报告？

说明 Agent 认为它不是安全的代码修复问题。比如：

- Redis、数据库、外部接口连接失败。
- 环境变量缺失。
- 数据库约束或生产脏数据问题。
- 日志信息不足，无法安全定位代码。

### `verification_requests` 必须提前写吗？

V4 仍然建议提前写。它是“业务服务启动后的一组稳定探针”，不是针对每个 bug 临时生成的测试。针对本次 bug 的临时复现由 `generated_tests` 负责。

### generated test 没有提交进 PR 是为什么？

只有满足下面条件才会提交：

- 能识别测试框架。
- Agent 生成了测试文件。
- 修复前该测试失败，且失败和 incident 相关。
- 修复后该测试通过。
- `generated_tests.commit_when_stable: true`。

否则会继续执行既有验证链路，不把不稳定测试提交进 PR。
