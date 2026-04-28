from __future__ import annotations

from agentfix.config import FeishuSettings, RecordsSettings
from agentfix.feishu import FeishuNotifier
from agentfix.models import RepairRecord, RepairResult
from agentfix.repair_records import RepairRecordWriter


def test_repair_record_writer_creates_json_and_markdown(tmp_path) -> None:
    writer = RepairRecordWriter(RecordsSettings(root="records", auto_commit=False), project_root=tmp_path)
    record = RepairRecord(
        incident_id="inc-1",
        target="svc",
        source="incident_webhook",
        status="pr_created",
        message="Fixed it.",
        pr_url="https://github.com/org/repo/pull/1",
        repair_result=RepairResult(root_cause_summary="Fixed it.", status="pr_created"),
    )

    written = writer.write(record)

    assert written.record_json_path is not None
    assert written.record_markdown_path is not None
    assert (tmp_path / "records" / "inc-1.json").exists()
    assert (tmp_path / "records" / "inc-1.md").exists()


def test_feishu_card_contains_review_message() -> None:
    notifier = FeishuNotifier(FeishuSettings(webhook_url="https://example.invalid/webhook"))
    record = RepairRecord(
        incident_id="inc-1",
        target="svc",
        source="incident_webhook",
        status="pr_created",
        message="Fixed it.",
        pr_url="https://github.com/org/repo/pull/1",
        repair_result=RepairResult(
            root_cause_summary="Fixed it.",
            status="pr_created",
            changed_files=["src/app.ts"],
            pr_url="https://github.com/org/repo/pull/1",
        ),
    )

    payload = notifier._build_payload(record)

    assert payload["msg_type"] == "interactive"
    assert FeishuNotifier.REVIEW_MESSAGE in payload["card"]["header"]["title"]["content"]
    element_text = "\n".join(element["content"] for element in payload["card"]["elements"])
    assert "https://github.com/org/repo/pull/1" in element_text
    assert "Generated test" in element_text
