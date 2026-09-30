"""User-editable Markdown instructions, including legacy rule conversion."""

DEFAULT_RULE_TEXT = """# 每日简报规则

## 目标
帮助我掌握需要处理的事项和有价值的信息，避免遗漏截止日期。

## 筛选原则
- 保留课程、作业、考试、会议、账单和需要回复或确认的信息。
- 排除广告、垃圾邮件和没有实质内容的重复通知。
- 不要仅因为发件地址是 noreply 就排除重要通知。
- 如果无法确定一条信息是否重要，优先保留并说明原因。

## 简报写作要求
- 按紧急程度排序，区分需要处理的事项和知会信息。
- 清楚写出任务、截止时间和下一步行动，缺失的信息不要猜测。
- 合并同一邮件线程中的重复信息，保留关键变化。
- 使用中文 Markdown，表达简洁，条目数量不设上限。
"""


def rule_document(rule) -> str:
    if rule.text.strip():
        return rule.text
    field = {"sender": "发件人", "sender_email": "发件地址", "sender_domain": "发件域名",
             "title": "标题", "list_id": "邮件列表 ID"}[rule.match_field]
    op = "等于" if rule.match_op == "eq" else "包含"
    action = "保留" if rule.action == "include" else "排除"
    return f"{action}{field}{op}“{rule.match_value}”的信息。" + (f"\n说明：{rule.note}" if rule.note else "")
