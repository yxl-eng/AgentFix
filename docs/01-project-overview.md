# AgentFix 项目梳理指南

## 一、项目概述

**AgentFix** 是一个面向 Python 服务仓库的 **Agent 化自动修复 CLI 工具**。

> 核心价值：读取线上 Traceback 日志 → 结合 Git 仓库上下文 → 调用 LLM 做两阶段修复分析 → 生成最小补丁 → 自动验证 → 创建 GitHub Draft PR

### 技术栈
- **语言**: Python 3.11+
- **核心依赖**: `openai` (LLM 调用), `pydantic` (数据模型), `PyYAML` (配置解析)
- **测试框架**: pytest
- **包管理**: setuptools (可编辑安装 `pip install -e .`)

---

## 二、目录结构总览

```
Feishu_code_reviewer/
├── agentfix.yaml              # 主配置文件（需从 .example 复制）
├── agentfix.yaml.example      # 配置示例
├── pyproject.toml             # 项目元数据 & 依赖声明
├── README.md                  # 项目说明
│
├── src/agentfix/              # 🔵 核心源码（主包）
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                 # CLI 入口，定义 5 个子命令
│   ├── config.py              # 配置加载与合并逻辑
│   ├── models.py              # 全部 Pydantic 数据模型定义
│   ├── incident_ingest.py     # 日志解析（Traceback → Incident）
│   ├── repo_context.py        # 仓库上下文收集（Git + 文件扫描）
│   ├── services/
│   │   ├── analysis.py        # Analysis Agent（根因分析 LLM 调用）
│   │   └── patching.py        # Patch Agent（补丁生成 LLM 调用）
│   ├── patch_engine.py        # 补丁应用引擎（写文件 + Guardrails 校验）
│   ├── validator.py           # 验证器（py_compile + pytest）
│   ├── publisher.py           # PR 发布器（GitHub REST API）
│   ├── repair_orchestrator.py # 🎯 总编排器（串联全部流程）
│   └── providers/
│       ├── base.py            # ModelProvider 抽象基类
│       └── openai_provider.py # OpenAI Responses API 实现
│
└── tests/                     # 测试代码
    ├── conftest.py            # pytest fixtures
    ├── helpers.py             # 测试工具函数
    ├── fixtures/              # 测试 fixture（日志样本等）
    ├── test_incident_ingest.py
    ├── test_orchestrator.py
    ├── test_patch_engine.py
    ├── test_publisher.py
    ├── test_repo_context.py
    └── test_validator.py
```

---

## 三、核心架构 — 数据流全景

```
日志文件 ──→ [IncidentIngestor] ──→ Incident 结构化数据
                                              │
                                              ▼
                          [RepoContextCollector] ← Git 仓库路径
                                              │
                                              ▼
                         RepoContext（候选文件 + 元数据）
                                              │
                              ┌───────────────┼───────────────┐
                              ▼                               ▼
                   [AnalysisAgent]                    [PatchAgent]
                   （LLM 第一阶段）                    （LLM 第二阶段）
                   根因分析                           补丁生成
                              │                               │
                              ▼                               ▼
                     AnalysisResult                   PatchProposal
                                                              │
                                                              ▼
                                                   [PatchEngine]
                                                   应用补丁+安全检查
                                                              │
                                                              ▼
                                                     AppliedPatch
                                                              │
                                                              ▼
                                                    [Validator]
                                                  py_compile + pytest
                                                    ┌──────────┴──────────┐
                                                    ▼                      ▼
                                               通过 ✅                 失败 ❌
                                                    │                      │
                                                    ▼                    ▼
                                            [Publisher]            重试（最多2次）
                                        创建 GitHub Draft PR
```

---

## 四、关键模块详解

### 4.1 `cli.py` — CLI 入口

| 子命令 | 功能 | 是否需要 API Key |
|--------|------|-----------------|
| `doctor` | 检查运行时环境、配置、凭据 | 否 |
| `run` | 执行完整修复流程 | 是 |
| `analyze` | 仅做根因分析（不修改代码） | 是 |
| `validate` | 验证已有改动 | 否 |
| `pr` | 基于已有结果创建 Draft PR | 仅需 GitHub Token |

### 4.2 `models.py` — 数据模型（核心实体）

| 模型 | 用途 | 关键字段 |
|------|------|----------|
| `Incident` | 解析后的故障信息 | exception_type, stack_frames, suspected_module |
| `CandidateFile` | 候修文件 | relative_path, score, excerpt, full_content |
| `RepoContext` | 仓库上下文 | metadata, candidate_files |
| `AnalysisResult` | 分析结果 | root_cause_summary, confidence, candidate_targets |
| `PatchProposal` | 补丁提案 | patches: list[FilePatch], commit_message_title |
| `AppliedPatch` | 已应用的补丁 | changed_files, diff_text |
| `ValidationResult` | 验证结果 | syntax_check, tests_passed, is_success |
| `RepairResult` | 最终修复结果 | status, pr_url, artifact_dir |

### 4.3 `incident_ingest.py` — 日志解析器

