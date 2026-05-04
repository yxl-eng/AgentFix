from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

from patchpilot.config import FeishuSettings
from patchpilot.localization import public_status, status_label
from patchpilot.models import RepairRecord


class FeishuNotifier:
    REVIEW_MESSAGE = "PatchPilot 已修复一个 Bug，请 Review"
    ACTION_MESSAGE = "PatchPilot 发现一个异常，需要人工处理"
    IGNORED_MESSAGE = "PatchPilot 已忽略一条非异常日志"

    def __init__(self, settings: FeishuSettings) -> None:
        self.settings = settings

    def notify_repair(self, record: RepairRecord) -> tuple[bool, str]:
        webhook_url = self.settings.resolved_webhook_url()
        if not webhook_url:
            return False, f"飞书机器人 Webhook 未配置，请在 patchpilot.local.yaml 中配置 feishu.webhook_url。"
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
        normalized_status = public_status(record.status)
        changed_files = "、".join(result.changed_files) if result and result.changed_files else "无"
        root_cause = record.message or (result.root_cause_summary if result else "") or "无"
        repair_summary = self._repair_summary(record)
        validation_summary = self._validation_summary(record)
        entry = record.pr_url or (result.pr_url if result else None) or record.record_markdown_path or "未生成"

        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": self._title_for_status(normalized_status)},
                    "template": self._template_for_status(normalized_status),
                },
                "elements": [
                    {"tag": "markdown", "content": f"**目标服务**：{record.target}"},
                    {"tag": "markdown", "content": f"**状态**：{status_label(normalized_status)}"},
                    {"tag": "markdown", "content": f"**根因摘要**：{root_cause}"},
                    {"tag": "markdown", "content": f"**修复摘要**：{repair_summary}"},
                    {"tag": "markdown", "content": f"**修改文件**：{changed_files}"},
                    {"tag": "markdown", "content": f"**验证摘要**：{validation_summary}"},
                    {"tag": "markdown", "content": f"**PR / 报告**：{entry}"},
                ],
            },
        }

    def _repair_summary(self, record: RepairRecord) -> str:
        result = record.repair_result
        if result and result.changed_files:
            if result.analysis and result.analysis.repair_plan:
                return "；".join(result.analysis.repair_plan[:2])
            return f"已修改 {len(result.changed_files)} 个文件并完成验证。"
        if public_status(record.status) == "ignored":
            return "Planner 判断为预期日志或噪声，未修改代码。"
        reason = (result.failure_reason if result else None) or record.decision_reason
        return f"未自动修改代码。{reason or '需要开发者查看完整报告。'}"

    def _validation_summary(self, record: RepairRecord) -> str:
        result = record.repair_result
        if not result or not result.validation:
            return "未执行验证"
        if public_status(record.status) == "needs_human_verification":
            return "语法/编译检查通过，但自动生成的回归测试未通过，需要人工确认。"
        if result.validation.is_success:
            command_count = len(result.validation.commands)
            return f"通过。执行 {command_count} 条验证命令。"
        failures = "；".join(result.validation.failure_summary[:2]) if result.validation.failure_summary else "无摘要"
        return f"失败：{failures}"

    def _title_for_status(self, status: str) -> str:
        if status == "fixed":
            return self.REVIEW_MESSAGE
        if status == "ignored":
            return self.IGNORED_MESSAGE
        return self.ACTION_MESSAGE

    def _template_for_status(self, status: str) -> str:
        if status == "fixed":
            return "green"
        if status == "ignored":
            return "blue"
        if status == "needs_human_verification":
            return "orange"
        return "red"

    def _sign(self, timestamp: str, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        signature = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
        return base64.b64encode(signature).decode("utf-8")
