# AgentFix V3 测试指南

这份文档用于从头测试 V3：自动生成回归测试、修复复杂 FastAPI demo、创建 PR、写 records、发送飞书通知。

测试分三层，不要一上来就跑完整链路：

- AgentFix 本体测试：确认 CLI、配置、单元测试可用。
- Demo 服务测试：确认 `fastapi-order-service` 本身能启动、能复现 bug、能产生日志。
- 完整 Agent 流程测试：通过 webhook、watch 或 GitHub issue 触发自动修复。

## 1. 前置检查

在 AgentFix 仓库根目录执行：

```powershell
cd C:\Users\86137\Desktop\Feishu_code_reviewer
conda activate agentfix311
python -m pip install -e ".[dev]"
agentfix doctor
```

如果你把密钥写在 `agentfix.local.yaml`，正常直接运行 `agentfix doctor` 即可。默认加载顺序是：

1. 读取 `agentfix.yaml`
2. 如果存在 `agentfix.local.yaml`，再用它覆盖同名配置

不要只执行 `agentfix --config agentfix.local.yaml doctor`，除非这个文件里包含完整配置；否则它不会自动合并 `agentfix.yaml`。

`agentfix doctor` 重点看这些字段：

- `openai_api_key_present: true`：大模型 key 已配置。
- `github_token_present: true`：需要创建 PR 时必须为 true。
- `feishu_webhook_present: true`：需要飞书通知时必须为 true。
- `targets` 里包含 `fastapi-order-service`。
- `generated_test_targets` 里包含 `fastapi-order-service`。

## 2. 运行 AgentFix 本体测试

这一步只测试 AgentFix 自己的代码，不会创建 PR，也不会发飞书。

```powershell
python -m pytest -q
```

项目已经在 `pyproject.toml` 中配置了 `--basetemp=tmp-pytest`，所以 pytest 临时目录会固定创建在仓库根目录的 `tmp-pytest/`，不会默认写到 Windows 的 `%TEMP%`。`tmp-pytest/` 已加入 `.gitignore`，可以随时删除后重跑。

如果这里只失败在某个目标 demo 的业务测试，先确认你是在 AgentFix 根目录运行，而不是进入了 `demo_services/fastapi-order-service` 目录。

当前 `pyproject.toml` 已配置：

```toml
testpaths = ["tests"]
norecursedirs = ["tests/fixtures"]
```

所以正常情况下不会误收集 `tests/fixtures` 下面那些故意带 bug 的示例仓库。

## 3. 运行复杂 FastAPI Demo 服务

进入 demo 服务目录并安装它自己的依赖：

```powershell
cd C:\Users\86137\Desktop\Feishu_code_reviewer\demo_services\fastapi-order-service
python -m pip install -r requirements.txt
python -m pytest tests
```

这里的 `tests/` 是 demo 服务自带的基础测试，不是 Agent 自动生成的测试。它目前只覆盖健康检查、订单拥有者取消订单、订单拥有者查询订单，所以它会通过；真正的 bug 是“非订单拥有者取消订单时返回 500，而不是 403”，这个场景要由 V3 生成回归测试来覆盖。

启动 demo 服务：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8770
```

另开一个 PowerShell，检查健康接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8770/health
```

复现 demo bug：

```powershell
try {
  Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8770/orders/ord-100/cancel `
    -Headers @{ "X-User-Id" = "user-2" }
} catch {
  $_.Exception.Response.StatusCode.value__
}
```

修复前这里应该返回 `500`，并向 demo 仓库内的 `logs/app.log` 写入 traceback。

完成这一步后，先把 demo 服务停掉。后面 Agent 验证阶段会自己执行 `start_command` 启动服务，如果 8770 端口已经被你手动占用，验证会失败。

## 4. 准备完整 PR + 飞书链路

完整链路需要 demo 服务本身是一个 GitHub 仓库，并且 `agentfix.yaml` 里的 `repo_full_name` 指向真实仓库。

在 demo 服务目录内确认：

```powershell
git status
git remote -v
```

如果还没有远程仓库，需要你自己在 GitHub 创建一个仓库，然后：

```powershell
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

然后回到 AgentFix 根目录，修改 `agentfix.yaml`：

