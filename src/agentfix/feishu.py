from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

from agentfix.config import FeishuSettings
from agentfix.models import RepairRecord


class FeishuNotifier:
    REVIEW_MESSAGE = "我发现了一个 Bug 并已为您修复，请 Review"

    def __init__(self, settings: FeishuSettings) -> None:
        self.settings = settings

    def notify_repair(self, record: RepairRecord) -> tuple[bool, str]:
        webhook_url = self.settings.resolved_webhook_url()
        if not webhook_url:
            return False, f"Feishu webhook missing. Set {self.settings.webhook_url_env_var}."
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
        changed_files = ", ".join(result.changed_files) if result and result.changed_files else "none"
        validation_status = "not available"
        if result and result.validation:
            validation_status = "passed" if result.validation.is_success else "failed"
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": self.REVIEW_MESSAGE},
                    "template": "green" if record.status in {"pr_created", "validated"} else "orange",
                },
                "elements": [
                    {"tag": "markdown", "content": f"**目标服务**：{record.target}"},
                    {"tag": "markdown", "content": f"**状态**：{record.status}"},
                    {"tag": "markdown", "content": f"**摘要**：{record.message}"},
                    {"tag": "markdown", "content": f"**改动文件**：{changed_files}"},
                    {"tag": "markdown", "content": f"**验证结果**：{validation_status}"},
                    {"tag": "markdown", "content": f"**PR**：{record.pr_url or 'not created'}"},
                    {"tag": "markdown", "content": f"**修复记录**：{record.record_markdown_path or 'not written'}"},
                ],
            },
        }

    def _sign(self, timestamp: str, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        signature = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
        return base64.b64encode(signature).decode("utf-8")
