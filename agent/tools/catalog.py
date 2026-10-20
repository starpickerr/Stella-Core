"""User-facing catalog of built-in tools.

The catalog is display copy. It does not register tools or change which
tools an agent receives.
"""

from __future__ import annotations

MEMORY_IDS = frozenset({"memory_search", "memory_get"})
MEMORY_REASON = {
    "zh": "仅在启用记忆的对话中可用，不会加入通用工具列表。",
    "en": "Available only in a conversation with memory, and not added to the general tool list.",
}
MISSING_REASON = {
    "zh": "当前环境缺少依赖或尚未启用。",
    "en": "A dependency is missing or the tool is not enabled.",
}


def _entry(tool_id, zh_title, en_title, zh_intro, en_intro, zh_detail, en_detail):
    return {
        "id": tool_id,
        "title": {"zh": zh_title, "en": en_title},
        "intro": {"zh": zh_intro, "en": en_intro},
        "detail": {"zh": zh_detail, "en": en_detail},
    }


CATALOG = [
    _entry("read", "读取文件", "Read Files",
           "读取工作区中的文件内容，并查看支持的文档内容或媒体文件信息。",
           "Read workspace files, supported documents, and media file information.",
           "只能读取当前工作区里已有的文件。它不会修改文件，也不能把工作区以外的路径当作可读内容。",
           "Reads files that already exist in the current workspace. It does not modify files or treat paths outside the workspace as readable content."),
    _entry("write", "写入文件", "Write Files",
           "创建文件或完整重写文件内容。",
           "Create files or replace an entire file's contents.",
           "会替换目标文件的全部内容。适合新建或整篇重写，不适合只改其中几行。",
           "Replaces the entire contents of the target file. Use it to create a file or rewrite it, not to change a few lines."),
    _entry("edit", "编辑文件", "Edit Files",
           "按指定文本修改已有文件，适合局部编辑。",
           "Change existing files by replacing specific text.",
           "只替换能唯一定位的原有文本。找不到这段文本，或它在文件里出现多次时，不会改动文件。",
           "Replaces one uniquely matched passage. If that passage is missing or appears more than once, the file stays unchanged."),
    _entry("bash", "执行命令", "Run Commands",
           "在工作环境中执行命令并读取输出。",
           "Run commands in the workspace and read their output.",
           "命令在当前工作环境中运行，并受现有权限约束。超时、失败或被拒绝时会返回原因，不会假装已经完成。",
           "Commands run in the current workspace and stay inside the existing permission boundary. Timeouts, failures, and refusals return a reason."),
    _entry("ls", "浏览目录", "List Directory",
           "查看目录中的文件和子目录。",
           "Browse files and subdirectories in a directory.",
           "列出指定目录的直接内容。它不读取文件正文，也不会递归展开整个工作区。",
           "Lists the immediate contents of a directory. It does not read file bodies or expand the whole workspace."),
    _entry("send", "发送本地文件", "Send Local Files",
           "将本地图片、音视频或文档作为文件发给用户。",
           "Send a local image, media file, or document to the user.",
           "发送的是工作区里已经存在的文件。它不生成新文件，也不能把未保存的内容当作附件。",
           "Sends a file that already exists in the workspace. It does not create a file or attach unsaved content."),
    _entry("search_files", "搜索文件", "Search Files",
           "在工作区中按名称或内容查找文件。",
           "Find workspace files by name or content.",
           "在工作区范围内查找匹配的文件。结果是文件位置，不是对文件的修改。",
           "Searches within the workspace. The result is where a file matches, not a change to that file."),
    _entry("memory_search", "搜索记忆", "Search Memory",
           "检索 Agent 的长期记忆；启用知识库时也可检索知识内容。",
           "Search the agent's long-term memory and, when enabled, knowledge base.",
           "只在带有记忆能力的对话中可用。它可以查找记忆和已启用的知识内容，但不会因此把这项能力加进所有对话。",
           "Available only in a conversation that has memory. It can search memory and enabled knowledge, without adding that ability to every conversation."),
    _entry("memory_get", "读取记忆", "Read Memory",
           "读取指定记忆文件或行段；启用知识库时也可读取知识页面。",
           "Read a memory file or line range and, when enabled, knowledge pages.",
           "只读取已经定位到的记忆或知识页面。没有记忆上下文时不可用，也不会改写这些内容。",
           "Reads a memory file or knowledge page that has already been located. It is unavailable without a memory context and does not rewrite that content."),
    _entry("evolution_undo", "撤销自主学习", "Undo Self-Learning",
           "根据已有备份撤销一次自主学习对记忆或技能文件的修改。",
           "Restore memory or skill files from a backup before a self-learning change.",
           "只能恢复已经留下备份的那一次改动。没有对应备份时不会猜测应该恢复成什么。",
           "Restores one self-learning change that still has a backup. Without that backup it does not guess what to restore."),
    _entry("subagent", "分派子任务", "Delegate Task",
           "将独立工作交给子 Agent 执行并汇总结果。",
           "Delegate independent work to a subagent and collect its result.",
           "适合可以分开完成的工作。子任务仍遵守同样的权限，不能借分派扩大可访问范围。",
           "Use it for work that can be done separately. The subagent keeps the same permission boundary and cannot widen access."),
    _entry("bills", "管理账单", "Manage Bills",
           "记录、查询和维护个人收支，并查看月度或年度汇总。",
           "Record and manage personal income and expenses, with monthly or yearly summaries.",
           "处理 Stella 中的个人收支记录和汇总。它不连接银行，也不会代替用户确认一笔未经说明的账目。",
           "Manages personal income and expense records kept in Stella. It does not connect to a bank or confirm an unexplained entry."),
    _entry("briefing", "管理简报", "Manage Briefings",
           "生成、更新和查看每日简报，并管理简报条目与规则。",
           "Generate, update, and inspect daily briefings, items, and rules.",
           "围绕已经配置的简报来源工作。来源未配置或生成失败时，会保留失败原因，而不是给出一份空白简报冒充完成。",
           "Works with briefings whose sources are already configured. A missing source or a failed run keeps its reason instead of presenting an empty briefing as finished."),
    _entry("calendar", "管理日程", "Manage Calendar",
           "查看、创建和维护个人日程及分类，包括重复日程。",
           "View and manage personal events and categories, including recurring events.",
           "维护 Stella 中的日程和分类。修改重复日程时作用于用户确认的范围，不会擅自改掉整个系列。",
           "Maintains events and categories in Stella. A change to a repeating event stays within the range the user confirmed."),
    _entry("apple", "Apple 集成", "Apple Integration",
           "查询和管理 Apple 日历、提醒事项的连接及同步操作。",
           "Manage Apple Calendar and Reminders connections and sync operations.",
           "依赖本机已经授予的 Apple 访问权限。未授权或同步失败时只报告状态，不会把未确认的数据写入另一边。",
           "Depends on Apple access already granted on this computer. If access or sync fails, it reports that state and does not write unconfirmed data to the other side."),
    _entry("todos", "管理事务", "Manage Tasks",
           "创建、拆解、排序和更新事务及其状态。",
           "Create, break down, order, and update tasks and their status.",
           "管理 Stella 事务清单中的事项、子事项和状态。它不代替用户完成事项，也不会删除没有明确要求删除的记录。",
           "Manages items, subitems, and status in the Stella task list. It does not complete an item for the user or delete a record that was not explicitly requested."),
    _entry("elearning", "读取课程资料", "Read Course Materials",
           "查询 eLearning 课程信息与文件，并在授权后保存课程文件。",
           "Read eLearning course information and files, and save files when authorized.",
           "先读取课程信息。保存课程文件需要已经授予的授权；没有授权时不会下载。",
           "Reads course information first. Saving a course file requires an authorization that is already granted; otherwise nothing is downloaded."),
    _entry("skill", "管理技能", "Manage Skills",
           "创建或更新 Stella 自定义技能及其资源。",
           "Create or update Stella custom skills and their resources.",
           "只修改 Stella 的自定义技能。启用或停用现有技能仍由能力页面的开关完成，这个工具不会偷偷切换开关。",
           "Changes Stella custom skills. Enabling or disabling an existing skill stays on the capability page switch; this tool does not flip that switch quietly."),
    _entry("env_config", "管理密钥配置", "Manage Key Settings",
           "查看或更新受保护的 API 密钥和相关配置。",
           "View or update protected API keys and related settings.",
           "配置值受现有保护机制约束。目录和界面只说明这项能力，不会展示已保存的密钥。",
           "Stored values stay behind the existing protection. The catalog and the page describe the capability and never display a saved key."),
    _entry("scheduler", "管理定时任务", "Manage Scheduled Tasks",
           "创建、查询和维护提醒或周期性任务。",
           "Create, inspect, and manage reminders or recurring tasks.",
           "用于需要稍后或重复执行的任务。主动通知只能发往一个已连接的允许渠道，不能配置备用渠道。",
           "Use it when work should run later or on a repeat. A proactive notice goes to one connected allowed channel and cannot set a backup channel."),
    _entry("web_search", "网页搜索", "Search the Web",
           "使用已配置的搜索服务查找实时网页信息。",
           "Find current web information through a configured search provider.",
           "需要已经配置的搜索服务。没有配置时能力仍列在目录中，但不会返回虚构的搜索结果。",
           "Needs a search provider that is already configured. Without one, the capability stays in the catalog and does not invent results."),
    _entry("web_fetch", "读取网页", "Read Web Content",
           "获取网页正文或受支持的在线文档内容。",
           "Retrieve readable web pages or supported online documents.",
           "读取给定地址的公开正文。登录墙、不受支持的格式或网络失败会返回原因，而不是一段猜测的正文。",
           "Reads the public text of a given address. A login wall, an unsupported format, or a network failure returns a reason instead of guessed text."),
    _entry("vision", "图像识别", "Analyze Images",
           "分析本地或在线图片，识别内容或提取文字。",
           "Analyze local or online images and extract content or text.",
           "需要可用的图像识别配置。图片无法读取或服务不可用时，会说明原因，不会编造图中内容。",
           "Needs an image service that is available. If the image cannot be read or the service is unavailable, it explains why and does not invent the contents."),
    _entry("browser", "操作浏览器", "Control Browser",
           "浏览网页并与页面元素交互，读取页面内容。",
           "Navigate pages, interact with elements, and read web content.",
           "通过受控浏览器打开页面并与可见元素交互。它遵守现有权限，不会绕过登录或站点限制。",
           "Opens pages in the controlled browser and interacts with visible elements. It stays inside the existing permissions and does not bypass a login or a site restriction."),
    _entry("agent_hub", "外部智能体", "External Agents",
           "向已配置的外部智能体提交任务，查询进度或请求取消。",
           "Delegate tasks to configured external agents, inspect progress, or request cancellation.",
           "需要启用智能体插件并配置接入方式。外部调用遵守连接权限；未实现的能力会明确返回不支持。",
           "Requires the Agent Hub plugin and a configured access mode. External calls follow connection permissions; unimplemented capabilities return unsupported."),

]


def build_catalog(loaded_ids):
    """Return the public catalog. ``loaded_ids`` are tools the process can construct."""
    loaded = set(loaded_ids)
    rows = []
    for item in CATALOG:
        row = {
            "id": item["id"],
            "title": dict(item["title"]),
            "intro": dict(item["intro"]),
            "detail": dict(item["detail"]),
        }
        if item["id"] in MEMORY_IDS:
            row["available"] = False
            row["reason"] = dict(MEMORY_REASON)
        elif item["id"] in loaded:
            row["available"] = True
            row["reason"] = None
        else:
            row["available"] = False
            row["reason"] = dict(MISSING_REASON)
        rows.append(row)
    return rows


def tools_payload():
    """Build the API payload without registering memory tools or MCP tools."""
    from agent.tools.tool_manager import ToolManager

    manager = ToolManager()
    manager.load_tools()
    return {"status": "success", "tools": build_catalog(set(manager.tool_classes))}