```yaml
targets:
  fastapi-order-service:
    repo_full_name: <owner>/<repo>
    repo_path: demo_services/fastapi-order-service
    base_branch: main
    service_log_file: logs/app.log
    start_command: uvicorn app.main:app --host 127.0.0.1 --port 8770
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
      fallback_to_v2_on_failure: true
```

密钥可以放在环境变量：

```powershell
$env:ARK_API_KEY="your-model-key"
$env:GITHUB_TOKEN="your-github-token"
$env:FEISHU_WEBHOOK_URL="your-feishu-bot-webhook"
```

也可以放在 `agentfix.local.yaml`：

```yaml
openai:
  api_key: your-model-key

github:
  token: your-github-token

feishu:
  webhook_url: your-feishu-bot-webhook
```

## 5. 用 Incident Webhook 测试完整 V3 流程

启动 AgentFix 服务：

```powershell
cd C:\Users\86137\Desktop\Feishu_code_reviewer
conda activate agentfix311
agentfix serve --host 127.0.0.1 --port 8080 --watch
```

另开一个 PowerShell，发送 incident webhook。最快方式是直接使用 demo 里预置的 traceback 文件：

```powershell
$body = @{
  target = "fastapi-order-service"
  incident_id = "fastapi-order-v3-001"
  log_file = "logs/incident.log"
  request_context = @{
    method = "POST"
    path = "/orders/ord-100/cancel"
    headers = @{
      "X-User-Id" = "user-2"
    }
  }
  expected_outcome = @{
    expected_status = 403
  }
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8080/webhooks/incidents `
  -ContentType application/json `
  -Body $body
```

也可以先按第 3 节真实复现一次 bug，然后把 `log_file` 改成：

```json
{
  "log_file": "logs/app.log"
}
```

注意：`log_file` 是相对目标仓库 `repo_path` 的路径，不是相对 AgentFix 根目录。

### 成功时应该看到什么

HTTP 返回里重点看：

- `status: pr_created`：验证通过，并且 GitHub Draft PR 创建成功。
- `status: validated`：修复和验证通过，但 PR 没创建成功，通常是 GitHub token、remote、repo_full_name 问题。
- `status: needs_manual_intervention`：模型补丁或验证没过，需要人工介入。
- `status: duplicate`：同一个 `incident_id` 已经处理过。

完整成功后会出现这些产物：

- GitHub 上出现一个 Draft PR。
- AgentFix 仓库出现 `records/<incident_id>.json`。
- AgentFix 仓库出现 `records/<incident_id>.md`。
- `.agentfix-artifacts/` 下出现本次分析、补丁、验证、PR 的中间产物。
- 飞书群收到卡片：“我发现了一个 Bug 并已为您修复，请 Review”。

V3 生成测试的关键字段在 record 里：

```json
{
  "generated_test": {
    "attempted": true,
    "framework": "pytest",
    "test_path": "tests/...",
    "prefix_failed": true,
    "postfix_passed": true,
    "committed": true,
    "fallback_reason": null
  }
}
```

含义是：

- `prefix_failed: true`：修复前，Agent 生成的测试确实失败。
- `postfix_passed: true`：修复后，同一个测试通过。
- `committed: true`：这个稳定的回归测试会和业务修复一起进入 PR。

如果 `fallback_reason` 有内容，说明生成测试阶段没有形成稳定闭环，Agent 会继续执行既有验证链路。

## 6. 测试 Watch 触发

`--watch` 的含义是：Agent 启动后记录每个 target 的日志文件当前位置，只处理之后新增的错误日志。

启动 Agent：

```powershell
agentfix serve --host 127.0.0.1 --port 8080 --watch
```

另开 PowerShell，把一段新错误追加到 demo 服务日志：

```powershell
cd C:\Users\86137\Desktop\Feishu_code_reviewer\demo_services\fastapi-order-service
Add-Content .\logs\app.log "`nrequest_id=watch-$(Get-Date -Format yyyyMMddHHmmss)"
Get-Content .\logs\incident.log -Raw | Add-Content .\logs\app.log
```

等待 `server.poll_interval_seconds`，默认 10 秒。Agent 会检测到新增文本里有 `Traceback`，自动触发修复。

如果你反复追加完全相同的日志，可能会被事件去重拦住。加一行新的 `request_id` 可以避免 hash 完全相同。

## 7. 测试 GitHub Bug Issue Webhook

这个测试不一定需要真的配置 GitHub webhook，可以本地模拟一次请求。

要求：

- `agentfix.yaml` 中 `targets.fastapi-order-service.repo_full_name` 必须等于 payload 里的 `repository.full_name`。
- issue 必须带 `bug` 标签。
- issue body 里要有 traceback 或错误日志。

PowerShell 示例：

```powershell
$issueBody = Get-Content `
  C:\Users\86137\Desktop\Feishu_code_reviewer\demo_services\fastapi-order-service\logs\incident.log `
  -Raw

