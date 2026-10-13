"""Course selection adapted from elearning_crawler/src/service.py."""
import re
from .errors import LoginRequired, SyncCancelled, SyncError
from .utils import parse_date

def course_list(client):
    return client.list("/api/v1/courses", {"enrollment_type": "student", "enrollment_state": "active", "include[]": "term"})


def select_courses(courses, selectors):
    if not selectors:
        raise SyncError("尚未选择课程，请在 eLearning 设置中选择课程。")
    selected = {}
    for selector in selectors:
        query = str(selector).strip()
        match_id = re.search(r"/courses/(\d+)", query)
        if match_id:
            query = match_id.group(1)
        matches = [c for c in courses if str(c.get("id")) == query] if query.isdigit() else [
            c for c in courses if query.casefold() in c.get("name", "").casefold()]
        if len(matches) != 1:
            details = "；".join("{}（ID {}）".format(c.get("name"), c.get("id")) for c in matches)
            raise SyncError("课程“{}”{}。{} 请在 eLearning 设置中刷新课程列表并重新选择课程。".format(
                query, "未找到" if not matches else "匹配多个结果", details))
        selected[str(matches[0]["id"])] = matches[0]
    return list(selected.values())



def list_files(client, cid):
    try:
        return client.list("/api/v1/courses/{}/files".format(cid)), []
    except (LoginRequired, SyncCancelled):
        raise
    except SyncError as error:
        original = str(error)
    # Some courses disable the Files tab but expose files in modules.
    files, errors = {}, ["文件列表读取失败（{}），尝试从单元补充。此轮文件扫描可能不完整。".format(original)]
    for module in client.list("/api/v1/courses/{}/modules".format(cid)):
        for item in client.list("/api/v1/courses/{}/modules/{}/items".format(cid, module["id"])):
            if item.get("type") == "File" and item.get("content_id"):
                fid = item["content_id"]
                if fid in files:
                    continue
                try:
                    files[fid] = client.get("/api/v1/files/{}".format(fid))[0]
                except (LoginRequired, SyncCancelled):
                    raise
                except SyncError as error:
                    errors.append("单元文件 {}：{}".format(fid, error))
    return list(files.values()), errors


def list_recent_files(client, cid, since):
    """Read recent file metadata; Canvas sorts file pages by update time."""
    if since is None:
        return list_files(client, cid)
    path = "/api/v1/courses/{}/files".format(cid)
    params = {"sort": "updated_at", "order": "desc", "per_page": 100}
    seen, files = set(), []
    try:
        while path:
            if path in seen:
                raise SyncError("接口分页循环，已停止以防重复请求。")
            seen.add(path)
            page, path = client.get(path, params)
            params = None
            if not isinstance(page, list):
                raise SyncError("接口未返回文件列表。")
            reached_older = False
            for raw in page:
                updated = parse_date(raw.get("updated_at") or raw.get("modified_at") or raw.get("created_at"))
                if updated is not None and updated <= since:
                    reached_older = True
                else:
                    files.append(raw)
            if reached_older:
                break
    except (LoginRequired, SyncCancelled):
        raise
    except SyncError as exc:
        if files:
            return files, ["文件元数据读取不完整：{}".format(exc)]
        return list_files(client, cid)
    return files, []
