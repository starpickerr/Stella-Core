"""Resource documents adapted from elearning_crawler/src/resources.py and service.py."""
import datetime as dt
import urllib.parse

from .models import Resource
from .utils import SHANGHAI, display_date, extract, md, parse_date


def value_text(value, fallback="未提供"):
    return fallback if value is None or value == "" else str(value)


def document(title, course, fields, html=None, page=""):
    lines = ["# " + md(title), "", "- 课程：" + md(course["name"])]
    lines.extend("- {}：{}".format(label, md(value)) for label, value in fields)
    if html is not None:
        text, links = extract(html)
        lines += ["", "## 内容", "", text or "网站未提供文字内容，请打开原页面查看。"]
        links = dict.fromkeys(urllib.parse.urljoin(page, link) for link in links)
        for link in links:
            if urllib.parse.urlparse(link).scheme in ("http", "https"):
                lines.append("\n[附件或参考链接]({})".format(link.replace(" ", "%20")))
    if page:
        lines += ["", "[打开网站页面]({})".format(page)]
    return "\n".join(lines) + "\n"


def announcement(canvas, course, item):
    title = item.get("title") or "未命名公告"
    page = item.get("html_url") or "{}/courses/{}/discussion_topics/{}".format(canvas.base, course["id"], item["id"])
    posted = display_date(item.get("posted_at") or item.get("created_at"))
    author = (item.get("author") or {}).get("display_name") or "未提供"
    fields = [("发布时间", posted), ("发布者", author)]
    return Resource(course, str(item["id"]), title, "发布 " + posted,
                    document(title, course, fields, item.get("message") or "", page), page,
                    item.get("posted_at") or item.get("created_at") or "")


def quiz_status(item):
    now = dt.datetime.now(SHANGHAI)
    unlock, lock = parse_date(item.get("unlock_at")), parse_date(item.get("lock_at"))
    if unlock and now < unlock:
        return "尚未开放"
    if lock and now >= lock:
        return "已关闭"
    if item.get("locked_for_user"):
        return "当前受限"
    return "请在网站确认可参加状态"


def quiz(canvas, course, item, from_assignment=False):
    title = item.get("title") or item.get("name") or "未命名测试"
    section = "assignments" if from_assignment else "quizzes"
    page = item.get("html_url") or "{}/courses/{}/{}/{}".format(canvas.base, course["id"], section, item["id"])
    status, due = quiz_status(item), display_date(item.get("due_at"))
    limit = item.get("time_limit")
    attempts = item.get("allowed_attempts")
    fields = [("状态", status), ("截止时间", due), ("开放时间", display_date(item.get("unlock_at"))),
              ("关闭时间", display_date(item.get("lock_at"))), ("满分", value_text(item.get("points_possible"))),
              ("题目数", value_text(item.get("question_count"))),
              ("限时", "不限时" if limit == 0 else str(limit) + " 分钟" if limit is not None else "未提供"),
              ("允许次数", "不限次数" if attempts == -1 else value_text(attempts))]
    if item.get("lock_explanation"):
        fields.append(("限制说明", extract(item["lock_explanation"])[0]))
    return Resource(course, section + "-" + str(item["id"]), title, "截止 {} · {}".format(due, status),
                    document(title, course, fields, item.get("description") or "", page), page)


def grade(canvas, course, item):
    submission = item.get("submission") or {}
    title = item.get("name") or "未命名作业"
    hidden = item.get("muted") or ("posted_at" in submission and not submission["posted_at"])
    state = submission.get("workflow_state")
    if submission.get("excused"):
        status = "免交"
    elif hidden and state == "graded":
        status = "评分尚未公布"
    elif state == "graded" or (submission.get("score") is not None and not hidden):
        status = "已评分"
    elif state in ("submitted", "pending_review") or submission.get("submitted_at"):
        status = "已提交，待评分"
    elif state == "unsubmitted":
        status = "未提交"
    else:
        status = "评分状态未提供"
    score = "未公布" if hidden else value_text(submission.get("score"), "未公布")
    grade_text = "未公布" if hidden else value_text(submission.get("grade"), "未公布")
    possible = value_text(item.get("points_possible"))
    fields = [("状态", status), ("得分 / 满分", score + " / " + possible), ("等级或评分", grade_text),
              ("提交时间", display_date(submission.get("submitted_at"))),
              ("评分时间", display_date(submission.get("graded_at"))), ("截止时间", display_date(item.get("due_at")))]
    for comment in submission.get("submission_comments") or []:
        fields.append(("评语（{}）".format(comment.get("author_name") or "教师"), comment.get("comment") or ""))
    page = "{}/courses/{}/grades#assignment_{}".format(canvas.base, course["id"], item["id"])
    return Resource(course, "assignment-" + str(item["id"]), title,
                    "{} / {} · {}".format(score, possible, status), document(title, course, fields, page=page), page)


