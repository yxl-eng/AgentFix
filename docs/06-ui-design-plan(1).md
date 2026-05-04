# PatchPilot 前端 UI 设计方案

本文档用于规划 PatchPilot 的第一版前端界面，当前仅定义产品定位、页面结构、交互重点和 MVP 范围，不涉及具体开发实现。待方案确认后，再进入前端架构设计和页面开发阶段。

## 设计目标

PatchPilot 当前的核心能力不是内容展示，而是把一次自动修复流程完整呈现出来，包括事故输入、根因分析、补丁生成、验证执行、PR 产出和修复记录沉淀。

因此，第一版前端不建议优先做营销官网，而建议优先建设一个面向研发团队的修复工作台。

目标如下：

- 让所有路径、Key、Token、Webhook、命令和运行参数都具备可配置能力。
- 让用户快速看到当前 Agent 的运行情况和修复结果。
- 让用户理解一次修复为什么发生、改了什么、是否可信。
- 让用户可以方便地审阅补丁、验证过程和最终 PR。
- 让系统状态、配置状态、风险点具备可视化能力。

## 产品定位

建议第一版产品名称为 `PatchPilot Console`。

产品定位为：

> 面向研发团队的自动修复审阅工作台

它不是传统的业务后台，也不是单纯的官网，而是围绕以下核心对象展开：

- `Target`
- `Incident`
- `Repair Run`
- `Validation`
- `Draft PR`
- `Repair Record`

## 目标用户

### 研发负责人

关注整体修复效率、修复成功率、Draft PR 产出和人工介入比例。

### 开发工程师

关注根因分析是否合理、补丁是否最小、测试是否通过、PR 是否可直接审阅。

### SRE / 值班同学

关注 webhook 是否正常、事故是否被接收、事件是否重复、服务是否卡住、验证链路是否完整。

### 测试 / QA

关注是否生成了有效的回归测试、补丁是否真正修复问题、验证过程是否覆盖关键路径。

## 设计原则

第一版建议遵循以下设计原则：

- 配置优先：先保证所有读入参数可配置，再建设修复审阅工作台。
- 结果可见：用户能快速看到当前状态和最终产物。
- 过程可信：用户能看到分析、补丁、验证和通知链路。
- 风险可控：用户能识别失败、缺配置、缺验证等风险。
- 敏感信息安全：Key、Token、Secret 默认掩码显示，不明文回显。
- 实用优先：先做工作台，再扩展高级操作能力。

## 信息架构

建议第一版采用以下一级导航：

- `Configuration`
- `Dashboard`
- `Incidents`
- `Repairs`
- `Targets`
- `System`

## 页面规划

### 1. Configuration

这是第一优先级页面，用于统一管理 PatchPilot 所有读入参数。

设计目标如下：

- 让系统级、Target 级、凭据级参数都能被查看、编辑、校验和保存。
- 让用户明确每个参数的来源、当前值、生效范围和是否缺失。
- 让敏感配置在保证安全的前提下可更新，但不明文泄露。
- 让配置变更在 UI 中可追踪，避免线上修复失败时无法定位原因。

建议页面采用左侧导航加右侧表单工作台布局。

左侧建议分为 5 个配置分组：

- `系统配置`
- `模型与推理`
- `凭据管理`
- `Targets`
- `运行与产物`

#### 1.1 系统配置

建议纳入以下字段：

- `server.host`
- `server.port`
- `server.poll_interval_seconds`
- `server.state_path`
- `runtime.artifact_root`
- `records.root`
- `records.auto_commit`
- `validation.python_executable`

这一组的重点是把所有本地运行路径和服务监听参数可配置化。

#### 1.2 模型与推理

建议纳入以下字段：

- `openai.model`
- `openai.base_url`
- `openai.transport`
- `openai.analysis_reasoning_effort`
- `openai.patch_reasoning_effort`
- `guardrails.max_changed_files`
- `guardrails.max_patch_lines`
- `guardrails.min_confidence`
- `guardrails.ignored_paths`
- `runtime.max_repair_attempts`

这一组的重点是把模型接入参数和修复边界全部显式配置化。

#### 1.3 凭据管理

建议纳入以下字段：

- `openai.api_key_env_var`
- `github.token_env_var`
- `feishu.webhook_url_env_var`
- `feishu.webhook_secret_env_var`

同时建议支持录入以下敏感值或其覆盖值：

- OpenAI API Key
- GitHub Token
- Feishu Webhook URL
- Feishu Webhook Secret

敏感字段交互规则建议如下：

