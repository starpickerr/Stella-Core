"""Knowledge-specific behavior contributed only by an available plugin."""

def context_prompt(language, content):
    if language == 'en':
        rules = """## Knowledge
Use knowledge_search to find stored knowledge and knowledge_get to read documents.
When a shared article, a substantial conclusion, an important entity or a technical concept is worth keeping, save it in the same turn with knowledge_write. Follow existing categories; suggested categories are sources/, analysis/, entities/ and concepts/. Link only to existing related pages.
Write with action=create_document, payload={path: "sources/topic.md", content: "Markdown"}; use overwrite=true only when updating an existing document after reading it. The plugin maintains index.md automatically. Never use general file tools or shell to change knowledge documents. Never store secrets. Knowledge contains structured material, separate from personal memory.
Use lowercase kebab-case file names and one topic per page. Start with a Markdown title, include a source URL or description when applicable, then concise content, key points and links to related pages. Update existing pages rather than duplicating them. Cite saved pages in replies with links prefixed by knowledge/; use relative links between documents.

### Current knowledge index
"""
    else:
        rules = """## 知识库
使用 knowledge_search 检索、knowledge_get 阅读已保存的知识。
用户分享的文章、深入讨论的结论、重要实体或技术概念值得保留时，在当轮使用 knowledge_write 保存。延续已有分类，可参考 sources/、analysis/、entities/、concepts/；只链接已存在的相关页面。
写入使用 action=create_document，payload={path: "sources/topic.md", content: "Markdown正文"}；更新已有文档须先阅读，再指定 overwrite=true。插件自动维护 index.md。不要用通用文件工具或终端修改知识文档，不保存密钥等敏感内容。结构化知识与个人长期记忆分别保存。
文件名使用小写连字符，一页一个主题。正文从 Markdown 标题开始，有明确来源时注明来源链接或说明，然后写简明正文、关键点和相关页面链接。更新已有页面，避免重复；回复中用 knowledge/ 前缀链接引用页面，文档之间使用相对链接。

### 当前知识索引
"""
    return rules + content[:20000]
