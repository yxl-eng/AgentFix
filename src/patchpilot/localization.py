from __future__ import annotations


PUBLIC_STATUS_ALIASES = {
    "pr_created": "fixed",
    "validated": "fixed",
    "reported": "needs_manual_intervention",
    "needs_more_context": "needs_manual_intervention",
    "failed": "needs_manual_intervention",
}

STATUS_LABELS = {
    "fixed": "已修复",
    "needs_human_verification": "需要人工验证",
    "needs_manual_intervention": "需要人工处理",
    "ignored": "已忽略",
    "duplicate": "重复事件",
    "rejected": "已拒绝",
}

DISPOSITION_LABELS = {
    "repair_attempt": "尝试自动修复",
    "report_only": "生成处理报告",
    "needs_more_context": "需要更多上下文",
    "ignored": "忽略事件",
}

ROOT_CAUSE_LABELS = {
    "code": "代码缺陷",
    "configuration": "配置问题",
    "environment": "运行环境问题",
    "external_dependency": "外部依赖问题",
    "data": "数据问题",
    "benign_log": "预期业务日志",
    "non_error_event": "非错误事件",
    "unknown": "未知",
}

RISK_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}


def public_status(value: str | None) -> str:
    if not value:
        return "needs_manual_intervention"
    return PUBLIC_STATUS_ALIASES.get(value, value)


def status_label(value: str | None) -> str:
    return _label(public_status(value), STATUS_LABELS)


def disposition_label(value: str | None) -> str:
    return _label(value, DISPOSITION_LABELS)


def root_cause_label(value: str | None) -> str:
    return _label(value, ROOT_CAUSE_LABELS)


def risk_label(value: str | None) -> str:
    return _label(value, RISK_LABELS)


def bool_label(value: bool | None) -> str:
    return "是" if value else "否"


def _label(value: str | None, mapping: dict[str, str]) -> str:
    if not value:
        return "未知"
    return mapping.get(value, value)