- 默认仅显示“已配置 / 未配置”状态。
- 明文值不在列表页和详情页直接回显。
- 支持“更新值”操作，但保存后只显示掩码。
- 支持显示来源：
  - 环境变量
  - `patchpilot.yaml`
  - `patchpilot.local.yaml`
  - UI 覆盖值

#### 1.4 Targets 配置

每个 target 建议支持新增、编辑、复制和删除。

建议纳入以下字段：

- `target_name`
- `repo_full_name`
- `repo_path`
- `base_branch`
- `service_log_file`
- `start_command`
- `healthcheck_url`
- `test_commands`
- `verification_requests`
- `generated_tests.enabled`
- `generated_tests.framework`
- `generated_tests.commit_when_stable`
- `generated_tests.fallback_to_v2_on_failure`

建议对以下字段提供专门交互：

- 路径类字段提供路径输入和存在性校验
- 命令类字段支持多行编辑
- 请求类字段支持结构化表单编辑
- 布尔开关类字段使用 switch

#### 1.5 运行与产物

建议纳入以下字段：

- `runtime.artifact_root`
- `records.root`
- `server.state_path`

这部分重点是把所有与输出产物、状态库、运行中间文件相关的路径统一收口配置。

#### 1.6 页面能力

Configuration 页面建议支持以下能力：

- 查看当前生效配置
- 编辑配置
- 保存为 `patchpilot.yaml`
- 将敏感项保存到 `patchpilot.local.yaml`
- 显示字段来源和优先级
- 配置校验和错误提示
- 检查缺失必填项
- 对比当前值与默认值
- 一键执行配置自检

#### 1.7 配置来源与优先级

建议在 UI 中明确展示配置来源优先级，避免用户误判当前生效值。

建议优先级如下：

1. UI 临时覆盖值
2. `patchpilot.local.yaml`
3. 环境变量解析结果
4. `patchpilot.yaml`
5. 系统默认值

如果当前项目实现层面的真实优先级与此不同，开发时需要以前后端统一规则为准。

#### 1.8 安全规则

配置模块需明确以下安全规则：

- 不在前端页面直接回显完整 Key、Token、Secret。
- 敏感字段单独提交，避免和普通配置混在同一个 payload 中。
- 导出配置时默认排除明文凭据。
- 配置变更前提示影响范围，例如是否影响 webhook、PR、通知或验证。

### 2. Dashboard

目标是让用户一进入系统就能看到 PatchPilot 的总体运行情况和最近修复状态。

建议包含以下模块：

- 顶部 KPI 卡片：
  - 今日事故数
  - 修复成功率
  - 待人工确认数
  - Draft PR 数
- 运行状态卡：
  - Agent 服务状态
  - Webhook 状态
  - Watch 状态
  - 最近心跳时间
- 最近事故时间线：
  - 按状态展示 `pr_created`、`validated`、`failed`、`duplicate`
- 最近修复记录表：
  - 展示 `incident_id`、`target`、`status`、`changed_files`、`pr_url`
- 风险提醒区：
  - 例如缺少 OpenAI Key、GitHub Token、Feishu Webhook，或 target 未配置验证

### 3. Incidents 列表页

目标是统一查看所有进入系统的事故事件。

建议列表字段如下：

- `incident_id`
- `target`
- `source`
- `status`
- `created_at`
- `root_cause_summary`
- `pr_url`
- `record`

建议支持以下筛选：

- 按 `status`
- 按 `source`
- 按 `target`
- 按时间范围
- 按是否已有 `PR`

建议支持以下交互：

- 点击行进入详情页
- 弹窗查看原始日志
- 复制 `event_key`
- 快速跳转修复记录或 PR

### 4. Incident Detail / Repair Detail

这是整个产品的核心页面，建议采用带标签页的工作台布局。

建议拆分为以下 6 个标签页：

- `概览`
- `日志`
- `分析`
- `补丁`
- `验证`
- `产物`

#### 概览

展示一次修复任务的总体信息：

- `incident_id`
- `target`
- `source`
- `status`
- `root_cause_summary`
- `branch`
- `pr_url`
- `artifact_dir`
- `record_json_path`
- `record_markdown_path`

建议额外显示关键标记：

- 已生成测试
- 验证通过
- 已通知飞书

#### 日志

目标是完整呈现触发修复的日志内容。

建议能力如下：

- 展示原始日志全文
- 高亮关键错误词：`Traceback`、`Error`、`Exception`、`panic`
- 对 `path:line` 形式做可点击增强设计
- 支持：
  - 复制日志
  - 折叠无关行
  - 仅查看错误上下文

#### 分析

