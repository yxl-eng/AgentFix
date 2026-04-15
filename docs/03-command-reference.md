# AgentFix 命令行功能文档

> 基于 `cli.py`、`repair_orchestrator.py`、`validator.py`、`publisher.py` 源码精确梳理

---

## 全局选项

| 参数 | 说明 |
|------|------|
| `--config <path>` | 指定配置文件路径（默认自动查找 `agentfix.yaml`） |

---

## 1. `agentfix doctor`

### 功能
**环境自检命令** — 检查运行时配置、Agent 拓扑、凭据状态、依赖安装情况，不执行任何修复操作。

### 是否需要凭据
**不需要** API Key 或 GitHub Token

### 执行流程
1. 加载 `agentfix.yaml` 配置
2. 收集以下信息并输出 JSON 报告：
   - 配置文件路径
   - Agent 拓扑图（各组件类名）
   - 完整工作流步骤列表
   - 当前配置值（模型、URL、Guardrails 参数等）
   - 凭据检测（API Key / Token 是否存在）
   - Python 版本 & 核心模块是否可用
   - 各命令的凭据需求说明

### 用法

```bash
agentfix doctor
```

### 预期输出（JSON）

```json
{
  "config_path": "/path/to/agentfix.yaml",
  "agent_topology": {
    "orchestrator": "RepairOrchestrator",
    "analysis_agent": "AnalysisAgent",
    "patch_agent": "PatchAgent",
    "validator": "Validator",
    "publisher": "GitHubPublisher",
    "model_provider": "OpenAIResponsesProvider"
  },
  "workflow": [
    "ingest incident log",
    "collect repo context",
    "analysis agent produces root cause and candidate files",
    "patch agent produces minimal file updates",
    "patch engine enforces guardrails",
    "validator runs py_compile and optional pytest",
    "publisher creates branch, commit, push, and GitHub Draft PR"
  ],
  "configuration": {
    "default_model": "deepseek-v3-2-251201",
    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "transport": "rest_chat_completions",
    "analysis_reasoning_effort": "medium",
    "patch_reasoning_effort": "high",
    "validation_python": "/.../python3",
    "max_changed_files": 3,
    "max_patch_lines": 250
  },
  "credentials": {
    "openai_api_key_env_var": "ARK_API_KEY",
    "openai_api_key_present": true,
    "github_token_env_var": "GITHUB_TOKEN",
    "github_token_present": true
  },
  "runtime_checks": {
    "python_version": "3.14.x",
    "modules": {
      "openai": true,
      "pydantic": true,
      "yaml": true,
      "pytest": true
    }
  },
  "command_requirements": {
    "doctor": "no model key required",
    "validate": "no model key required",
    "pr": "requires GitHub token for actual PR creation",
    "analyze": "requires OpenAI API key",
    "run": "requires OpenAI API key and GitHub token unless --no-pr is used"
  }
}
```

### 退出码
始终返回 `0`

---

## 2. `agentfix analyze`

### 功能
**根因分析命令** — 解析日志 + 收集仓库上下文 + 调用 LLM 分析根因，**只读分析，不修改任何代码**。

### 是否需要凭据
**需要** OpenAI API Key（调用 LLM 做分析）

### 参数

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--repo` | 是 | - | 目标仓库路径 |
| `--log-file` | 是 | - | Traceback 日志文件路径 |
| `--base-branch` | 否 | `main` | 用于收集上下文的基准分支 |

### 执行流程

```
日志文件 → IncidentIngestor.parse_log() → Incident 结构化对象
                                              │
                         RepoContextCollector.collect() ← repo_path + incident + base_branch
                                              │
                                         RepoContext
                           （候选文件列表 + 仓库元数据 + 测试候选列表）
                                              │
                              AnalysisAgent.analyze() ← LLM 第一阶段调用
                                              │
                                       AnalysisResult
                          （根因摘要、置信度、候修目标、修复计划、验证关注点）
```

### 用法

```bash
agentfix analyze \
  --repo ./tests/fixtures/key_error_repo \
  --log-file ./tests/fixtures/logs/key_error.log \
  --base-branch main
