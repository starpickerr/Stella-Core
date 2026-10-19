"""Normalize the crawler's Canvas resources into briefing source_items."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import logging

from .client import ensure_login
from .courses import course_list, select_courses, list_files, list_recent_files
from .documents import announcement, assignment_document, quiz, grade, course_grade
from .errors import LoginRequired, SyncCancelled, SyncError
from .models import FetchResult, FetchedItem
from .store import account_id
from .utils import parse_date

logger = logging.getLogger("stella.elearning.source")


class ElearningSource:
    name = "elearning"

    def __init__(self, config, store, client_factory=None, cancel_event=None,
                 on_items_ready=None, briefing_only=False):
        self.config = dict(config)
        self.store = store
        self.account_id = account_id(config)
        self.display_name = "eLearning · " + config["username"]
        self.client_factory = client_factory
        # File downloads are exclusively initiated by sync_files.
        self.cancel_event = cancel_event
        self.on_items_ready = on_items_ready
        self.briefing_only = briefing_only

    def _check_cancelled(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise SyncCancelled("eLearning 读取已取消")

    def fetch(self, cursors):
        self._check_cancelled()
        if not self.config["courses"]:
            raise SyncError("尚未选择课程，请在 eLearning 设置中选择课程。")
        client = (self.client_factory(self.config) if self.client_factory is not None
                  else ensure_login(self.config, self.store, cancel_event=self.cancel_event))
        courses = select_courses(course_list(client), self.config["courses"])
        self._check_cancelled()
        profile, _ = client.get("/api/v1/users/self/profile")
        self._check_cancelled()
        old = json.loads(cursors.get("elearning_state") or "{}")
        state = dict(old)
        start, end = parse_date(cursors.get("since")), parse_date(cursors.get("until"))
        observed = end or datetime.now(timezone.utc)
        items, errors, quiz_not_found = [], [], []
        assignments_by_course = {}
        reads = 0

        def add(course, kind, raw, title, body, url, sender="", actionable=False):
            self._check_cancelled()
            key = "{}:{}:{}".format(course["id"], kind, raw["id"])
            fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            previous = old.get(key, {})
            timestamps = [parse_date(raw.get(field)) for field in ("updated_at", "modified_at", "posted_at", "created_at")]
            submission = raw.get("submission") or {}
            timestamps += [parse_date(submission.get(field)) for field in ("graded_at", "submitted_at", "posted_at")]
            occurred = max((value for value in timestamps if value), default=None)
            if previous.get("fingerprint") == fingerprint:
                occurred = parse_date(previous.get("occurred_at")) or occurred
            elif not occurred or (previous and start and occurred <= start) or (not previous and actionable and start and occurred <= start):
                # A changed resource without a useful server timestamp, or an
                # outstanding task discovered on first connection, is observed
                # now. due_at is a deadline, never the event timestamp.
                occurred = observed
            state[key] = {"fingerprint": fingerprint, "occurred_at": occurred.isoformat()}
            # Keep records arriving during the fetch (and future-dated records)
            # in the catalog. The pipeline applies the final (start, end]
            # window after fetching, just as it does for IMAP.
            if start and occurred <= start:
                return
            items.append(FetchedItem(source=self.name, account_id=self.account_id, source_id=key, thread_id=key,
                sender=sender or course["name"], title=course["name"] + " · " + title,
                snippet=body[:1000], occurred_at=occurred.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                url=url, payload={"body": body, "resource_type": kind, "course_id": str(course["id"]),
                                  "course_name": course["name"], "due_at": raw.get("due_at"), "fingerprint": fingerprint,
                                  "entity_id": "{}:assignment:{}".format(course["id"], raw["id"]) if kind in {"assignment", "grade"} else key,
                                  "submission_status": submission.get("workflow_state"), "score": submission.get("score"),
                                  "grade": submission.get("grade")}))

        def read(course, resource, params=None):
            nonlocal reads
            self._check_cancelled()
            try:
                rows = client.list("/api/v1/courses/{}/{}".format(course["id"], resource), params)
                reads += 1
                return [row for row in rows if row.get("published") is not False and not row.get("hidden_for_user")]
            except (LoginRequired, SyncCancelled):
                raise
            except SyncError as exc:
                if resource == "quizzes" and str(exc) == "网站返回 HTTP 404。":
                    quiz_not_found.append(course["name"])
                    return []
                errors.append("{} / {}：{}".format(course["name"], resource, exc))
                return []

        def files(course):
            nonlocal reads
            self._check_cancelled()
            try:
                rows, warnings = (list_recent_files(client, course["id"], start) if self.briefing_only
                                  else list_files(client, course["id"]))
                reads += 1
                errors.extend("{}：{}".format(course["name"], warning) for warning in warnings)
                return [row for row in rows if not row.get("hidden_for_user")]
            except (LoginRequired, SyncCancelled):
                raise
            except SyncError as exc:
                errors.append("{} / files：{}".format(course["name"], exc))
                return []

        # Assignments are the small actionable set. A listener can see them
        # before the larger announcement and file catalogs finish.
        for course in courses:
            self._check_cancelled()
            assignments = read(course, "assignments", {"include[]": ["submission", "submission_comments"]})
            assignments_by_course[str(course["id"])] = assignments
            for raw in assignments:
                self._check_cancelled()
                page = raw.get("html_url") or "{}/courses/{}/assignments/{}".format(client.base, course["id"], raw["id"])
                if raw.get("is_quiz_assignment") or raw.get("quiz_id"):
                    document = quiz(client, course, raw, from_assignment=True)
                    add(course, "assignment", raw, document.title, document.text, page, actionable=True)
                else:
                    document = assignment_document(client, course, raw, observed)
                    add(course, "assignment", raw, raw.get("name") or "作业", document["text"], page,
                        actionable=not document["submitted"])
                if raw.get("submission") and ((raw["submission"].get("graded_at")) or raw["submission"].get("submission_comments")):
                    document = grade(client, course, raw)
                    add(course, "grade", raw, document.title + " · 评分", document.text, document.url)
            logger.info("[eLearning] assignments read course=%s count=%d", course["id"], len(assignments))
            if self.on_items_ready is not None:
                self.on_items_ready(list(items))

        for course in courses:
            self._check_cancelled()
            for raw in read(course, "discussion_topics", {"only_announcements": "true"}):
                self._check_cancelled()
                document = announcement(client, course, raw)
                add(course, "announcement", raw, document.title, document.text, document.url,
                    (raw.get("author") or {}).get("display_name", ""))
            assignments = assignments_by_course[str(course["id"])]
            known_quizzes = {str(row["quiz_id"]) for row in assignments if row.get("quiz_id")}
            known_quiz_assignments = {str(row["id"]) for row in assignments if row.get("is_quiz_assignment") or row.get("quiz_id")}
            for raw in read(course, "quizzes"):
                self._check_cancelled()
                if str(raw["id"]) in known_quizzes or str(raw.get("assignment_id")) in known_quiz_assignments:
                    continue
                document = quiz(client, course, raw)
                add(course, "quiz", raw, document.title, document.text, document.url, actionable=True)
            for raw in files(course):
                self._check_cancelled()
                title = raw.get("display_name") or raw.get("filename") or "课程文件"
                page = "{}/courses/{}/files/{}".format(client.base, course["id"], raw["id"])
                body = "课程：{}\n文件：{}\n大小：{} 字节\n更新时间：{}\n原页面：{}".format(
                    course["name"], title, raw.get("size", "未提供"), raw.get("updated_at") or raw.get("modified_at") or "未提供", page)
                add(course, "file", raw, title, body, page)
            for raw in read(course, "enrollments", {"user_id": str(profile["id"]), "type[]": "StudentEnrollment"}):
                self._check_cancelled()
                document = course_grade(client, course, raw)
                add(course, "course_grade", raw, document.title, document.text, document.url)
            logger.info("[eLearning] metadata read course=%s candidates=%d", course["id"], len(items))
            if self.on_items_ready is not None:
                self.on_items_ready(list(items))
        if quiz_not_found:
            # Some courses do not expose a standalone quizzes endpoint. The
            # assignments endpoint can still contain quiz assignments, and
            # all other successful reads are usable for this briefing.
            logger.info("[eLearning] quizzes endpoint unavailable for %s courses", len(quiz_not_found))
        if not reads and errors:
            raise SyncError("；".join(errors))
        # Partial reads do not advance source state, so inaccessible resources
        # remain eligible when permissions/network recover.
        return FetchResult(items, {} if errors else {"elearning_state": json.dumps(state, ensure_ascii=False)}, errors)
