# AgentFix 桌面 GUI 使用说明

AgentFix 桌面端基于 Python 内置 `tkinter` 实现，不需要额外启动网页控制台。它面向普通使用者提供一个本地工作台，用来查看事故记录、编辑密钥和配置、管理目标服务，并手动触发一次修复。

## 启动

在项目根目录运行：

```powershell
python gui.py
```

如果当前环境里 `python` 不可用，可以使用你的 conda 环境：

```powershell
conda run --no-capture-output -n agentfix311 python gui.py
```

## 配置保存位置

GUI 会读取：

1. `agentfix.yaml`
2. `agentfix.local.yaml`

保存时写入 `agentfix.local.yaml`。这个文件适合放本机路径、真实仓库名和密钥，默认不应该提交到 Git。

## 页面功能

### 总览

展示当前 records 统计，包括总事件、已创建 PR、只报告和已忽略事件，并列出最近事故。

### 事故记录

左侧是 `records/*.json` 列表，支持按状态筛选和关键词搜索。右侧展示当前事故的处理结论、根因类型、风险等级、PR、证据、人工处理建议和工具调用链路。

### 配置中心

可以直接修改模型、GitHub、飞书、Planner、风控、server、records 和全局验证配置。

密钥类字段默认隐藏，包括：

- 模型 / ARK API Key
- GitHub 访问令牌
- 飞书机器人地址
- 飞书签名密钥

点击字段右侧的“预览”可以临时显示明文，再点击“隐藏”恢复掩码。配置页面只展示可直接填写的密钥项，不会在界面上打印密钥内容。

勾选项使用“已启用 / 未启用”按钮，不使用系统 checkbox，因此不会出现选中后显示为 `×` 的问题。

### 目标服务

用于配置被 AgentFix 监控和修复的本地服务仓库。常用字段包括：

- `repo_full_name`：GitHub 仓库名，例如 `owner/repo`
- `repo_path`：目标服务在本机的路径
- `base_branch`：PR 的目标分支
- `service_log_file`：Agent watch 的日志文件
- `start_command`：验证时启动服务的命令
- `healthcheck_url`：服务健康检查地址
- `test_commands`：已有测试命令，每行一个
- `verification_requests`：服务启动后要请求的接口，JSON 数组格式
- `generated_tests`：自动生成回归测试相关配置

配置页和目标服务页支持鼠标滚轮滚动，鼠标在输入框、文本框或按钮区域上方时也会滚动当前页面。

### 手动运行

选择本地目标仓库和日志文件后，可以触发一次：

```powershell
python -m agentfix run --repo <repo> --log-file <log> --base-branch <branch>
```

默认启用“只验证，不创建 PR”。关闭后才会按 CLI 能力继续创建分支、commit、push 和 Draft PR。

## 完整链路运行

1. 在 GUI 的“配置中心”填好模型密钥、GitHub 访问令牌和飞书机器人地址。
2. 在“目标服务”配置目标服务仓库路径、GitHub 仓库名、日志文件、测试命令和服务验证方式。
3. 启动 Agent 服务：

```powershell
agentfix serve --host 127.0.0.1 --port 8080 --watch
```

4. 通过目标服务页面触发错误，或发送 incident webhook。
5. 回到 GUI 的“事故记录”查看 Planner 决策、工具调用、修复结果、PR 链接和人工处理建议。