通过正则表达式从 Traceback 日志中提取：
- **堆栈帧** (`File "...", line X, in Y`)
- **异常类型和消息** (`KeyError: 'xxx'`)
- **服务名 / 环境标签**
- **时间戳**
- **触发提示**（Traceback 前的上下文行）

支持的标准异常：`AttributeError`, `KeyError`, `TypeError`, `ImportError`, `ModuleNotFoundError`, `NoneType` 相关

### 4.4 `services/analysis.py` — Analysis Agent（第一阶段 LLM）

- **输入**: Incident + RepoContext
- **输出**: AnalysisResult（根因摘要、置信度、候修目标列表、修复计划、验证关注点）
- **推理强度**: 可配置（默认 medium）

### 4.5 `services/patching.py` — Patch Agent（第二阶段 LLM）

- **输入**: Incident + AnalysisResult + RepoContext + 反馈信息
- **输出**: PatchProposal（具体文件补丁列表、提交信息）
- **推理强度**: 可配置（默认 high）
- **特点**: 支持多轮重试反馈（validation failure 会作为 feedback 传入）

### 4.6 `patch_engine.py` — 补丁应用引擎

职责：
1. 将 PatchProposal 中的 `updated_content` 写入实际文件
2. **Guardrails 安全检查**：
   - 最多改 3 个文件 (`max_changed_files`)
   - 补丁不超过 250 行 (`max_patch_lines`)
   - 禁止修改依赖文件
3. 生成 diff 文本

### 4.7 `validator.py` — 验证器

两步验证：
1. **语法检查**: `py_compile` 对每个改动的文件
2. **测试运行**: 执行配置的 `test_commands`（可选 pytest）

### 4.8 `publisher.py` — GitHub PR 发布器

操作序列：创建分支 → git add → git commit → git push → 调用 GitHub REST API 创建 Draft PR

### 4.9 `providers/openai_provider.py` — 模型提供者

封装 OpenAI 兼容 API 调用，支持多种传输方式：
- `auto` / `responses` / `chat_completions` / `rest_chat_completions`

当前项目配置使用 **火山方舟 DeepSeek 模型**。

---

## 五、配置系统 (`config.py`)

配置加载优先级（从低到高）：
```
内置默认值 < agentfix.yaml < agentfix.local.yaml（gitignore）
```

主要配置项：

```yaml
openai:
  model: deepseek-v3-2-251201          # LLM 模型
  api_key_env_var: ARK_API_KEY         # API Key 环境变量名
  base_url: https://ark.cn-beijing.volces.com/api/v3  # API 地址
  transport: rest_chat_completions      # 传输协议

guardrails:
  max_changed_files: 3                  # 最大改动文件数
  max_patch_lines: 250                  # 最大补丁行数
  min_confidence: 0.45                  # 最小置信度阈值

runtime:
  max_repair_attempts: 2                # 最大修复重试次数
  artifact_root: .agentfix-artifacts    # 产物输出目录
```

---

## 六、修复流程详细时序 (`repair_orchestrator.py`)

`run()` 方法的完整执行流程：

```
1. 解析日志 → Incident 对象
2. 创建产物目录 (.agentfix-artifacts/{timestamp}-{id}/)
3. 收集仓库上下文 → RepoContext
4. 调用 AnalysisAgent → AnalysisResult
5. 置信度检查（< min_confidence 则终止）
6. 【循环 max_repair_attempts 次】
   a. 复制仓库到临时目录（不污染源仓库）
   b. 调用 PatchAgent → PatchProposal
   c. PatchEngine 应用补丁（带 Guardrails 检查）
   d. Validator 验证（compile + test）
   e. 验证通过 → 跳出循环；失败 → 用错误信息作为 feedback 重试
7. Publisher 创建 GitHub Draft PR
8. 输出 RepairResult（JSON + Markdown 报告）
```

---

## 七、快速上手步骤

### 1️⃣ 环境准备
```bash
cd /path/to/Feishu_code_reviewer
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2️⃣ 配置文件
```bash
cp agentfix.yaml.example agentfix.yaml
# 编辑 agentfix.yaml 填入你的 API 配置
```

### 3️⃣ 设置环境变量
```bash
export ARK_API_KEY="your-api-key"
export GITHUB_TOKEN="your-github-token"  # 如需创建 PR
```

### 4️⃣ 验证环境
```bash
agentfix doctor
```

### 5️⃣ 运行测试
```bash
pytest tests/ -q
```

### 6️⃣ 执行修复
```bash
# 完整修复流程
agentfix run --repo /path/to/your/service-repo --log-file ./tests/fixtures/xxx.log --base-branch main

# 仅分析不做修复
agentfix analyze --repo /path/to/your/service-repo --log-file ./tests/fixtures/xxx.log
```

---

## 八、设计亮点

1. **安全隔离**: 每次修复在临时副本上操作，不污染源仓库
2. **两阶段 LLM**: 分析与补丁生成分离，各自可调推理强度
3. **Guardrails**: 多层安全限制（文件数、行数、路径白名单）
4. **重试机制**: 验证失败会将错误作为反馈传入 LLM 重试（最多 2 次）
5. **结构化输出**: 全程 Pydantic 模型保障类型安全
6. **产物持久化**: 每次运行产出完整 JSON + Markdown 报告到 `.agentfix-artifacts/`