目标是让用户理解 Agent 的判断依据。

建议映射现有分析结果中的字段：

- `root_cause_summary`
- `confidence`
- `candidate_targets`
- `repair_plan`
- `validation_focus`
- `additional_notes`

建议表现方式如下：

- 使用置信度条显示 `confidence`
- 使用文件卡片展示候选文件：
  - `path`
  - `rationale`
  - `confidence`
  - `change_summary`
- 使用步骤流展示 `repair_plan`
- 使用 checklist 展示 `validation_focus`

#### 补丁

目标是清晰展示修复改动内容，帮助开发者快速审阅。

建议展示：

- `changed_files`
- `diff_summary`

建议布局如下：

- 左侧文件列表
- 右侧 diff viewer

建议后续可扩展：

- 仅看业务代码
- 仅看测试文件
- 单独查看自动生成测试

#### 验证

目标是把修复可信度建立在可审计的验证链路上。

建议展示：

- `syntax_check`
- `tests_passed`
- `tests_executed`
- 所有执行命令及输出

推荐用 stepper 或命令卡片展示以下过程：

- 生成测试前运行
- 补丁后测试
- `py_compile`
- `pytest`
- 启动服务
- 健康检查
- 验证请求
- 日志复扫
- 停止服务

每个命令卡片建议包含：

- `command`
- `returncode`
- `stdout`
- `stderr`
- 执行状态

#### 产物

目标是展示最终交付物和可追溯信息。

建议展示：

- `record_json`
- `record_markdown`
- `artifact_dir`
- `pr_url`
- 飞书通知结果

建议支持以下操作：

- 下载 JSON
- 下载 Markdown
- 打开 PR
- 复制修复摘要

### 5. Repairs 列表页

目标是统一管理所有修复记录，便于做历史查询、复盘和演示。

建议列表字段如下：

- `incident_id`
- `target`
- `status`
- `message`
- `changed_files`
- `tests_run_count`
- `pr_url`
- `feishu_notified`

适用场景如下：

- 查看历史成功案例
- 汇总失败案例
- 做修复复盘
- 展示 Agent 的交付效果

### 6. Targets 页

目标是展示所有已配置 target 的能力、状态和配置完整性。

每个 target 建议展示：

- `target_name`
- `repo_full_name`
- `repo_path`
- `base_branch`
- `service_log_file`
- `healthcheck_url`
- `test_commands`
- `verification_requests`

状态标记建议包括：

- 已配置验证
- 支持 watch
- GitHub 关联已启用
- 生成测试已启用

该页面在第一版不再定位为只读展示页，而是配置模块中的目标仓库总览入口。

建议支持以下操作：

- 跳转到 `Configuration > Targets`
- 查看配置完整性状态
- 查看最近一次修复结果
- 查看最近一次验证结果
- 快速新增 target
- 快速复制 target 配置模板

### 7. System 页

目标是把 `doctor` 命令和系统健康状态做成可视化页面。

建议包含以下模块：

- 凭据状态：
  - OpenAI API Key
  - GitHub Token
  - Feishu Webhook
  - Feishu Webhook Secret
- 模型配置：
  - `default_model`
  - `analysis_reasoning_effort`
  - `patch_reasoning_effort`
- Guardrails：
  - `max_changed_files`
  - `max_patch_lines`
- 运行环境：
  - `python_version`
  - 模块可用性
- 服务状态：
  - `host`
  - `port`
  - `watch`
- 配置状态：
  - 配置来源
  - 缺失项数量
  - 非法路径数量
  - 凭据缺失数量

## 核心用户流

### 用户流 1：初始化配置

- 进入 `Configuration`
- 先完成系统配置和凭据配置
- 新增或编辑 target
- 执行配置自检
- 修复必填项和路径问题
- 确认配置可用于运行

### 用户流 2：查看一次自动修复

- 进入 Dashboard
- 打开最新 incident
- 查看根因分析
- 查看补丁 diff
- 查看验证结果
- 跳转到 Draft PR 审阅

### 用户流 3：排查失败任务

- 进入 Incidents
- 筛选 `failed` 或 `needs_manual_intervention`
- 查看失败原因
- 查看验证或命令输出
- 判断是配置问题、环境问题还是模型问题

### 用户流 4：做修复复盘

- 进入 Repairs
- 打开某条修复记录
- 查看根因、补丁、测试和 PR
- 导出 Markdown 记录用于分享或归档

## 视觉风格建议

第一版建议采用工程化工作台风格，而不是品牌展示型官网风格。

推荐方向：

