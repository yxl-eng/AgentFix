# PatchPilot

PatchPilot 是一个面向线上 Web 服务事故的环境感知自动修复 Agent。它会从日志、GitHub `bug` issue 或本地日志 watch 事件中发现异常，先判断是否值得处理，再尝试读取代码、生成补丁、执行验证、创建 Draft PR，并把结果写入修复记录和飞书通知。

## 支持的操作

- 监听本地日志或 webhook 事件，自动发现事故
- 先做分诊，再决定是忽略、人工处理还是自动修复
- 读取相关代码并生成最小修复补丁
- 执行测试、服务验证和回归检查
- 验证通过后创建 Draft PR
- 生成事故记录并推送飞书通知
- 通过 GUI 查看记录、编辑配置和管理目标服务

## 核心产物

- `records/<incident_id>.json` 和 `records/<incident_id>.md`：修复记录与报告
- `.patchpilot-artifacts/`：中间产物、补丁和验证结果
- `.patchpilot-state/events.sqlite3`：事件去重状态

## 快速入门

1. 安装依赖：

```powershell
python -m pip install -e ".[dev]"
```

2. 打开桌面控制台：

```powershell
python gui.py
```

3. 在 GUI 里完成模型、GitHub、飞书和目标服务配置。

4. 需要常驻监听时，启动服务：

```powershell
patchpilot serve --host 127.0.0.1 --port 8080 --watch
```
