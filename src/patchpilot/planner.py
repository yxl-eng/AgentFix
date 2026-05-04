from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from patchpilot.config import AppConfig, TargetSettings
from patchpilot.models import PlannerDecision, RepairEvent


class IncidentPlanner:
    """Small, policy-bound incident router before the repair pipeline.

    The planner is intentionally deterministic in V4: it makes the first safety
    decision from observable runtime signals, then the existing LLM repair agents
    handle code analysis and patch generation only when the incident looks fixable
    in source.
    """

    ENVIRONMENT_PATTERNS = {
        "connection refused": "external_dependency",
        "econnrefused": "external_dependency",
        "connection reset": "external_dependency",
        "timed out": "external_dependency",
        "timeout": "external_dependency",
        "database is locked": "environment",
        "db unavailable": "external_dependency",
        "service unavailable": "external_dependency",
        "missing required environment variable": "configuration",
        "environment variable": "configuration",
        "permission denied": "environment",
        "no such file or directory": "configuration",
        "disk quota": "environment",
        "out of memory": "environment",
    }

    DATA_PATTERNS = {
        "integrityerror": "data",
        "duplicate key": "data",
        "foreign key": "data",
        "deadlock": "data",
        "missing seed data": "data",
        "invalid production data": "data",
    }

    CODE_PATTERNS = [
        "traceback",
        "typeerror",
        "attributeerror",
        "keyerror",
        "indexerror",
        "valueerror",
        "nameerror",
        "runtimeerror",
        "nullpointerexception",
        "illegalstateexception",
        "panic:",
        "segmentation fault",
    ]

    BENIGN_PATTERNS = [
        "client_error",
        "validation failed",
        "validationerror",
        "bad request",
        "unauthorized",
        "forbidden",
        "not found",
        "rate limit",
        "retry succeeded",
        "expected business rejection",
        "expected_status=4",
        "http 400",
        "http 401",
        "http 403",
        "http 404",
        "http 409",
    ]

    def __init__(self, config: AppConfig, project_root: str | Path | None = None) -> None:
        self.config = config
        self.project_root = Path(project_root or ".").resolve()

    def plan(
        self,
        event: RepairEvent,
        target_config: TargetSettings,
        log_text: str,
        *,
        incident_id: str,
    ) -> PlannerDecision:
        if not self.config.agent.planner.enabled:
            return self._decision(
                disposition="repair_attempt",
                root_cause_type="code",
                risk_level="medium",
                confidence=0.7,
                summary="Planner 已被配置关闭，事件将直接进入自动修复流程。",
                reason="配置项 agent.planner.enabled 为 false，因此跳过环境感知分诊。",
                evidence=["配置要求跳过 Planner 分诊。"],
                tool_plan=self._repair_plan(target_config),
            )

        repo_path = Path(target_config.repo_path).resolve()
        env_evidence = self._inspect_target(repo_path, target_config)
        if not repo_path.exists():
            return self._decision(
                disposition="report_only",
                root_cause_type="configuration",
                risk_level="high",
                confidence=0.95,
                summary="配置的目标仓库路径不存在。",
                reason="目标仓库不在本机，PatchPilot 无法读取代码或生成补丁。",
                evidence=[f"repo_path={repo_path}", *env_evidence],
                tool_plan=["Read Log", "Inspect Config", "Record Repair", "Notify Feishu"],
                human_action_required=True,
                human_steps=[
                    "先把目标服务仓库 clone 到配置的 repo_path。",
                    "检查 patchpilot.local.yaml 中的 target.repo_path 是否指向这个本地仓库。",
                    "路径可用后重新发送 incident 或重新触发日志 watch。",
                ],
            )

        stripped = log_text.strip()
        if len(stripped) < 20:
            return self._decision(
                disposition="needs_more_context",
                root_cause_type="unknown",
                risk_level="low",
                confidence=0.8,
                summary="事件缺少足够的日志上下文，无法安全诊断。",
                reason="上报内容太短，无法判断是真实异常、业务噪声还是环境问题。",
                evidence=[f"log_length={len(stripped)}", *env_evidence],
                tool_plan=["Read Log", "Inspect Config", "Record Repair", "Notify Feishu"],
                human_action_required=True,
                human_steps=[
                    "补充完整 traceback 或结构化错误事件。",
                    "补充请求方法、路径、用户或租户 ID，以及预期行为。",
                    "如果事件来自日志 watch，请扩大日志窗口或改用 incident webhook 主动上报。",
                ],
            )

        lowered = stripped.lower()
        matched_env = self._match_any(lowered, self.ENVIRONMENT_PATTERNS)
        if matched_env is not None:
            marker, root_type = matched_env
            return self._decision(
                disposition="report_only",
                root_cause_type=root_type,
                risk_level="high",
                confidence=0.85,
                summary="该异常更像是运行环境、配置或外部依赖不可用导致。",
                reason=f"日志中包含 `{marker}`，这类问题通常不能只靠修改业务代码解决。",
                evidence=[self._excerpt_for_marker(stripped, marker), *env_evidence],
                tool_plan=["Read Log", "Inspect Config", "Check Runtime", "Record Repair", "Notify Feishu"],
                human_action_required=True,
                human_steps=[
                    "优先检查失败的外部依赖或运行时资源。",
                    "确认环境变量、服务凭证、网络连通性和进程健康状态。",
                    "环境恢复后重新回放请求；如果代码仍然报错，再重新发送 incident。",
                ],
            )

        matched_data = self._match_any(lowered, self.DATA_PATTERNS)
        if matched_data is not None:
            marker, root_type = matched_data
            return self._decision(
                disposition="report_only",
                root_cause_type=root_type,
                risk_level="medium",
                confidence=0.78,
                summary="该异常更像是生产数据一致性问题，不适合直接自动改代码。",
                reason=f"日志中包含 `{marker}`，通常需要先检查数据或迁移记录。",
                evidence=[self._excerpt_for_marker(stripped, marker), *env_evidence],
                tool_plan=["Read Log", "Inspect Config", "Search Similar Fixes", "Record Repair", "Notify Feishu"],
                human_action_required=True,
                human_steps=[
                    "根据日志上下文检查受影响的记录、租户或订单 ID。",
                    "确认是否需要数据迁移、补数或人工修复数据。",
                    "只有在明确异常数据形态后，再考虑补充代码防御逻辑。",
                ],
            )

        has_code_signal = any(pattern in lowered for pattern in self.CODE_PATTERNS)
        if has_code_signal:
            return self._decision(
                disposition="repair_attempt",
                root_cause_type="code",
                risk_level="medium",
                confidence=0.82,
                summary="日志包含源码级异常信号，适合尝试自动修复。",
                reason="日志里有 traceback 或异常标记，可以回溯到具体源码文件。",
                evidence=[self._first_relevant_line(stripped), *env_evidence],
                tool_plan=self._repair_plan(target_config),
                human_action_required=False,
            )

        if "error" in lowered and self._looks_benign(lowered):
            return self._decision(
                disposition="ignored",
                root_cause_type="benign_log",
                risk_level="low",
                confidence=0.75,
                summary="日志虽然包含 error 字样，但更像预期内的客户端或业务拒绝行为。",
                reason="没有发现 traceback 或崩溃标记，并且日志符合常见 4xx 或业务校验拒绝模式。",
                evidence=[self._first_relevant_line(stripped), *env_evidence],
                tool_plan=["Read Log", "Record Repair"],
                human_action_required=False,
            )

        if "error" in lowered:
            return self._decision(
                disposition="needs_more_context",
                root_cause_type="unknown",
                risk_level="low",
                confidence=0.65,
                summary="事件提到了 error，但缺少足够诊断证据。",
                reason="在修改代码前，PatchPilot 需要 traceback、失败请求或运行时上下文。",
                evidence=[self._first_relevant_line(stripped), *env_evidence],
                tool_plan=["Read Log", "Inspect Config", "Record Repair", "Notify Feishu"],
                human_action_required=True,
                human_steps=[
                    "发送 error 附近的完整 traceback 或服务日志片段。",
                    "补充接口路径、请求体结构、预期状态码和最近发布变更。",
                ],
            )

        return self._decision(
            disposition="ignored",
            root_cause_type="non_error_event",
            risk_level="low",
            confidence=0.72,
            summary="事件中没有明确的异常信号。",
            reason="没有检测到异常、traceback、崩溃或可操作的错误标记。",
            evidence=[self._first_relevant_line(stripped), *env_evidence],
            tool_plan=["Read Log", "Record Repair"],
            human_action_required=False,
        )

    def _decision(
        self,
        *,
        disposition: str,
        root_cause_type: str,
        risk_level: str,
        confidence: float,
        summary: str,
        reason: str,
        evidence: list[str],
        tool_plan: list[str],
        human_action_required: bool = False,
        human_steps: list[str] | None = None,
    ) -> PlannerDecision:
        filtered_plan = self._filter_plan(tool_plan)
        return PlannerDecision(
            disposition=disposition,
            root_cause_type=root_cause_type,
            risk_level=risk_level,
            confidence=confidence,
            summary=summary,
            decision_reason=reason,
            evidence=[item for item in evidence if item],
            tool_plan=filtered_plan,
            human_action_required=human_action_required,
            human_resolution_steps=human_steps or [],
        )

    def _repair_plan(self, target_config: TargetSettings) -> list[str]:
        plan = ["Read Log", "Read Code"]
        if target_config.generated_tests.enabled:
            plan.append("Generate Regression Test")
        plan.extend(["Run Test", "Git Commit", "Record Repair", "Notify Feishu"])
        return plan

    def _filter_plan(self, tool_plan: list[str]) -> list[str]:
        allowed = set(self.config.agent.planner.allowed_tools)
        if not allowed:
            return tool_plan[: self.config.agent.planner.max_steps]
        filtered = [tool for tool in tool_plan if tool in allowed]
        return filtered[: self.config.agent.planner.max_steps]

    def _inspect_target(self, repo_path: Path, target_config: TargetSettings) -> list[str]:
        evidence = [f"target_repo={repo_path}"]
        if repo_path.exists():
            evidence.append("repo_path_exists=true")
            if (repo_path / ".git").exists():
                branch = self._git_output(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
                evidence.append(f"git_branch={branch or 'unknown'}")
            if target_config.service_log_file:
                log_path = (repo_path / target_config.service_log_file).resolve()
                evidence.append(f"service_log_file_exists={str(log_path.exists()).lower()}")
            if target_config.test_commands:
                evidence.append(f"test_commands={json.dumps(target_config.test_commands, ensure_ascii=False)}")
            if target_config.healthcheck_url:
                evidence.append(f"healthcheck_url={target_config.healthcheck_url}")
        else:
            evidence.append("repo_path_exists=false")
        return evidence

    def _git_output(self, repo_path: Path, args: list[str]) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def _match_any(self, lowered: str, patterns: dict[str, str]) -> tuple[str, str] | None:
        for marker, root_type in patterns.items():
            if marker in lowered:
                return marker, root_type
        return None

    def _looks_benign(self, lowered: str) -> bool:
        if "traceback" in lowered or "exception" in lowered:
            return False
        return any(pattern in lowered for pattern in self.BENIGN_PATTERNS)

    def _first_relevant_line(self, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:500]
        return ""

    def _excerpt_for_marker(self, text: str, marker: str) -> str:
        pattern = re.compile(re.escape(marker), re.IGNORECASE)
        for line in text.splitlines():
            if pattern.search(line):
                return line.strip()[:500]
        return self._first_relevant_line(text)
