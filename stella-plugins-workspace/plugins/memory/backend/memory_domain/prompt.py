"""Memory-specific behavior contributed only by an available plugin."""
from datetime import datetime


def context_prompt(language, content):
    today = datetime.now().strftime('%Y-%m-%d')
    if language == 'en':
        rules = """## Memory
Before answering about past events, decisions, people or preferences, recall with memory_search unless the loaded memory already supplies the answer. Read known paths with memory_get; if search is empty, check recent daily records and acknowledge missing evidence.
Use memory_write for enduring preferences, important decisions and useful task progress. Store concise durable facts in MEMORY.md and daily events in memory/{today}.md (append=true to add a record). Read before replacing existing content. A one-off exclusion for the current request is not a long-term memory. Never store credentials or secrets. Never write memory using general file tools or shell.
Use memory naturally without exposing internal file names.

### Current long-term memory
"""
    else:
        rules = """## 长期记忆
回答过往事件、决策、人物关系或偏好前，必须先用 memory_search 检索；当前已加载的记忆足够时无需重复。已知路径使用 memory_get；检索无结果时检查近期日记，并如实说明缺失信息。
使用 memory_write 保存稳定偏好、重要决策和有价值的任务进展。长期核心信息写入 MEMORY.md，当天事件写入 memory/{today}.md（追加记录指定 append=true）；替换已有内容前先阅读。仅适用于当前请求的排除条件不构成长期记忆。禁止记录密钥等敏感信息，不要使用通用文件工具或终端写记忆。
自然使用记忆，无需向用户暴露内部文件名。

### 当前长期记忆
"""
    return rules.replace('{today}', today) + content[-20000:]
