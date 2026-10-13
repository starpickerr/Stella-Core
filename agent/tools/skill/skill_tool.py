"""Agent entry point for authoring local custom skills."""

from agent.skills.authoring import SkillAuthoring
from agent.tools.base_tool import BaseTool, ToolResult


class SkillTool(BaseTool):
    name = "skill"
    required_capability = "admin"
    description = (
        "创建或更新 Stella 自定义技能。用户要求新建技能时，直接用 action='create'、"
        "name 和完整 SKILL.md 文本；修改现有技能用 action='update'。"
        "只有额外脚本或参考文件才用 action='write_resource'，path 限于 "
        "scripts/、references/、assets/。技能库不能通过 write/edit/bash 修改。"
    )
    params = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "update", "write_resource"]},
            "name": {"type": "string", "description": "小写字母、数字和连字符组成的技能名"},
            "content": {"type": "string", "description": "完整 SKILL.md 或资源文件的文本内容"},
            "path": {"type": "string", "description": "write_resource 时相对技能目录的文件路径"},
        },
        "required": ["action", "name", "content"],
        "additionalProperties": False,
    }

    def execute(self, params):
        try:
            authoring = SkillAuthoring()
            action = params.get("action")
            if action == "create":
                result = authoring.create(params.get("name"), params.get("content"))
            elif action == "update":
                result = authoring.update(params.get("name"), params.get("content"))
            elif action == "write_resource":
                result = authoring.write_resource(
                    params.get("name"), params.get("path"), params.get("content"))
            else:
                raise ValueError("无效的技能操作")
            agent = getattr(self, "context", None)
            if agent is not None and hasattr(agent, "refresh_skills"):
                agent.refresh_skills()
            return ToolResult.success(result)
        except (OSError, ValueError) as exc:
            return ToolResult.fail(str(exc))