```

### 预期输出（JSON）

```json
{
  "incident": {
    "service_name": "config-api",
    "environment": "prod",
    "exception_type": "KeyError",
    "exception_message": "'user_id'",
    "stack_frames": [...],
    "suspected_module": "config",
    "incident_id": "key_error"
  },
  "analysis": {
    "root_cause_summary": "...",
    "confidence": 0.95,
    "candidate_targets": [
      {
        "path": "app/config.py",
        "rationale": "...",
        "confidence": 0.95,
        "change_summary": "..."
      }
    ],
    "repair_plan": ["...", "..."],
    "validation_focus": ["...", "..."],
    "additional_notes": ["..."]
  },
  "candidates": [
    {
      "relative_path": "app/config.py",
      "absolute_path": "/full/path/to/app/config.py",
      "score": 183.0,
      "reasons": ["exact traceback path match", ...],
      "excerpt": "def read_user_id(payload):\n    return payload[\"user_id\"]",
      "full_content": "..."
    }
  ]
}
```

### 退出码
始终返回 `0`

### 典型使用场景
- 初次排查事故，想先看 LLM 对根因的判断
- 不确定是否要自动修复，先做分析确认方向
- 调试 LLM 输出质量，调整 `analysis_reasoning_effort`

---

## 3. `agentfix run`

### 功能
**完整修复流水线** — 从日志解析到 Draft PR 创建的全自动端到端修复。

### 是否需要凭据
- **必须**: OpenAI API Key（两阶段 LLM 调用）
- **条件**: GitHub Token（不加 `--no-pr` 时需要）

### 参数

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--repo` | 是 | - | 目标仓库路径 |
| `--log-file` | 是 | - | Traceback 日志文件路径 |
| `--base-branch` | 否 | `main` | PR 的目标基准分支 |
| `--no-pr` | 否 | false | 跳过 PR 创建，只做到验证通过 |

### 完整执行流程

```
Step 1: 解析日志
  IncidentIngestor.from_file(log_file)
  -> Incident (异常类型、堆栈帧、服务名等)
       |
       v
Step 2: 创建产物目录
  .agentfix-artifacts/{timestamp}-{incident_id}/
       |
       v
Step 3: 收集仓库上下文
  RepoContextCollector.collect(repo, incident)
  -> RepoContext (候选文件 + Git 元数据)
       |
       v
Step 4: LLM 根因分析 (第一阶段)
  AnalysisAgent.analyze(incident, context)
  -> AnalysisResult
  写入: artifact_dir/analysis.json
       |
       v
  [置信度检查]
  confidence < min_confidence (默认 0.45)?
     Yes --> 立即终止, status = needs_manual_intervention
     No  --> 继续下一步
       |
       v
Step 5: 修复循环 (最多 max_repair_attempts 次, 默认 2)

  循环 attempt = 1..N:

  a) 复制仓库到临时目录 (不污染源仓库)
  b) LLM 补丁生成 (第二阶段)
     PatchAgent.propose(incident, analysis, feedback)
     -> PatchProposal
     写入: attempt-{n}-proposal.json

  c) 应用补丁 + Guardrails 安全检查
     PatchEngine.apply(proposal, allowed_paths)
     检查:
       - 文件数 <= max_changed_files (默认 3)
       - 行数 <= max_patch_lines (默认 250)
       - 路径在白名单内
     写入: attempt-{n}.patch

  d) 验证 (compile + test)
     Validator.validate(workspace, changed_files)
     - py_compile 所有改动 .py 文件
     - pytest (如有 tests/ 目录)
     写入: attempt-{n}-validation.json

  e) 验证通过?
     Yes --> 跳出循环，进入发布
     No  --> 将错误信息作为 feedback 重试
       |
       v (验证通过)
Step 6: 发布 (publish=true 且未加 --no-pr)
  GitHubPublisher.publish():
    1) git checkout -B agentfix/{id}/{error-type}
    2) git add changed_files
    3) git commit -m "fix: auto-repair ..."
    4) git push -u origin {branch}
    5) POST /repos/{owner}/{repo}/pulls (Draft PR)
  写入: attempt-{n}-pr.json

  若 publish=false (--no-pr):
    跳过此步, status = "validated"
       |
       v
Step 7: 输出最终结果
  RepairResult (JSON)
  同时写入:
    artifact_dir/repair-result.json (JSON 格式)
    artifact_dir/repair-report.md  (Markdown 报告)
```

