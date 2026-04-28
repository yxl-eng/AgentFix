# AgentFix V3 Generated Regression Tests

V3 adds an optional regression-test generation step before the repair patch is created.

`test_commands` still means "how to run tests". The generated test feature adds the missing second half: it asks the model to create a focused test file for the current incident, runs that new test before the fix, then runs it again after the fix.

## Flow

1. Parse the incident log and collect code context.
2. Analyze the root cause.
3. Detect the target repository test framework.
4. Ask the model to generate one regression test file.
5. Apply that test in the temporary repair workspace.
6. Run only the generated test before the fix.
7. Keep the test only if it fails for a non-infrastructure reason.
8. Generate and apply the repair patch.
9. Run the generated test again after the fix.
10. Run the normal V2 validation: `test_commands`, service start, healthcheck, verification requests, and log scan.
11. If the generated test is stable, include it in the PR with the code fix.

If generated-test creation fails, AgentFix records the reason and falls back to the existing V2 validation path by default.

## Target Config

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
      fallback_to_v2_on_failure: true
      max_files: 1
```

Supported first-pass framework detection:

- Python: `pytest`, `unittest`
- Node: `jest`, `vitest`, `mocha`
- Go: `go test`
- Java: Maven/Gradle JUnit

Unsupported or unclear projects fall back to V2.

## Complex Demo

`demo_services/fastapi-order-service` is the richer V3 demo. It contains:

- FastAPI routes
- header-based user identity
- repository and service layers
- order create/read/cancel endpoints
- application logging
- pytest tests
- an intentional authorization bug in order cancellation

To use it for the full PR + Feishu demo, create a GitHub repo, add it as the demo service `origin`, push `main`, and update `targets.fastapi-order-service.repo_full_name` in `agentfix.yaml`.
