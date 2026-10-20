"""Download selected Canvas files into the configured course folder."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import logging
import os
import re
import stat
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse

from .errors import SyncCancelled, SyncError
from .store import account_id, write_json

logger = logging.getLogger("stella.elearning.file_sync")

_lock = threading.RLock()
_MAX_FILE_SIZE = 512 * 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)


def _component(value, fallback):
    # Canvas names are display data, never trusted path components.
    cleaned = re.sub(r"[^\w .()\-]+", "_", str(value or "").replace("/", "_").replace("\\", "_"))
    cleaned = cleaned.strip(" ._")[:90].rstrip(" ._")
    return cleaned or fallback


def _filename(raw):
    original = _component(raw.get("filename") or raw.get("display_name"), "course-file")
    stem, extension = os.path.splitext(original)
    file_id = _component(raw.get("id"), "unknown")
    return f"{stem[:70]}--{file_id}{extension[:16]}"


def _courseware_filename(raw):
    # Preserve the Canvas name unless it would escape the selected directory
    # or exceed a filesystem component limit.
    original = str(raw.get("filename") or raw.get("display_name") or "").replace("/", "_").replace("\\", "_")
    original = "".join(char for char in original if ord(char) >= 32).strip()
    if original in ("", ".", ".."):
        return _filename(raw)
    if len(original.encode("utf-8")) <= 240:
        return original
    stem, extension = os.path.splitext(original)
    suffix = f"--{_component(raw.get('id'), 'unknown')}{extension[:16]}"
    allowed = 240 - len(suffix.encode("utf-8"))
    while len(stem.encode("utf-8")) > allowed:
        stem = stem[:-1]
    return stem + suffix


def _versioned_filename(name, version):
    stem, extension = os.path.splitext(name)
    suffix = f"-更新-{version}{extension[:16]}"
    while len((stem + suffix).encode("utf-8")) > 240:
        stem = stem[:-1]
    return stem + suffix


def _courseware_folder(course):
    name = re.sub(r"^[A-Za-z]{2,}[-_]?\d{3,}(?:[.-]\d+)*\s+", "", str(course.get("name") or ""))
    safe = _component(name, "课程")
    while len(safe.encode("utf-8")) > 240:
        safe = safe[:-1]
    return safe


def _manifest_path(store, config, layout):
    path = store.file_sync_manifest_path(config)
    return path if layout == "managed" else path.with_name(path.stem + "-courseware.json")


def _manifest_name(value):
    return (isinstance(value, str) and value not in ("", ".", "..")
            and os.path.basename(value) == value and "\\" not in value
            and not any(ord(char) < 32 for char in value))


def _fingerprint(raw):
    fields = {key: raw.get(key) for key in ("id", "filename", "display_name", "size", "updated_at", "modified_at")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


def _open_directory(path):
    """Walk every component without following links, including root ancestors."""
    if not path.is_absolute() or ".." in path.parts:
        raise SyncError("课程文件保存目录无效")
    descriptor = None
    try:
        descriptor = os.open(path.anchor, _DIRECTORY_FLAGS)
        for component in path.parts[1:]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise SyncError("课程文件保存目录不可访问、权限不足或已移动，请检查目录及系统访问权限") from exc


def _check_directory(path, descriptor):
    current = _open_directory(path)
    try:
        actual, expected = os.fstat(current), os.fstat(descriptor)
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise SyncError("课程文件保存目录已移动，请重新选择目录")
    finally:
        os.close(current)


def _open_child(parent_fd, name):
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    try:
        return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise SyncError(f"课程资料路径不是安全目录：{name}") from exc


def _digest_existing(directory_fd, name, cancel_event=None):
    _check_cancelled(cancel_event)
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise SyncError(f"课程文件目标不是普通文件：{name}")
    descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        for block in iter(lambda: stream.read(128 * 1024), b""):
            _check_cancelled(cancel_event)
            digest.update(block)
    return digest.hexdigest()


class _TruncatedDownload(Exception):
    pass


def _check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise SyncCancelled("eLearning 文件同步已取消")


def _wait(cancel_event, seconds):
    _check_cancelled(cancel_event)
    if cancel_event is None:
        time.sleep(seconds)
    elif cancel_event.wait(seconds):
        raise SyncCancelled("eLearning 文件同步已取消")


def _download(client, url, directory_fd, cancel_event=None):
    _check_cancelled(cancel_event)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SyncError("课程文件下载地址必须是 HTTPS")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise SyncError("课程文件下载地址不能指向本机")
    try:
        if ipaddress.ip_address(host).is_private:
            raise SyncError("课程文件下载地址不能指向私有网络")
    except ValueError:
        pass
    for attempt in range(3):
        try:
            return _download_once(client, url, directory_fd, cancel_event)
        except _TruncatedDownload as exc:
            if attempt == 2:
                raise SyncError("课程文件传输中断，已重试 3 次；下次同步会继续尝试") from exc
            _wait(cancel_event, 2 ** attempt)


def _download_once(client, url, directory_fd, cancel_event=None):
    _check_cancelled(cancel_event)
    temporary = ".elearning-" + os.urandom(8).hex()
    descriptor = os.open(temporary, _FILE_FLAGS, 0o600, dir_fd=directory_fd)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as output, client.open(url, api=False) as response:
            headers = getattr(response, "headers", None)
            length = headers.get("Content-Length") if headers else None
            expected = int(length) if length and length.isdecimal() else None
            while True:
                _check_cancelled(cancel_event)
                try:
                    block = response.read(128 * 1024)
                except (http.client.HTTPException, URLError, TimeoutError, OSError) as exc:
                    raise _TruncatedDownload() from exc
                if not block:
                    break
                _check_cancelled(cancel_event)
                size += len(block)
                if size > _MAX_FILE_SIZE:
                    raise SyncError("课程文件超过 512 MB，未保存")
                output.write(block)
                digest.update(block)
            if expected is not None and size != expected:
                raise _TruncatedDownload()
            _check_cancelled(cancel_event)
            output.flush()
            os.fsync(output.fileno())
        return temporary, digest.hexdigest()
    except Exception:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        raise


def _load_manifest(store, config, root, layout):
    path = _manifest_path(store, config, layout)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if data.get("root") != str(root):
        return {"root": str(root), "courses": {}, "files": {}}
    return data


def _save_manifest(store, config, manifest, layout):
    write_json(_manifest_path(store, config, layout), manifest)


def _current_configuration(store, config, course_id):
    current = store.load_settings()
    if (account_id(current) != account_id(config)
            or current.get("file_sync_root") != config.get("file_sync_root")
            or course_id not in current.get("courses", [])):
        raise SyncError("课程文件同步设置已变更，请检查 eLearning 设置")


def sync_files(client, config, rows, store, cancel_event=None, layout="managed"):
    """Save changed files; return per-file errors without hiding briefing data."""
    if layout not in ("managed", "courseware"):
        raise ValueError("invalid eLearning file layout")
    if not rows:
        return []
    _check_cancelled(cancel_event)
    root = Path(config.get("file_sync_root") or "")
    if not root.is_absolute() or ".." in root.parts:
        return ["课程文件保存目录无效，请重新选择目录"]
    try:
        _current_configuration(store, config, str(rows[0][0]["id"]))
    except SyncError as exc:
        return [str(exc)]
    errors = []
    while not _lock.acquire(timeout=0.1):
        _check_cancelled(cancel_event)
    try:
        _check_cancelled(cancel_event)
        manifest = _load_manifest(store, config, root, layout)
        try:
            root_fd = _open_directory(root)
        except SyncError as exc:
            return [str(exc)]
        try:
            for index, (course, raw) in enumerate(rows, start=1):
                _check_cancelled(cancel_event)
                logger.info("[eLearningFileSync] processing %d/%d course=%s file=%s",
                            index, len(rows), course.get("id"), raw.get("id"))
                try:
                    _sync_one(client, config, store, root, root_fd, manifest, course, raw, cancel_event, layout)
                except SyncCancelled:
                    raise
                except Exception as exc:
                    logger.warning("[eLearningFileSync] failed %d/%d course=%s file=%s: %s",
                                   index, len(rows), course.get("id"), raw.get("id"), exc)
                    errors.append(f"{course.get('name', '课程')} / {raw.get('display_name') or raw.get('filename') or '文件'}：{exc}")
        except SyncCancelled:
            raise
        except SyncError as exc:
            errors.append(str(exc))
        finally:
            os.close(root_fd)
    finally:
        _lock.release()
    return errors


def _sync_one(client, config, store, root, materials_fd, manifest, course, raw, cancel_event=None, layout="managed"):
    _check_cancelled(cancel_event)
    course_id, file_id = str(course["id"]), str(raw["id"])
    _current_configuration(store, config, course_id)
    _check_directory(root, materials_fd)
    if isinstance(raw.get("size"), (int, float)) and raw["size"] > _MAX_FILE_SIZE:
        raise SyncError("课程文件超过 512 MB，未保存")
    if course_id not in manifest["courses"]:
        folder = (_courseware_folder(course) if layout == "courseware" else
                  f"{_component(course.get('name'), '课程')}--{_component(course_id, 'unknown')}")
        if layout == "courseware" and folder in manifest["courses"].values():
            folder = f"{folder[:70]}--{_component(course_id, 'unknown')}"
        manifest["courses"][course_id] = folder
    folder = manifest["courses"][course_id]
    if not _manifest_name(folder):
        raise SyncError("课程文件目录记录无效")
    course_fd = _open_child(materials_fd, folder)
    try:
        directory_fd = _open_child(course_fd, "课件") if layout == "courseware" else course_fd
    except Exception:
        os.close(course_fd)
        raise
    try:
        key = f"{course_id}:{file_id}"
        previous = manifest["files"].get(key) or {}
        remote = _fingerprint(raw)
        name = previous.get("name") or (_courseware_filename(raw) if layout == "courseware" else _filename(raw))
        if not _manifest_name(name):
            raise SyncError("课程文件名记录无效")
        if layout == "courseware" and not previous and any(
            entry.get("name") == name for other_key, entry in manifest["files"].items()
            if other_key != key and other_key.startswith(course_id + ":") and isinstance(entry, dict)
        ):
            stem, extension = os.path.splitext(name)
            name = f"{stem}--{_component(file_id, 'unknown')}{extension}"
        existing_digest = _digest_existing(directory_fd, name, cancel_event)
        if previous.get("remote") == remote and existing_digest == previous.get("sha256"):
            return
        # A locally edited file stays untouched until Canvas reports a new version.
        if previous.get("remote") == remote and existing_digest is not None:
            return
        url = raw.get("url")
        if not isinstance(url, str) or not url:
            raise SyncError("课程文件没有可用的下载地址")
        logger.info("[eLearningFileSync] downloading course=%s file=%s", course_id, file_id)
        temporary, downloaded_digest = _download(client, url, directory_fd, cancel_event)
        logger.info("[eLearningFileSync] downloaded course=%s file=%s", course_id, file_id)
        try:
            _check_cancelled(cancel_event)
            _current_configuration(store, config, course_id)
            existing_digest = _digest_existing(directory_fd, name, cancel_event)
            if layout == "courseware" and existing_digest == downloaded_digest:
                manifest["files"][key] = {"remote": remote, "name": name, "sha256": downloaded_digest}
                _save_manifest(store, config, manifest, layout)
                return
            # Never replace an existing user-visible file: it may be edited
            # after any digest check. New remote versions get exclusive names.
            if existing_digest is not None:
                base = _courseware_filename(raw) if layout == "courseware" else _filename(raw)
                name = _versioned_filename(base, remote[:8])
                if _digest_existing(directory_fd, name, cancel_event) is not None:
                    name = _versioned_filename(base, f"{remote[:8]}-{downloaded_digest[:8]}")
            destination = root / folder / "课件" / name if layout == "courseware" else root / folder / name
            store.record_audit(tool="elearning", operation="download", resource=str(destination), event="file_modify",
                   risk="L1", decision="allow", reason="Configured course file sync within the selected folder.")
            _check_cancelled(cancel_event)
            _current_configuration(store, config, course_id)
            _check_directory(destination.parent, directory_fd)
            os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    follow_symlinks=False)
            os.unlink(temporary, dir_fd=directory_fd)
            manifest["files"][key] = {"remote": remote, "name": name, "sha256": downloaded_digest}
            _save_manifest(store, config, manifest, layout)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
    finally:
        if directory_fd != course_fd:
            os.close(directory_fd)
        os.close(course_fd)
