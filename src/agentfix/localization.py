from __future__ import annotations


STATUS_LABELS = {
    "pr_created": "已创建 PR",
    "validated": "已验证通过",
    "reported": "已生成报告",
    "ignored": "已忽略",
    "failed": "处理失败",
    "needs_manual_intervention": "需要人工处理",
    "needs_human_verification": "需要人工确认",
    "needs_more_context": "需要更多上下文",
    "duplicate": "重复事件",
    "rejected": "已拒绝",
}

DISPOSITION_LABELS = {
    "repair_attempt": "尝试自动修复",
    "report_only": "仅生成报告",
    "needs_more_context": "需要更多上下文",
    "ignored": "忽略事件",
}

ROOT_CAUSE_LABELS = {
    "code": "代码缺陷",
    "configuration": "配置问题",
    "environment": "运行环境问题",
    "external_dependency": "外部依赖问题",
    "data": "数据问题",
    "benign_log": "预期内业务或客户端日志",
    "non_error_event": "非错误事件",
    "unknown": "未知",
}

RISK_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}


def status_label(value: str | None) -> str:
    return _label(value, STATUS_LABELS)


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

