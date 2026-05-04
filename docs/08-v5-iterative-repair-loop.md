# PatchPilot V5：迭代修复循环

V5 的核心变化是把“一轮修复流水线”升级为受控的 Iterative Repair Loop。PatchPilot 不再只生成一次补丁，而是把验证失败反馈带回模型，继续调整补丁，直到修复成功、达到最大轮数或触发风控。

## 默认循环

每轮执行：

1. 收集日志和代码上下文。
2. 刷新根因假设。
3. 生成或复用回归测试。
4. 生成补丁。
5. 在临时工作区应用补丁。
6. 运行语法/编译检查。
7. 运行生成测试。
8. 运行配置验证。
9. 根据结果决定停止、继续下一轮或生成报告。

默认最大轮数：

```yaml
runtime:
  max_repair_attempts: 3
```

每轮都会写入结构化记录，包括当前假设、读取的代码上下文、生成测试结果、补丁摘要、验证反馈和下一轮反馈。

## 状态

V5 对外只展示 4 种状态：

- `fixed`：修复已验证通过；PR 是否创建看 `pr_url`。
- `needs_human_verification`：语法/编译通过，但自动生成的回归测试样例没有通过，需要人类确认。
- `needs_manual_intervention`：环境、配置、数据、外部依赖、信息不足、补丁越界或多轮修复失败。
- `ignored`：Planner 判断为噪声、预期业务日志或无需处理。

旧记录兼容展示：

- `pr_created`、`validated` 显示为 `fixed`。
- `reported`、`needs_more_context` 显示为 `needs_manual_intervention`。

## 飞书通知

飞书卡片改为精简版，只包含：

- 目标服务
- 状态
- 根因摘要
- 修复摘要
- 修改文件
- 验证摘要
- PR / 报告入口

工具调用链、生成测试详情和人工处理建议保留在 `records/*.md`，不再放进卡片。

## 配置迁移

新标准文件名：

```text
patchpilot.yaml
patchpilot.local.yaml
```

旧文件仍兼容读取：

```text
agentfix.yaml
agentfix.local.yaml
```

GUI 保存时只写入 `patchpilot.local.yaml`。