$headers = @{
  "X-GitHub-Event" = "issues"
  "X-GitHub-Delivery" = "local-github-v3-001"
}

$body = @{
  action = "opened"
  repository = @{
    full_name = "<owner>/<repo>"
  }
  issue = @{
    number = 1
    title = "Bug: cancelling someone else's order returns 500"
    html_url = "https://github.com/<owner>/<repo>/issues/1"
    body = $issueBody
    labels = @(
      @{ name = "bug" }
    )
  }
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8080/webhooks/github `
  -Headers $headers `
  -ContentType application/json `
  -Body $body
```

如果你再次使用相同的 `X-GitHub-Delivery`，会返回 `duplicate`。要重新测试，改成新的 delivery id。

## 8. 事件去重和重新测试

事件 key 规则：

- incident webhook 优先使用 `incident_id`。
- GitHub webhook 优先使用 `X-GitHub-Delivery`。
- watch 使用新增日志内容 hash。

所以：

- 想重新跑一次 incident webhook，换一个新的 `incident_id`。
- 想重新跑一次 GitHub webhook，换一个新的 `X-GitHub-Delivery`。
- 想重新跑 watch，追加不完全相同的新日志。

如果你确实想清空去重库，先停止 Agent 服务，再删除：

```powershell
Remove-Item .agentfix-state\events.sqlite3
```

平时更推荐换 ID，不要频繁删状态库。

## 9. 常见问题

### `agentfix` 命令找不到

说明当前环境还没安装本项目：

```powershell
conda activate agentfix311
python -m pip install -e ".[dev]"
```

### 完整流程没有生成测试

检查：

- 触发方式是不是走 `agentfix serve` 的 target。当前 V3 生成测试依赖 target 配置；直接 `agentfix run --repo ...` 更适合做 V2 本地 smoke test。
- `targets.fastapi-order-service.generated_tests.enabled` 是否为 `true`。
- `record.generated_test.fallback_reason` 写了什么。

### PR 没创建

检查：

- demo 服务仓库是否有 GitHub `origin`。
- `repo_full_name` 是否是真实的 `<owner>/<repo>`。
- `GITHUB_TOKEN` 是否有目标仓库写权限。
- 本地 `main` 是否已经推到远程。

### 验证失败，提示端口占用

Agent 验证阶段会执行：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8770
```

如果你手动启动的 demo 服务还没停，8770 会被占用。先 Ctrl+C 停掉手动服务，再重新触发。

### 飞书没有收到通知

检查：

- `FEISHU_WEBHOOK_URL` 或 `feishu.webhook_url` 是否配置。
- 飞书机器人是否启用了签名校验；如果启用了，还要配置 `FEISHU_WEBHOOK_SECRET`。
- record 里的 `feishu_notified` 和 `Notify Feishu` tool call。

### 补丁被 guardrails 拦截

业务修复受全局限制控制：

```yaml
guardrails:
  max_changed_files: 5
  max_patch_lines: 500
```

生成测试文件有独立限制：

```yaml
generated_tests:
  max_files: 1
```

如果模型想改的文件数或行数超过限制，本次会进入失败或重试，不会强行提交大范围补丁。复杂 demo 可以适当把 `max_changed_files` 和 `max_patch_lines` 调大。

## 10. 最小验收清单

一次完整 V3 demo 至少满足：

- `agentfix doctor` 显示 target 和密钥配置正确。
- demo 服务原始 bug 能复现为 500。
- incident webhook 返回 `pr_created`，或者本地无 GitHub 条件时至少返回 `validated`。
- `records/<incident_id>.json` 中 `generated_test.prefix_failed` 为 `true`。
- `records/<incident_id>.json` 中 `generated_test.postfix_passed` 为 `true`。
- PR 中同时包含业务修复和生成的回归测试。
- 飞书卡片包含 PR 链接、验证状态、records 路径和 generated test 状态。
