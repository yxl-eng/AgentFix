from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

from agentfix.config import FeishuSettings
from agentfix.localization import disposition_label, root_cause_label, status_label
from agentfix.models import RepairRecord


class FeishuNotifier:
    REVIEW_MESSAGE = "我发现了一个 Bug 并已为您修复，请 Review"
    REPORT_MESSAGE = "AgentFix 发现一个异常并生成了处理报告，请处理"
    IGNORED_MESSAGE = "AgentFix 已忽略一条非异常日志"

    def __init__(self, settings: FeishuSettings) -> None:
        self.settings = settings

    def notify_repair(self, record: RepairRecord) -> tuple[bool, str]:
        webhook_url = self.settings.resolved_webhook_url()
        if not webhook_url:
            return False, f"飞书机器人 Webhook 未配置，请设置 {self.settings.webhook_url_env_var}。"
        payload = self._build_payload(record)
        secret = self.settings.resolved_webhook_secret()
        if secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = self._sign(timestamp, secret)
        request = urllib.request.Request(
            url=webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8", errors="ignore")
        except urllib.error.URLError as exc:
            return False, str(exc)
        return True, body

    def _build_payload(self, record: RepairRecord) -> dict[str, object]:
        result = record.repair_result
        changed_files = "、".join(result.changed_files) if result and result.changed_files else "无"
        validation_status = "未执行"
        if result and result.validation:
            validation_status = "通过" if result.validation.is_success else "失败"
        generated_test_status = "未尝试"
        if result and result.generated_test:
            if result.generated_test.is_stable and result.generated_test.committed:
                generated_test_status = f"已提交 {result.generated_test.test_path}"
            elif result.generated_test.fallback_reason:
                generated_test_status = f"未采纳，继续既有验证：{result.generated_test.fallback_reason}"
            else:
                generated_test_status = "已尝试但未采纳"
        summary = record.message
        decision_reason = record.decision_reason or (result.decision_reason if result else "")
        if decision_reason and decision_reason not in summary:
            summary = f"{summary}（处理判断：{decision_reason}）"
        repair_approach = "无"
        if result and result.analysis and result.analysis.repair_plan:
            repair_approach = "\n".join(f"- {step}" for step in result.analysis.repair_plan[:3])
        elif result and result.changed_files:
            repair_approach = f"- 修改 {changed_files}，并通过验证确认行为恢复。"
        generated_test_detail = self._generated_test_detail(result.generated_test if result else None)
        human_steps = record.human_resolution_steps or (result.human_resolution_steps if result else [])
        human_steps_text = "\n".join(f"- {step}" for step in human_steps) or "无"
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": self._title_for_record(record)},
                    "template": self._template_for_record(record),
                },
                "elements": [
                    {"tag": "markdown", "content": f"**目标服务**：{record.target}"},
                    {"tag": "markdown", "content": f"**状态**：{status_label(record.status)}"},
                    {"tag": "markdown", "content": f"**处理结论**：{disposition_label(record.disposition or 'repair_attempt')}"},
                    {"tag": "markdown", "content": f"**根因类型**：{root_cause_label(record.root_cause_type or 'unknown')}"},
                    {"tag": "markdown", "content": f"**摘要**：{summary}"},
                    {"tag": "markdown", "content": f"**修复思路**：\n{repair_approach}"},
                    {"tag": "markdown", "content": f"**修改文件**：{changed_files}"},
                    {"tag": "markdown", "content": f"**验证结果**：{validation_status}"},
                    {"tag": "markdown", "content": f"**自动生成测试**：{generated_test_status}\n{generated_test_detail}"},
                    {"tag": "markdown", "content": f"**人工处理建议**：\n{human_steps_text}"},
                    {"tag": "markdown", "content": f"**PR**：{record.pr_url or '未创建'}"},
                    {"tag": "markdown", "content": f"**修复记录**：{record.record_markdown_path or '未写入'}"},
                ],
            },
        }

    def _title_for_record(self, record: RepairRecord) -> str:
        if record.status in {"pr_created", "validated"}:
            return self.REVIEW_MESSAGE
        if record.status == "ignored":
            return self.IGNORED_MESSAGE
        return self.REPORT_MESSAGE

    def _generated_test_detail(self, generated_test) -> str:
        if generated_test is None or not generated_test.attempted:
            return "说明：本次未生成新的回归测试。"
        lines = []
        if generated_test.summary:
            lines.append(f"用例介绍：{generated_test.summary}")
        if generated_test.expected_behavior:
            lines.append(f"预期行为：{generated_test.expected_behavior}")
        if generated_test.test_cases:
            lines.append("覆盖用例：" + "、".join(generated_test.test_cases))
        return "\n".join(lines) or "说明：没有额外测试说明。"

    def _template_for_record(self, record: RepairRecord) -> str:
        if record.status in {"pr_created", "validated"}:
            return "green"
        if record.status == "ignored":
            return "blue"
        if record.status in {"failed", "needs_manual_intervention"}:
            return "red"
        return "orange"

    def _sign(self, timestamp: str, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        signature = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
        return base64.b64encode(signature).decode("utf-8")