### 用法

```bash
# 完整流程（含 PR 创建）
agentfix run \
  --repo /path/to/your/repo \
  --log-file ./error.log \
  --base-branch main

# 只做修复和验证，不建 PR
agentfix run \
  --repo /path/to/your/repo \
  --log-file ./error.log \
  --base-branch main \
  --no-pr
```

### 预期输出（JSON）— 成功案例

```json
{
  "root_cause_summary": "The function read_user_id in app/config.py assumes the 'user_id' key is always present...",
  "changed_files": ["app/config.py"],
  "diff_summary": "@@ -4,3 +4,3 @@\n def read_user_id(payload):\n-    return payload[\"user_id\"]\n+    return payload.get(\"user_id\")",
  "syntax_check": true,
  "tests_run": ["/.../python3 -m pytest"],
  "pr_url": "https://github.com/owner/repo/pull/42",
  "status": "pr_created",
  "branch": "agentfix/key_error/key-error",
  "artifact_dir": ".agentfix-artifacts/20260414133000-key_error"
}
```

### 预期输出 — 各种 status 含义

| status | 含义 | 触发条件 |
|--------|------|----------|
| **`pr_created`** | 修复成功且已创建 Draft PR | 验证通过 + publish=true |
| **`validated`** | 修复成功但未创建 PR | 验证通过 + `--no-pr` 或 Token 缺失 |
| **`needs_manual_intervention`** | 需人工介入 | 置信度不足 或 重试耗尽 |

### 退出码
- `0`: `status` 为 `validated` 或 `pr_created`
- `1`: 其他情况（修复失败）

### 产物目录结构

```
.agentfix-artifacts/
  └── 20260414133000-key_error/        <-- 每次 run 自动生成一个时间戳目录
      ├── incident.json                <-- 结构化故障信息
      ├── analysis.json                <-- LLM 根因分析结果
      ├── attempt-1-proposal.json      <-- 第1次补丁提案
      ├── attempt-1.patch              <-- 第1次应用的 diff
      ├── attempt-1-validation.json    <-- 第1次验证结果
      ├── attempt-1-pr.json            <-- 第1次 PR 结果（如有）
      ├── repair-result.json           <-- 最终结果汇总
      └── repair-report.md             <-- 可读性 Markdown 报告
```

---

## 4. `agentfix validate`

### 功能
**独立验证命令** — 对已有代码改动执行语法检查和测试运行，不调用 LLM。

### 是否需要凭据
**不需要**（纯本地操作）

### 参数

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--repo` | 是 | - | 目标仓库路径 |
| `--base-branch` | 否 | `main` | 用于上下文收集的基准分支 |
| `--log-file` | 否 | null | 可选日志文件（用于更好的测试选择） |
| `--files` | 否 | `git diff --name-only` | 待验证的文件列表（空格分隔） |

### 执行流程

```
changed_files 来源:
  |-- 显式指定 --files file1.py file2.py
  +-- 未指定则自动执行 git diff --name-only

验证步骤:
  1) py_compile: 对所有 .py 改动文件做 Python 语法检查
  2) 测试运行 (按优先级选择):
     |-- validation.test_commands 配置显式指定了 --> 直接用
     |-- repo_context.metadata.test_candidates 非空   --> pytest + 候选文件
     |-- 仓库根目录有 tests/ 目录                     --> pytest
     +-- 以上都不满足                                 --> 跳过测试
```

### 用法

```bash
# 验证 git diff 检测到的改动文件
agentfix validate \
  --repo /path/to/your/repo

# 验证指定文件
agentfix validate \
  --repo /path/to/your/repo \
  --files app/config.py app/service.py

# 结合日志文件做更智能的测试选择
agentfix validate \
  --repo /path/to/your/repo \
  --log-file ./error.log
