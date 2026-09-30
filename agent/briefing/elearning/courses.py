"""Course selection adapted from elearning_crawler/src/service.py."""
import re
from .errors import LoginRequired, SyncError

def course_list(client):
    return client.list("/api/v1/courses", {"enrollment_type": "student", "enrollment_state": "active", "include[]": "term"})


def select_courses(courses, selectors):
    if not selectors:
        raise SyncError("尚未选择课程，请在简报设置中测试连接并勾选课程。")
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
            raise SyncError("课程“{}”{}。{} 请在简报设置中测试连接并重新选择课程。".format(
                query, "未找到" if not matches else "匹配多个结果", details))
        selected[str(matches[0]["id"])] = matches[0]
    return list(selected.values())



def list_files(client, cid):
    try:
        return client.list("/api/v1/courses/{}/files".format(cid)), []
    except LoginRequired:
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
                except LoginRequired:
                    raise
                except SyncError as error:
                    errors.append("单元文件 {}：{}".format(fid, error))
    return list(files.values()), errors
