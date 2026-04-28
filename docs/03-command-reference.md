# AgentFix 命令与 Webhook

## `agentfix doctor`

检查配置、依赖、凭据和 Agent 拓扑。

```powershell
agentfix doctor
```

## `agentfix analyze`

只做日志解析、代码上下文收集和 LLM 根因分析，不修改代码。

```powershell
agentfix analyze `
  --repo C:\path\to\target-repo `
  --log-file .\incident.log `
  --base-branch main
```

## `agentfix run`

执行完整单次修复流程：分析、补丁、验证、可选 PR。

```powershell
agentfix run `
  --repo C:\path\to\target-repo `
  --log-file .\incident.log `
  --base-branch main
```

只修复和验证，不创建 PR：

```powershell
agentfix run --repo C:\path\to\target-repo --log-file .\incident.log --no-pr
```

## `agentfix validate`

验证已有改动，不调用 LLM。

```powershell
agentfix validate --repo C:\path\to\target-repo --files src/app.ts
```

如果未传 `--files`，会读取目标仓库的 `git diff --name-only`。

## `agentfix pr`

基于已有 `repair-result.json` 创建 Draft PR。

```powershell
agentfix pr `
  --repo C:\path\to\target-repo `
  --report-file .agentfix-artifacts\20260427120000-demo\repair-result.json `
  --base-branch main
```

## `agentfix serve`

启动常驻 Agent 服务。

```powershell
agentfix serve --host 0.0.0.0 --port 8080 --watch
```

- `--host`：覆盖 `server.host`。
- `--port`：覆盖 `server.port`。
- `--watch`：启用 `targets.*.service_log_file` 轮询。

## HTTP 接口

健康检查：

```http
GET /health
```

事故 webhook：

```http
POST /webhooks/incidents
```

请求示例：

```json
{
  "target": "my-service",
  "incident_id": "demo-001",
  "log_text": "TypeError: Cannot read properties of undefined\n    at getUser (src/app.ts:10:5)"
}
```

也可以传 target 仓库内的日志文件：

```json
{
  "target": "my-service",
  "incident_id": "demo-002",
  "log_file": "logs/error.log"
}
```

安全约束：

- 不接受 `repo_path`。
- 不接受 `repo_url`。
- `log_file` 必须位于配置好的 target 仓库内部。

GitHub webhook：

```http
POST /webhooks/github
```

第一版只处理：

- `X-GitHub-Event: issues`
- `action` 为 `opened` 或 `labeled`
- issue 包含 `bug` 标签
- repository `full_name` 能匹配某个 `targets.*.repo_full_name`

## PowerShell 调用示例

```powershell
$body = @{
  target = "my-service"
  incident_id = "demo-001"
  log_text = "TypeError: boom at src/app.ts:10"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8080/webhooks/incidents `
  -ContentType application/json `
  -Body $body
```

## 验证流程

当 target 配置了验证项，Agent 会按顺序执行：

1. `test_commands`
2. `start_command`
3. `healthcheck_url`
4. `verification_requests`
5. 扫描 `service_log_file` 新增内容，确认同类错误没有再次出现
6. 停止服务进程

若没有可执行验证，修复结果会更偏向人工确认。

## 输出状态

- `pr_created`：修复通过验证并创建 Draft PR。
- `validated`：修复通过验证，但没有创建 PR。
- `needs_human_verification`：基础流程成功，但缺少足够服务级验证。
- `needs_manual_intervention`：分析置信度不足、补丁失败或重试耗尽。
- `failed`：Agent 服务处理事件时发生未恢复错误。

## 修复记录

每次事件会生成：

```text
records/<incident_id>.json
records/<incident_id>.md
```

记录内容包括事件来源、根因、改动文件、PR URL、验证命令、飞书通知结果和 Tool Use 链路。
