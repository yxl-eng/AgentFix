# PatchPilot 环境与配置

## 1. Python 环境

推荐 Python 3.11+。

```powershell
cd C:\path\to\Feishu_code_reviewer
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

安装后应可执行：

```powershell
patchpilot doctor
python -m pytest -q
```

## 2. 凭据

PatchPilot 需要三类凭据，按使用场景配置：

```powershell
$env:ARK_API_KEY="your-model-key"
$env:GITHUB_TOKEN="your-github-token"
$env:FEISHU_WEBHOOK_URL="your-feishu-bot-webhook"
```

如果飞书机器人启用了签名校验：

```powershell
$env:FEISHU_WEBHOOK_SECRET="your-feishu-bot-secret"
```

也可以写入 `patchpilot.local.yaml`：

```yaml
openai:
  api_key: your-model-key

github:
  token: your-github-token

feishu:
  webhook_url: your-feishu-bot-webhook
  webhook_secret: your-feishu-bot-secret
```

`patchpilot.local.yaml` 已被 `.gitignore` 忽略，不应提交。

## 3. 基础配置

复制模板：

```powershell
copy patchpilot.yaml.example patchpilot.yaml
```

大模型配置示例：

```yaml
openai:
  model: deepseek-v3-2-251201
  api_key_env_var: ARK_API_KEY
  base_url: https://ark.cn-beijing.volces.com/api/v3
  transport: rest_chat_completions
  analysis_reasoning_effort: medium
  patch_reasoning_effort: high
```

GitHub 配置：

```yaml
github:
  token_env_var: GITHUB_TOKEN
  api_base_url: https://api.github.com
```

Guardrails：

```yaml
guardrails:
  max_changed_files: 3
  max_patch_lines: 250
  min_confidence: 0.45
  ignored_paths:
    - .git
    - .venv
    - .pytest_cache
    - __pycache__
    - node_modules
```

## 4. Target 配置

每个要被 Agent 修复的 Web 服务都必须配置成 target。

```yaml
targets:
  my-service:
    repo_full_name: owner/my-service
    repo_path: C:/path/to/my-service
    base_branch: main
    service_log_file: logs/app.log
    start_command: npm run dev
    working_dir: .
    healthcheck_url: http://localhost:3000/health
    test_commands:
      - npm test
    verification_requests:
      - method: GET
        url: http://localhost:3000/api/users/1
        expected_status: 200
```

字段说明：

- `repo_full_name`：GitHub webhook 匹配用，格式为 `owner/repo`。
- `repo_path`：目标仓库本地路径，必须提前 clone。
- `base_branch`：PR 目标分支。
- `service_log_file`：服务日志文件，相对 `repo_path`。
- `start_command`：修复后启动服务的命令。
- `working_dir`：启动命令工作目录，相对 `repo_path`。
- `healthcheck_url`：服务启动后的健康检查 URL。
- `test_commands`：修复后执行的测试命令。
- `verification_requests`：模拟用户请求，确认 bug 不再复现。

## 5. Agent 服务配置

```yaml
server:
  host: 0.0.0.0
  port: 8080
  poll_interval_seconds: 10
  state_path: .patchpilot-state/events.sqlite3
```

`state_path` 是事件去重库。重复的 `incident_id` 或 GitHub delivery 不会重复创建 PR。

## 6. Records 与飞书

```yaml
records:
  root: records
  auto_commit: true

feishu:
  webhook_url_env_var: FEISHU_WEBHOOK_URL
  webhook_secret_env_var: FEISHU_WEBHOOK_SECRET
```

`records.auto_commit: true` 会把本次修复记录提交到 PatchPilot 仓库，仅提交 `records/` 下本次新增或更新的记录文件。
