"""Local, scoped authoring of custom Stella skills."""

from __future__ import annotations

import os
import re
import stat
import uuid
from pathlib import Path

from agent.skills.frontmatter import parse_frontmatter
from common.state_dir import skills_dir

_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)


def _name(value: str) -> str:
    if not isinstance(value, str) or len(value) > 64 or not _NAME.fullmatch(value):
        raise ValueError("技能名称只能使用小写字母、数字和连字符，最长 64 字符")
    return value


def _content(value: str, limit: int) -> bytes:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("技能内容必须是非空文本")
    encoded = value.encode("utf-8")
    if len(encoded) > limit:
        raise ValueError("技能内容超过大小限制")
    return encoded


def _skill_document(name: str, value: str) -> tuple[bytes, str]:
    encoded = _content(value, 256 * 1024)
    if not value.startswith("---\n"):
        raise ValueError("SKILL.md 需要 YAML frontmatter")
    metadata = parse_frontmatter(value)
    description = metadata.get("description")
    if metadata.get("name") != name or not isinstance(description, str) or not description.strip():
        raise ValueError("SKILL.md 的 name 必须与目录名一致，且 description 不能为空")
    return encoded, description.strip()


def _write(fd: int, content: bytes) -> None:
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_file(directory_fd: int, filename: str, content: bytes) -> None:
    temporary = ".stella-skill-" + uuid.uuid4().hex
    try:
        _write(os.open(temporary, _FILE_FLAGS, 0o600, dir_fd=directory_fd), content)
        os.replace(temporary, filename, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _resource_parts(value: str) -> list[str]:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ValueError("无效的技能资源路径")
    parts = value.split("/")
    if (len(parts) < 2 or len(parts) > 8 or parts[0] not in ("scripts", "references", "assets")
            or any(part in ("", ".", "..") or part.startswith(".") or len(part.encode("utf-8")) > 240
                   for part in parts)):
        raise ValueError("资源必须位于 scripts/、references/ 或 assets/，且不能越过技能目录")
    return parts


class SkillAuthoring:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else skills_dir(ensure=True)

    def _open_root(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        return os.open(str(self.root), _DIR_FLAGS)

    def _refresh(self) -> None:
        from agent.skills.manager import SkillManager
        SkillManager(custom_dir=str(self.root))

    def create(self, name: str, document: str) -> dict:
        name = _name(name)
        content, description = _skill_document(name, document)
        # A custom skill must not silently shadow a bundled skill.
        bundled = Path(__file__).parents[2] / "skills" / name
        if bundled.exists():
            raise ValueError("同名内置技能已存在")
        root_fd = self._open_root()
        try:
            os.mkdir(name, 0o700, dir_fd=root_fd)
            skill_fd = os.open(name, _DIR_FLAGS, dir_fd=root_fd)
            try:
                _write(os.open("SKILL.md", _FILE_FLAGS, 0o600, dir_fd=skill_fd), content)
            except Exception:
                try:
                    os.unlink("SKILL.md", dir_fd=skill_fd)
                except FileNotFoundError:
                    pass
                os.rmdir(name, dir_fd=root_fd)
                raise
            finally:
                os.close(skill_fd)
        finally:
            os.close(root_fd)
        self._refresh()
        return {"name": name, "description": description, "path": str(self.root / name / "SKILL.md")}

    def update(self, name: str, document: str) -> dict:
        name = _name(name)
        content, description = _skill_document(name, document)
        root_fd = self._open_root()
        try:
            skill_fd = os.open(name, _DIR_FLAGS, dir_fd=root_fd)
            try:
                current = os.stat("SKILL.md", dir_fd=skill_fd, follow_symlinks=False)
                if not stat.S_ISREG(current.st_mode):
                    raise ValueError("SKILL.md 不是普通文件")
                _atomic_file(skill_fd, "SKILL.md", content)
            finally:
                os.close(skill_fd)
        finally:
            os.close(root_fd)
        self._refresh()
        return {"name": name, "description": description, "path": str(self.root / name / "SKILL.md")}

    def write_resource(self, name: str, path: str, text: str) -> dict:
        name = _name(name)
        parts = _resource_parts(path)
        content = _content(text, 1024 * 1024)
        root_fd = self._open_root()
        opened = []
        try:
            current_fd = os.open(name, _DIR_FLAGS, dir_fd=root_fd)
            opened.append(current_fd)
            if not stat.S_ISREG(os.stat("SKILL.md", dir_fd=current_fd, follow_symlinks=False).st_mode):
                raise ValueError("技能缺少有效的 SKILL.md")
            for component in parts[:-1]:
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                current_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
                opened.append(current_fd)
            try:
                existing = os.stat(parts[-1], dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None and not stat.S_ISREG(existing.st_mode):
                raise ValueError("资源目标不是普通文件")
            _atomic_file(current_fd, parts[-1], content)
        finally:
            for fd in reversed(opened):
                os.close(fd)
            os.close(root_fd)
        return {"name": name, "path": str(self.root / name / path), "bytes_written": len(content)}