def course_grade(canvas, course, enrollment):
    grades = enrollment.get("grades") or {}
    current = value_text(grades.get("current_score"), "未公布")
    final = value_text(grades.get("final_score"), "未公布")
    fields = [("当前成绩（网站百分制）", current), ("最终成绩（网站百分制）", final),
              ("当前等级", value_text(grades.get("current_grade"), "未公布")),
              ("最终等级", value_text(grades.get("final_grade"), "未公布")),
              ("说明", "成绩直接采用网站结果；最终成绩的计算可能包含尚未完成的任务，以教师公布为准。")]
    page = "{}/courses/{}/grades".format(canvas.base, course["id"])
    title = "课程成绩汇总"
    return Resource(course, "enrollment-" + str(enrollment["id"]), title, "当前 {} · 最终 {}".format(current, final),
                    document(title, course, fields, page=page), page)



def assignment_status(assignment, now):
    submission = assignment.get("submission")
    if not isinstance(submission, dict):
        return "提交状态未提供，需确认", False
    if submission.get("workflow_state") == "graded":
        return "已评分", True
    if submission.get("workflow_state") in ("submitted", "pending_review") or submission.get("submitted_at"):
        return "已提交", True
    due = parse_date(assignment.get("due_at"))
    return ("已过截止时间，待确认" if due and due < now else "待完成"), False


def assignment_document(client, course, assignment, now=None):
    now = now or dt.datetime.now(SHANGHAI)
    status, submitted = assignment_status(assignment, now)
    content, links = extract(assignment.get("description"))
    page = assignment.get("html_url") or "{}/courses/{}/assignments/{}".format(client.base, course["id"], assignment["id"])
    submission_types = {"online_upload": "上传文件", "online_text_entry": "在线文本", "online_url": "提交网址",
                        "on_paper": "线下提交", "none": "无需在线提交", "external_tool": "外部工具",
                        "online_quiz": "在线测验", "discussion_topic": "讨论", "media_recording": "音视频"}
    methods = "、".join(submission_types.get(x, x) for x in assignment.get("submission_types", [])) or "未提供"
    lines = ["# " + md(assignment.get("name", "未命名作业")), "", "- 课程：" + md(course["name"]),
             "- 截止时间（北京时间）：" + display_date(assignment.get("due_at")),
             "- 开放时间：" + display_date(assignment.get("unlock_at")),
             "- 关闭时间：" + display_date(assignment.get("lock_at")), "- 状态：" + status,
             "- 提交方式：" + methods, "- 文件格式：" + ", ".join(assignment.get("allowed_extensions") or ["未限定/未提供"]),
             "- [查看原始任务](" + page + ")", "", "## 要求原文", "", content or "网站没有提供文字说明，请打开原始任务查看附件或外部工具。"]
    if assignment.get("locked_for_user"):
        lines += ["", "当前任务受限：" + extract(assignment.get("lock_explanation"))[0]]
    if links:
        lines += ["", "## 附件和参考链接", ""]
        for url in links:
            full = urllib.parse.urljoin(page, url)
            if urllib.parse.urlparse(full).scheme in ("http", "https"):
                lines.append("- [打开链接]({})".format(full.replace(" ", "%20")))
    return {"course": course["name"], "name": assignment.get("name", "作业"), "due_at": assignment.get("due_at"),
            "status": status, "submitted": submitted, "text": "\n".join(lines) + "\n",
            "excerpt": content[:360], "methods": methods}
