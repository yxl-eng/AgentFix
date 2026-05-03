from __future__ import annotations

from agentfix.config import FeishuSettings, RecordsSettings
from agentfix.feishu import FeishuNotifier
from agentfix.models import AnalysisResult, GeneratedTestResult, RepairRecord, RepairResult
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


def test_repair_record_markdown_contains_approach_and_test_details(tmp_path) -> None:
    writer = RepairRecordWriter(RecordsSettings(root="records", auto_commit=False), project_root=tmp_path)
    record = RepairRecord(
        incident_id="inc-2",
        target="svc",
        source="incident_webhook",
        status="validated",
        message="取消订单时先释放库存导致异常。",
        decision_reason="日志包含源码级异常信号。",
        repair_result=RepairResult(
            root_cause_summary="取消订单时先释放库存导致异常。",
            status="validated",
            analysis=AnalysisResult(
                root_cause_summary="取消订单时先释放库存导致异常。",
                confidence=0.9,
                repair_plan=["先判断订单支付状态，再释放库存。"],
            ),
            generated_test=GeneratedTestResult(
                attempted=True,
                framework="python-pytest",
                test_path="tests/test_agentfix_order.py",
                summary="覆盖已支付旧订单取消流程。",
                expected_behavior="返回 409，不再抛出 KeyError。",
                test_cases=["test_cancel_paid_legacy_order_returns_409"],
            ),
        ),
    )

    written = writer.write(record)
    markdown = (tmp_path / "records" / "inc-2.md").read_text(encoding="utf-8")

    assert written.record_markdown_path is not None
    assert "## 修复思路" in markdown
    assert "先判断订单支付状态，再释放库存。" in markdown
    assert "## 自动生成测试说明" in markdown
    assert "test_cancel_paid_legacy_order_returns_409" in markdown
    assert "决策理由" not in markdown


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
    assert "自动生成测试" in element_text
    assert "决策理由" not in element_text
