# AgentFix

AgentFix 是一个面向 Web 服务仓库的自动修复 Agent。它可以接收服务报错日志或 GitHub `bug` issue，读取目标仓库代码，调用大模型分析根因，生成最小补丁，运行测试和服务验证，创建 GitHub Draft PR，并通过飞书卡片通知开发者：

> 我发现了一个 Bug 并已为您修复，请 Review

当前版本保留原有 CLI 能力，同时新增常驻 Agent 服务。

## 核心能力

- **Read Log**：读取 webhook 上报日志、日志文件、GitHub issue body、watch 到的新日志。
- **Read Code**：根据 traceback、`path:line`、错误 token、最近变更定位候选源码文件。
- **Analyze + Patch**：通过 LLM 输出根因分析和完整文件补丁。
- **Run Test / Verification**：运行测试命令，启动服务，健康检查，执行验证请求，扫描新增日志。
- **Git Commit / PR**：创建修复分支、提交代码、推送并创建 GitHub Draft PR。
- **Record Repair**：在 AgentFix 仓库写入 `records/<incident_id>.json` 和 `.md` 修复记录。
- **Notify Feishu**：发送飞书群机器人交互卡片。

## 安装

需要 Python 3.11+。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

复制配置：

```powershell
copy agentfix.yaml.example agentfix.yaml
```

设置凭据：

```powershell
$env:ARK_API_KEY="your-model-key"
$env:GITHUB_TOKEN="your-github-token"
$env:FEISHU_WEBHOOK_URL="your-feishu-bot-webhook"
```

也可以把敏感配置写入 `agentfix.local.yaml`，该文件已被 `.gitignore` 忽略。

## 快速运行

环境自检：

```powershell
agentfix doctor
```

原有单次修复：

```powershell
agentfix run --repo C:\path\to\target-repo --log-file .\incident.log --base-branch main
```

启动常驻 Agent：

```powershell
agentfix serve --host 0.0.0.0 --port 8080 --watch
```

上报事故：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8080/webhooks/incidents `
  -ContentType application/json `
  -Body '{"target":"my-service","incident_id":"demo-001","log_text":"TypeError: boom at src/app.ts:10"}'
```

## 配置示例

```yaml
targets:
  my-service:
    repo_full_name: owner/my-service
    repo_path: C:/path/to/my-service
    base_branch: main
    service_log_file: logs/app.log
    start_command: npm run dev
    healthcheck_url: http://localhost:3000/health
    test_commands:
      - npm test
    verification_requests:
      - method: GET
        url: http://localhost:3000/api/users/1
        expected_status: 200
```

第一版只处理已配置的 `targets`，不接受 webhook 传入任意 `repo_path` 或 `repo_url`。目标仓库需要提前 clone 到本地。

## 文档

- [项目概览](docs/01-project-overview.md)
- [环境与配置](docs/02-environment-setup.md)
- [命令与 Webhook](docs/03-command-reference.md)
- [V3 自动生成回归测试](docs/04-generated-regression-tests.md)
- [V3 测试指南](docs/05-v3-testing-guide.md)

## 输出产物

- `.agentfix-artifacts/`：每次修复的中间产物、补丁、验证结果、最终报告。
- `.agentfix-state/events.sqlite3`：事件去重状态库。
- `records/`：Agent 自动生成的修复记录，适合作为交付物和演示材料。

## 安全边界

- webhook 不允许传任意仓库路径或 GitHub 链接。
- 只有 `agentfix.yaml` 中配置过的 target 会被处理。
- 依赖文件默认禁止被自动补丁修改。
- 自动补丁受最大文件数和最大补丁行数限制。
