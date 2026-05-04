# PatchPilot 自动生成回归测试

PatchPilot 会尝试根据 incident 日志、候选代码和现有测试风格生成一个聚焦的回归测试。理想闭环是：修复前失败，修复后通过；只有稳定闭环成立，生成的测试才会随业务修复一起进入 PR。

## 流程

1. 解析 incident 日志并收集代码上下文。
2. 分析根因。
3. 识别目标仓库测试框架。
4. 让模型生成一个回归测试文件。
5. 在临时修复工作区应用测试文件。
6. 修复前先运行生成测试。
7. 只有失败原因和 incident 相关时才保留候选测试。
8. 生成并应用业务修复补丁。
9. 修复后再次运行生成测试。
10. 继续运行既有验证：`test_commands`、服务启动、健康检查、接口验证请求和日志扫描。
11. 如果生成测试稳定，PR 同时包含业务修复和回归测试。

## 配置

```yaml
targets:
  my-service:
    repo_path: C:/repos/my-service
    base_branch: main
    test_commands:
      - python -m pytest tests
    generated_tests:
      enabled: true
      framework: auto
      commit_when_stable: true
      failure_policy: continue_existing_validation
      max_files: 1
```

`failure_policy` 支持：

- `continue_existing_validation`：生成测试不稳定时不提交测试，继续运行已有验证。这是默认值。
- `needs_human_verification`：语法/编译检查通过但生成测试修复后仍失败时，不创建 PR，状态为 `needs_human_verification`。

旧字段仍兼容：

- `fallback_to_v2_on_failure: true` 映射为 `continue_existing_validation`。
- `fallback_to_v2_on_failure: false` 映射为 `needs_human_verification`。

## 支持的测试框架

- Python：`pytest`、`unittest`
- Node：`jest`、`vitest`、`mocha`
- Go：`go test`
- Java：Maven/Gradle JUnit

识别不出的项目会跳过生成测试，继续走既有验证链路。
