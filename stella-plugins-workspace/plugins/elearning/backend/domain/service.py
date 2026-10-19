"""eLearning domain service: courses, fetch, file sync and plugin-owned settings.

No Stella ``agent.*`` / ``common.*`` imports. Authentication material, saved
sessions, course selection, download manifests and sync cursors all live in the
host-provided ``dataDir`` (see :mod:`domain.store`).
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .client import ensure_login
from .courses import course_list, list_files, select_courses
from .errors import LoginRequired, SyncCancelled, SyncError
from .file_sync import sync_files as _sync_files
from .source import ElearningSource
from .store import ElearningStore
from .utils import parse_date


class ElearningService:
    def __init__(self, data_dir, *, legacy_dir=None, client_factory=None, clock=None,
                 cancel_event: threading.Event | None = None):
        self.store = ElearningStore(Path(data_dir))
        self.client_factory = client_factory
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.cancel_event = cancel_event
        if legacy_dir:
            self.store.import_legacy(legacy_dir)

    # ----- plumbing ----------------------------------------------------
    def _check_cancelled(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise SyncCancelled("eLearning 读取已取消")

    def _client(self, cfg):
        self._check_cancelled()
        if self.client_factory is None:
            return ensure_login(cfg, self.store, cancel_event=self.cancel_event)
        client = self.client_factory(cfg)
        if hasattr(client, "cancel_event"):
            client.cancel_event = self.cancel_event
        self._check_cancelled()
        return client

    def _credentialed_settings(self):
        cfg = self.store.load_settings()
        if not cfg.get("username") or not self.store.has_credentials(cfg):
            raise ValueError("请先在 eLearning 设置中配置账号和登录凭据")
        return cfg

    # ----- settings ----------------------------------------------------
    def get_settings(self):
        return self.store.public_settings()

    def save_settings(self, payload):
        if isinstance(payload, dict) and ("file_sync_enabled" in payload or "file_sync_root" in payload):
            raise ValueError("课件保存授权请使用 save_file_sync_settings 管理")
        return self.store.save_settings(payload)

    def delete_settings(self):
        self.store.delete_settings()
        return self.store.public_settings()

    def save_file_sync_settings(self, enabled, root):
        return self.store.save_file_sync_settings(enabled, root)

    def get_cursors(self):
        return self.store.get_cursors()

    def set_cursors(self, cursors):
        return self.store.set_cursors(cursors)

    def drain_audit_events(self):
        return self.store.drain_audit()

    # ----- discovery ---------------------------------------------------
    def list_courses(self):
        cfg = self._credentialed_settings()
        rows = course_list(self._client(cfg))
        self._check_cancelled()
        return [{"id": str(row["id"]), "name": row.get("name", str(row["id"]))} for row in rows]

    def test_connection(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("eLearning 设置必须是对象")
        # Discovering courses is independent of the later file-save grant.
        cfg = self.store.resolve_settings({**payload, "file_sync_enabled": False, "file_sync_root": ""})
        client = self._client(cfg)
        options = [{"id": str(row["id"]), "name": row.get("name") if isinstance(row.get("name"), str) else ""}
                   for row in course_list(client)]
        self.store.save_course_options(cfg, options)
        return options

    # ----- reading -----------------------------------------------------
    @staticmethod
    def _page(params, maximum=50):
        offset, limit = params.get("offset", 0), params.get("limit", 20)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset 必须是非负整数")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
            raise ValueError(f"limit 必须为 1 至 {maximum} 的整数")
        return offset, limit

    @staticmethod
    def _extensions(params):
        values = params.get("file_extensions") or []
        if not isinstance(values, list) or len(values) > 20 or any(
            not isinstance(value, str) or not re.fullmatch(r"\.?[A-Za-z0-9]{1,12}", value)
            for value in values
        ):
            raise ValueError("file_extensions 必须是扩展名列表，例如 pdf、ppt、pptx")
        return {value.lstrip(".").lower() for value in values}

    def fetch(self, since=None, until=None, course_ids=None, offset=0, limit=20):
        """Windowed, paged read of course resources (Agent / UI read purpose)."""
        cfg = self._credentialed_settings()
        offset, limit = self._page({"offset": offset, "limit": limit})
        now = self.clock()
        start = (now - timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
        end = now
        if since is not None:
            start = parse_date(since)
        if until is not None:
            end = parse_date(until)
        if not start or not end or start >= end:
            raise ValueError("请提供有效的 since/until 时间窗口，起点须早于终点")
        selected = course_ids if course_ids is not None else (cfg.get("courses") or [])
        if not isinstance(selected, list) or any(not isinstance(value, str) or not value.strip() for value in selected):
            raise ValueError("course_ids 必须是课程 ID 列表")
        window = {"start": start.astimezone(timezone.utc).isoformat(),
                  "end": end.astimezone(timezone.utc).isoformat()}
        client_factory = self._client
        if course_ids is not None or not selected:
            client = self._client(cfg)
            courses = course_list(client)
            self._check_cancelled()
            selected = ([str(course["id"]) for course in select_courses(courses, selected)]
                        if selected else [str(course["id"]) for course in courses])

            def client_factory(_account):
                return client
        if not selected:
            return {"source_items": [], "total": 0, "next_offset": None, "window": window,
                    "status": "completed", "errors": []}
        source = ElearningSource({**cfg, "courses": selected}, self.store, client_factory=client_factory,
                                 cancel_event=self.cancel_event)
        fetched = source.fetch({"since": window["start"], "until": window["end"]})
        rows = sorted((item for item in fetched.items if start < parse_date(item.occurred_at) <= end),
                      key=lambda item: (item.occurred_at, item.source_id))
        page = rows[offset:offset + limit]
        return {"source_items": [asdict(item) for item in page], "total": len(rows),
                "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
                "window": window, "status": "partial" if fetched.errors else "completed",
                "errors": fetched.errors}

    def fetch_source(self, cursors=None, since=None, until=None):
        """Briefing/background fetch. Returns items plus *proposed* cursors.

        Cursors are never advanced here; the caller commits them with
        ``set_cursors`` only after the items were consumed successfully.
        """
        cfg = self.store.load_settings()
        if not cfg["enabled"]:
            raise ValueError("eLearning 来源未启用")
        source = ElearningSource(cfg, self.store, client_factory=self.client_factory,
                                 cancel_event=self.cancel_event, briefing_only=True)
        merged = dict(self.store.get_cursors(cfg) if cursors is None else cursors)
        if since is not None:
            merged["since"] = since
        if until is not None:
            merged["until"] = until
        result = source.fetch(merged)
        return {"source": source.name, "account_id": source.account_id,
                "display_name": source.display_name,
                "items": [item.to_catalog_payload() for item in result.items],
                "cursors": dict(result.cursors), "errors": list(result.errors)}

    # ----- files -------------------------------------------------------
    def _file_rows(self, cfg, params, *, authorized):
        for key in ("course_ids", "file_ids"):
            values = params.get(key) or []
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{key} 必须是文件或课程 ID 列表")
        requested_courses = set(params.get("course_ids") or [])
        requested_files = set(params.get("file_ids") or [])
        extensions = self._extensions(params)
        client = self._client(cfg)
        available = course_list(client)
        self._check_cancelled()
        selectors = cfg.get("courses") or []
        courses = select_courses(available, selectors) if selectors else available
        selected_ids = {str(course["id"]) for course in courses}
        if authorized and requested_courses - selected_ids:
            raise ValueError("只能同步 eLearning 设置中已授权保存文件的课程")
        if not authorized and requested_courses:
            courses = select_courses(available, list(requested_courses))
        rows, errors = [], []
        for course in courses:
            self._check_cancelled()
            if authorized and requested_courses and str(course["id"]) not in requested_courses:
                continue
            try:
                files, warnings = list_files(client, course["id"])
                self._check_cancelled()
                errors.extend(f"{course['name']}：{warning}" for warning in warnings)
                rows.extend((course, raw) for raw in files
                            if not raw.get("hidden_for_user")
                            and (not requested_files or str(raw.get("id")) in requested_files)
                            and (not extensions or os.path.splitext(str(raw.get("filename") or raw.get("display_name") or ""))[1].lstrip(".").lower() in extensions))
            except (LoginRequired, SyncCancelled):
                raise
            except SyncError as exc:
                errors.append(f"{course['name']} / files：{exc}")
        rows.sort(key=lambda pair: (str(pair[0]["id"]), str(pair[1]["id"])))
        missing = requested_files - {str(raw["id"]) for _, raw in rows}
        if missing:
            errors.append("以下课程文件未在筛选结果中找到：" + "、".join(sorted(missing)))
        return client, rows, errors

    def list_files(self, course_ids=None, file_ids=None, file_extensions=None, offset=0, limit=20):
        cfg = self._credentialed_settings()
        params = {"course_ids": course_ids, "file_ids": file_ids, "file_extensions": file_extensions}
        offset, limit = self._page({"offset": offset, "limit": limit}, maximum=200)
        _, rows, errors = self._file_rows(cfg, params, authorized=False)
        page = rows[offset:offset + limit]
        return {"status": "partial" if errors else "completed", "total": len(rows),
                "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
                "files": [{"course_id": str(course["id"]), "course_name": course.get("name", ""),
                           "file_id": str(raw["id"]), "filename": raw.get("filename") or raw.get("display_name") or "",
                           "size": raw.get("size"), "updated_at": raw.get("updated_at") or raw.get("modified_at"),
                           "page_url": f"{cfg['base_url'].rstrip('/')}/courses/{course['id']}/files/{raw['id']}"}
                          for course, raw in page], "errors": errors}

    def sync_files(self, course_ids=None, file_ids=None, file_extensions=None, layout="managed",
                   offset=0, limit=20):
        cfg = self._credentialed_settings()
        if not cfg.get("file_sync_enabled") or not cfg.get("file_sync_root"):
            raise ValueError("请先在 Agent 设置中开启课件保存，并选择保存目录")
        if not cfg.get("courses"):
            raise ValueError("请先在 eLearning 设置中选择允许保存文件的课程")
        if layout not in ("managed", "courseware"):
            raise ValueError("layout 必须是 managed 或 courseware")
        offset, limit = self._page({"offset": offset, "limit": limit})
        params = {"course_ids": course_ids, "file_ids": file_ids, "file_extensions": file_extensions}
        client, rows, errors = self._file_rows(cfg, params, authorized=True)
        page = rows[offset:offset + limit]
        self._check_cancelled()
        errors.extend(_sync_files(client, cfg, page, self.store, cancel_event=self.cancel_event, layout=layout))
        return {"status": "partial" if errors else "completed", "total": len(rows),
                "processed": len(page),
                "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
                "save_root": cfg["file_sync_root"], "errors": errors}