```

### 预期输出（JSON）— 成功

```json
{
  "syntax_check": true,
  "tests_passed": true,
  "commands": [
    { "command": "python3 -m py_compile app/config.py", "returncode": 0, "stdout": "", "stderr": "" },
    { "command": "python3 -m pytest", "returncode": 0, "stdout": "...", "stderr": "" }
  ],
  "failure_summary": [],
  "suggested_follow_up": []
}
```

### 预期输出 — 失败

```json
{
  "syntax_check": true,
  "tests_passed": false,
  "commands": [
    { "command": "python3 -m py_compile app/config.py", "returncode": 0 },
    { "command": "python3 -m pytest", "returncode": 1, "stderr": "FAILED test_config.py::test_xxx" }
  ],
  "failure_summary": ["Test command failed: python3 -m pytest"],
  "suggested_follow_up": ["Review failing command output and retry with a narrower patch."]
}
```

### 退出码
- `0`: 验证全部通过 (`is_success == true`)
- `1`: 存在失败项

### 典型使用场景
- 手动修改代码后，快速验证改动的正确性
- CI 流水线中作为验证步骤
- `agentfix run` 之后单独复查

---

## 5. `agentfix pr`

### 功能
**PR 创建命令** — 基于已有的修复结果 JSON，为当前分支创建 GitHub Draft PR。

### 是否需要凭据
**需要** GitHub Token（用于调用 GitHub REST API）

### 参数

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--repo` | 是 | - | 目标仓库路径 |
| `--base-branch` | 否 | `main` | PR 目标基准分支 |
| `--report-file` | **是** | - | `repair-result.json` 文件路径 |

### 执行流程

```
1. 读取 report-file (repair-result.json)
2. 提取信息: branch, root_cause_summary, status, tests_run
3. 构造 PR 标题: "[agentfix] {root_cause_summary}"
4. 构造 PR 正文:
   ## Error Summary
   - Status: `{status}`
   
   ## Root Cause
   {root_cause_summary}
   
   ## Validation
   - `test_command_1`
   - `test_command_2`

5. 调用 GitHub REST API 创建 Draft PR
   POST {api_base_url}/repos/{owner}/{repo}/pulls
   body: { title, head: branch, base: base_branch, body, draft: true }
```

### 用法

```bash
agentfix pr \
  --repo /path/to/your/repo \
  --report-file .agentfix-artifacts/xxx/repair-result.json \
  --base-branch main
```

### 预期输出（JSON）

```json
{
  "branch": "agentfix/key_error/key-error",
  "commit_sha": "abc123def456...",
  "pr_url": "https://github.com/owner/repo/pull/42",
  "title": "[agentfix] KeyError: The function read_user_id assumes...",
  "body": "## Error Summary\n..."
}
```

### 退出码
始终返回 `0`

### 典型使用场景
- `agentfix run --no-pr` 之后，审查完修改后手动创建 PR
- 在不同时间点基于历史修复记录重新发 PR
- PR 创建失败后重试

---

## 命令速查表

| 命令 | 改代码？ | 调 LLM？ | 建 PR？ | 需要 API Key | 需要 GitHub Token |
|------|---------|----------|---------|-------------|-------------------|
| `doctor` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `analyze` | ❌ | ✅ (1次) | ❌ | **✅** | ❌ |
| `validate` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `run` | **✅** | **✅ (多次)** | 条件* | **✅** | 条件* |
| `pr` | ❌ | ❌ | **✅** | ❌ | **✅** |

> *`run` 命令：不加 `--no-pr` 时需要 GitHub Token；加了则跳过 PR 创建。

---

## 推荐使用顺序（典型工作流）

```
① agentfix doctor          # 先检查环境是否正常
     ↓
② agentfix analyze         # 只做分析，确认根因判断准确
     ↓ (满意分析结果)
③ agentfix run --no-pr     # 跑完整修复但不建 PR，先看效果
     ↓ (review 产物目录中的 diff 和报告)
④ agentfix validate        # 在源仓库上再次验证
     ↓ (确认无误)
⑤ agentfix pr              # 正式创建 Draft PR 给团队 review
```