- 主界面采用浅色背景，便于阅读表格和管理信息
- 日志区、代码区、diff 区采用深色面板，强化工程工具感

色彩建议：

- 主色：蓝色系
- 成功：绿色
- 处理中：蓝色或紫色
- 警告：橙色
- 失败：红色

状态标签建议统一映射以下状态：

- `pr_created`
- `validated`
- `needs_human_verification`
- `needs_manual_intervention`
- `failed`
- `duplicate`

## 组件建议

为提高页面复用性，建议优先设计以下组件：

- `StatusBadge`
- `MetricCard`
- `Timeline`
- `CommandStepList`
- `LogViewer`
- `DiffViewer`
- `JSONTree`
- `ArtifactCard`
- `TargetCard`
- `ConfigSection`
- `ConfigField`
- `SecretField`
- `SourceBadge`
- `ConfigValidationPanel`

其中复用价值最高的组件预计为：

- `StatusBadge`
- `LogViewer`
- `CommandStepList`
- `DiffViewer`

## 前端技术建议

如果需要为该项目补充一个现代前端，推荐以下技术方向之一：

### 方案 A：效率优先

- `React`
- `TypeScript`
- `Ant Design`
- `Monaco Editor / Diff Editor`

适合快速构建后台型产品，表格、Tabs、抽屉、表单和状态展示能力成熟。

### 方案 B：现代定制优先

- `React`
- `TypeScript`
- `Tailwind CSS`
- `shadcn/ui`
- `Monaco Editor / Diff Editor`

适合做视觉更现代、可定制程度更高的产品界面。

### 推荐结论

结合 PatchPilot 当前的产品形态，建议优先采用：

- `React + TypeScript + Ant Design + Monaco Diff Editor`

原因如下：

- 更适合后台和工作台类交互
- 表格、筛选、详情页、命令卡片开发速度更快
- 更适合第一版快速交付

## 后端接口建议

第一版前端可以先围绕现有输出结构建设，不必一开始就设计复杂接口。

建议补充以下 API：

- `GET /health`
- `GET /api/config`
- `PUT /api/config/system`
- `PUT /api/config/model`
- `PUT /api/config/credentials`
- `GET /api/config/targets`
- `POST /api/config/targets`
- `PUT /api/config/targets/:name`
- `DELETE /api/config/targets/:name`
- `POST /api/config/validate`
- `GET /api/dashboard/summary`
- `GET /api/incidents`
- `GET /api/incidents/:id`
- `GET /api/repairs`
- `GET /api/repairs/:id`
- `GET /api/targets`
- `GET /api/system/doctor`

此外，配置接口建议返回以下附加信息：

- 字段当前值
- 是否为默认值
- 当前来源
- 是否为敏感字段
- 校验状态
- 错误信息

如果要快速实现 demo，可以先完成配置读写和校验接口，再逐步补全 Incidents、Repairs 和 Dashboard。

## MVP 范围

建议第一阶段只做以下页面：

- `Configuration`
- `Targets`
- `System`
- `Dashboard`

第一阶段暂不优先做：

- 完整的 Repairs 历史检索
- 复杂的 Repair Detail 交互增强
- 实时日志流
- 多用户权限

这样可以先保证系统“可配、可存、可检、可运行”，再进入修复审阅体验建设。

## 建议开发顺序

- 先定义配置数据模型，与 `patchpilot.yaml`、`patchpilot.local.yaml`、环境变量映射对齐
- 实现 `Configuration` 页面及配置校验
- 实现 `Targets` 配置管理
- 实现 `System` 页面和 `doctor` 联动
- 再实现 Dashboard
- 最后实现 Incidents、Repairs 和 Repair Detail

## 当前建议结论

第一版建议方向如下：

- 产品名：`PatchPilot Console`
- 产品定位：面向研发团队的自动修复审阅工作台
- 优先级：配置模块优先，工作台次之，官网最后
- 核心价值：
  - 配得全
  - 配得清
  - 配得安全
  - 看得见事故
  - 看得懂根因
  - 看得清补丁
  - 看得到验证
  - 看得见 PR 和修复记录

## 待确认项

在进入开发前，建议先确认以下问题：

- UI 配置保存的目标文件是仅写入 `patchpilot.yaml`，还是区分 `patchpilot.yaml` 与 `patchpilot.local.yaml`
- 环境变量与配置文件冲突时，以哪种优先级为准
- 是否允许在 UI 中直接录入并持久化敏感凭据
- target 删除是否需要额外保护或二次确认
- 是否需要在第一版加入手动触发 repair
- 是否需要在第一版加入实时日志流
