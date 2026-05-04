# PatchPilot 命令与 Webhook

## `patchpilot doctor`

检查配置、依赖、凭据和 Agent 拓扑。

```powershell
patchpilot doctor
```

## `patchpilot analyze`

只做日志解析、代码上下文收集和 LLM 根因分析，不修改代码。

```powershell
patchpilot analyze `
  --repo C:\path\to\target-repo `
  --log-file .\incident.log `
  --base-branch main
```

## `patchpilot run`

执行完整单次修复流程：分析、补丁、验证、可选 PR。V5 会进入 Iterative Repair Loop，默认最多 3 轮，根据验证反馈继续修正补丁。

```powershell
patchpilot run `
  --repo C:\path\to\target-repo `
  --log-file .\incident.log `
  --base-branch main
```

只修复和验证，不创建 PR：

```powershell
patchpilot run --repo C:\path\to\target-repo --log-file .\incident.log --no-pr
```

## `patchpilot validate`

验证已有改动，不调用 LLM。

```powershell
patchpilot validate --repo C:\path\to\target-repo --files src/app.ts
```

如果未传 `--files`，会读取目标仓库的 `git diff --name-only`。

## `patchpilot pr`

基于已有 `repair-result.json` 创建 Draft PR。

```powershell
patchpilot pr `
  --repo C:\path\to\target-repo `
  --report-file .patchpilot-artifacts\20260427120000-demo\repair-result.json `
  --base-branch main
```

## `patchpilot serve`

启动常驻 Agent 服务。

```powershell
patchpilot serve --host 0.0.0.0 --port 8080 --watch
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

若没有可执行验证，修复结果会更偏向人工处理报告。

## 输出状态

- `fixed`：修复已验证通过；是否创建 PR 看 `pr_url` 字段。
- `needs_human_verification`：语法/编译检查通过，但自动生成的回归测试样例没有通过，需要人工确认。
- `needs_manual_intervention`：配置、环境、数据、外部依赖、信息不足、补丁越界或多轮修复失败。
- `ignored`：Planner 判断为预期日志、噪声或无需处理的事件。

旧记录中的 `pr_created`、`validated` 会在 GUI 和报告中展示为 `fixed`；`reported`、`needs_more_context` 会展示为 `needs_manual_intervention`。

## 修复记录

每次事件会生成：

```text
records/<incident_id>.json
records/<incident_id>.md
```

记录内容包括事件来源、根因、改动文件、PR URL、验证命令、飞书通知结果和 Tool Use 链路。
