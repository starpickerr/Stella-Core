# -*- coding=utf-8 -*-
"""
WeCom Customer Service (微信客服) channel for CoW.

Differences from `channel/wechatcom/` (企微自建应用):
    1. Audience: external WeChat users (not internal members).
    2. Receiver fields: `external_userid` + `open_kfid` instead of a single
       member `userid`.
    3. Inbound flow: callback only delivers an event token, the actual
       message bodies must be pulled via `cgi-bin/kf/sync_msg` with a
       persistent cursor. See `wechatcom_kf_cursor_store.py`.
    4. Outbound flow: messages are sent via `cgi-bin/kf/send_msg` (each
       request must specify both `touser` and `open_kfid`); wechatpy has
       no native helper, so we call the HTTP endpoint directly.
"""
import io
import json
import os
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests
import web
from wechatpy.enterprise import WeChatClient
from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.enterprise.exceptions import InvalidCorpIdException
from wechatpy.exceptions import InvalidSignatureException, WeChatClientException

from bridge.context import Context
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.wechatcom_kf.wechatcom_kf_cursor_store import CursorStore
from channel.wechatcom_kf.wechatcom_kf_message import WechatComKfMessage
from common.log import logger
from common.singleton import singleton
from common.utils import (
    compress_imgfile,
    fsize,
    remove_markdown_symbol,
    split_string_by_utf8_length,
)
from config import conf

try:
    from voice.audio_convert import any_to_amr, split_audio
except ImportError as e:  # voice features optional
    logger.debug(
        "[wechatcom_kf] import voice.audio_convert failed, voice will be disabled: {}".format(e)
    )

MAX_UTF8_LEN = 2048
KF_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin/kf"
SYNC_MSG_LIMIT = 1000


@singleton
class WechatComKfChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()
        self.corp_id = conf().get("wechatcom_corp_id")
        self.secret = conf().get("wechatcom_kf_secret")
        self.token = conf().get("wechatcom_kf_token")
        self.aes_key = conf().get("wechatcom_kf_aes_key")
        self._http_server = None
        logger.info(
            "[wechatcom_kf] Initializing WeCom customer-service channel, corp_id: {}".format(
                self.corp_id
            )
        )
        self.crypto = WeChatCrypto(self.token, self.aes_key, self.corp_id)
        # Use the stock wechatpy WeChatClient so that the access_token is
        # cached and only refreshed when actually expired (~2h). The local
        # `WechatComAppClient` subclass has a broken background refresh
        # loop that re-fetches every 60s and a `fetch_access_token()`
        # override that may return a dict instead of a string, which
        # corrupts URLs and triggers errcode 40014.
        self.client = WeChatClient(self.corp_id, self.secret)

        cursor_dir = conf().get("wechatcom_kf_cursor_dir", "tmp")
        cursor_path = os.path.join(cursor_dir, "wechatcom_kf_cursors.json")
        self.cursor_store = CursorStore(cursor_path)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def startup(self):
        urls = ("/wxkf/?", "channel.wechatcom_kf.wechatcom_kf_channel.Query")
        app = web.application(urls, globals(), autoreload=False)
        port = conf().get("wechatcom_kf_port", 9888)
        logger.info("[wechatcom_kf] WeCom customer-service channel started")
        logger.info("[wechatcom_kf] Listening on http://0.0.0.0:{}/wxkf/".format(port))
        func = web.httpserver.StaticMiddleware(app.wsgifunc())
        func = web.httpserver.LogMiddleware(func)
        server = web.httpserver.WSGIServer(("0.0.0.0", port), func)
        self._http_server = server
        try:
            server.start()
        except (KeyboardInterrupt, SystemExit):
            server.stop()

    def stop(self):
        if self._http_server:
            try:
                self._http_server.stop()
                logger.info("[wechatcom_kf] HTTP server stopped")
            except Exception as e:
                logger.warning(f"[wechatcom_kf] Error stopping HTTP server: {e}")
            self._http_server = None

    # ------------------------------------------------------------------
    # Outbound — implementing the abstract `send` contract
    # ------------------------------------------------------------------
    def send(self, reply: Reply, context: Context):
        receiver = context["receiver"]
        msg = context.kwargs.get("msg")
        external_userid = context.get("external_userid") or (msg.external_userid if msg else None)
        open_kfid = context.get("open_kfid") or (msg.open_kfid if msg else None)

        if not external_userid or not open_kfid:
            logger.error(
                "[wechatcom_kf] missing external_userid or open_kfid, cannot send: "
                f"external_userid={external_userid}, open_kfid={open_kfid}"
            )
            return

        if reply.type in [ReplyType.TEXT, ReplyType.ERROR, ReplyType.INFO]:
            reply_text = remove_markdown_symbol(reply.content)
            texts = split_string_by_utf8_length(reply_text, MAX_UTF8_LEN)
            if len(texts) > 1:
                logger.info(
                    "[wechatcom_kf] text too long, split into {} parts".format(len(texts))
                )
            for i, text in enumerate(texts):
                self._send_text(external_userid, open_kfid, text)
                if i != len(texts) - 1:
                    time.sleep(0.5)
            logger.info("[wechatcom_kf] Do send text to {}: {}".format(receiver, reply_text))

        elif reply.type == ReplyType.VOICE:
            file_path = reply.content
            try:
                amr_file = os.path.splitext(file_path)[0] + ".amr"
                any_to_amr(file_path, amr_file)
                duration, files = split_audio(amr_file, 60 * 1000)
                if len(files) > 1:
                    logger.info(
                        "[wechatcom_kf] voice too long {}s > 60s, split into {} parts".format(
                            duration / 1000.0, len(files)
                        )
                    )
                media_ids = []
                for path in files:
                    with open(path, "rb") as f:
                        response = self.client.media.upload("voice", f)
                    logger.debug("[wechatcom_kf] upload voice response: {}".format(response))
                    media_ids.append(response["media_id"])
            except ImportError as e:
                logger.error("[wechatcom_kf] voice conversion failed: {}".format(e))
                logger.error("[wechatcom_kf] please install pydub: pip install pydub")
                return
            except WeChatClientException as e:
                logger.error("[wechatcom_kf] upload voice failed: {}".format(e))
                return

            try:
                os.remove(file_path)
                if amr_file != file_path:
                    os.remove(amr_file)
            except Exception:
                pass

            for media_id in media_ids:
                self._send_voice(external_userid, open_kfid, media_id)
                time.sleep(1)
            logger.info("[wechatcom_kf] sendVoice={}, receiver={}".format(reply.content, receiver))

        elif reply.type == ReplyType.IMAGE_URL:
            img_url = reply.content
            pic_res = requests.get(img_url, stream=True)
            image_storage = io.BytesIO()
            for block in pic_res.iter_content(1024):
                image_storage.write(block)
            sz = fsize(image_storage)
            if sz >= 10 * 1024 * 1024:
                logger.info("[wechatcom_kf] image too large, compressing, sz={}".format(sz))
                image_storage = compress_imgfile(image_storage, 10 * 1024 * 1024 - 1)
            image_storage.seek(0)
            try:
                response = self.client.media.upload("image", image_storage)
            except WeChatClientException as e:
                logger.error("[wechatcom_kf] upload image failed: {}".format(e))
                return
            self._send_image(external_userid, open_kfid, response["media_id"])
            logger.info("[wechatcom_kf] sendImage url={}, receiver={}".format(img_url, receiver))

        elif reply.type == ReplyType.IMAGE:
            image_storage = reply.content
            sz = fsize(image_storage)
            if sz >= 10 * 1024 * 1024:
                logger.info("[wechatcom_kf] image too large, compressing, sz={}".format(sz))
                image_storage = compress_imgfile(image_storage, 10 * 1024 * 1024 - 1)
            image_storage.seek(0)
            try:
                response = self.client.media.upload("image", image_storage)
            except WeChatClientException as e:
                logger.error("[wechatcom_kf] upload image failed: {}".format(e))
                return
            self._send_image(external_userid, open_kfid, response["media_id"])
            logger.info("[wechatcom_kf] sendImage, receiver={}".format(receiver))

        elif reply.type == ReplyType.VIDEO_URL:
            video_url = reply.content
            try:
                response = self.client.media.upload(
                    "video", requests.get(video_url, stream=True).content
                )
            except WeChatClientException as e:
                logger.error("[wechatcom_kf] upload video failed: {}".format(e))
                return
            self._send_video(external_userid, open_kfid, response["media_id"])
            logger.info("[wechatcom_kf] sendVideo url={}, receiver={}".format(video_url, receiver))

        elif reply.type == ReplyType.FILE:
            file_path = reply.content
            try:
                with open(file_path, "rb") as f:
                    response = self.client.media.upload(
                        "file", (os.path.basename(file_path), f.read())
                    )
            except WeChatClientException as e:
                logger.error("[wechatcom_kf] upload file failed: {}".format(e))
                return
            self._send_file(external_userid, open_kfid, response["media_id"])
            logger.info("[wechatcom_kf] sendFile={}, receiver={}".format(file_path, receiver))

        else:
            logger.warning("[wechatcom_kf] unsupported reply type: {}".format(reply.type))

    # ------------------------------------------------------------------
    # Inbound — pull messages by cursor
    # ------------------------------------------------------------------
    def consume_callback(self, token: str, open_kfid: str):
        """
        Called from the HTTP `Query.POST` handler whenever WeCom notifies
        us that there are new messages for `open_kfid`. Pulls all new
        messages via sync_msg and feeds them into `produce()`.
        """
        existing_cursor = self.cursor_store.get(open_kfid)

        # First-time bootstrap: always skip history, otherwise WeCom would
        # replay up to 14 days of messages on the very first callback and
        # flood every user with auto-replies.
        if not existing_cursor:
            self._initialize_cursor(token, open_kfid)
            return

        msgs = self._pull_messages(token, open_kfid, existing_cursor)
        if not msgs:
            return
        for raw in msgs:
            try:
                kf_msg = WechatComKfMessage(msg=raw, client=self.client)
            except NotImplementedError as e:
                logger.debug("[wechatcom_kf] {}".format(e))
                continue
            context = self._compose_context(
                kf_msg.ctype,
                kf_msg.content,
                isgroup=False,
                msg=kf_msg,
            )
            if context:
                self.produce(context)
            time.sleep(0.05)  # tiny gap between messages of the same batch

    def _initialize_cursor(self, token: str, open_kfid: str):
        """
        Drain all current messages for this `open_kfid` without producing
        any context, just to advance the cursor to "now". This prevents
        a fresh deployment from replying to up to ~14 days of history.
        """
        next_cursor = ""
        total_skipped = 0
        while True:
            data = self._call_sync_msg(token, open_kfid, next_cursor)
            if data is None:
                break
            msg_list = data.get("msg_list") or []
            total_skipped += len(msg_list)
            cursor_after = data.get("next_cursor") or ""
            if cursor_after:
                self.cursor_store.set(open_kfid, cursor_after)
            if not data.get("has_more"):
                break
            if not cursor_after or cursor_after == next_cursor:
                break
            next_cursor = cursor_after
        logger.info(
            "[wechatcom_kf] first-start bootstrap finished for open_kfid={}, "
            "skipped {} historical messages".format(open_kfid, total_skipped)
        )

    def _pull_messages(self, token: str, open_kfid: str, next_cursor: Optional[str]) -> list:
        """Loop sync_msg until `has_more` is false. Returns raw msg dicts."""
        collected = []
        cursor = next_cursor or ""
        while True:
            data = self._call_sync_msg(token, open_kfid, cursor)
            if data is None:
                break
            for item in data.get("msg_list") or []:
                # Only consume messages from external users; ignore replies
                # generated by our own kf account, otherwise we would loop
                # back into ourselves.
                if not item.get("external_userid"):
                    continue
                if item.get("msgtype") in ("text", "image", "voice"):
                    collected.append(item)
            cursor_after = data.get("next_cursor") or ""
            if cursor_after:
                self.cursor_store.set(open_kfid, cursor_after)
            if not data.get("has_more"):
                break
            if not cursor_after or cursor_after == cursor:
                break
            cursor = cursor_after

        if collected:
            collected = _dedup_image_text_pair(collected)
        logger.info(
            "[wechatcom_kf] pulled {} messages for open_kfid={}".format(len(collected), open_kfid)
        )
        return collected

    def _call_sync_msg(self, token: str, open_kfid: str, cursor: str) -> Optional[dict]:
        # `client.access_token` is the cached string property; do not use
        # `fetch_access_token()` here — wechatpy returns the raw response
        # dict from that call, which corrupts the query string.
        url = f"{KF_API_BASE}/sync_msg?access_token={self.client.access_token}"
        payload = {
            "token": token,
            "open_kfid": open_kfid,
            "limit": SYNC_MSG_LIMIT,
        }
        if cursor:
            payload["cursor"] = cursor
        try:
            resp = requests.post(url, json=payload, timeout=10).json()
        except Exception as e:
            logger.error(f"[wechatcom_kf] sync_msg request failed: {e}")
            return None

        if resp.get("errcode") != 0:
            logger.error(
                f"[wechatcom_kf] sync_msg errcode={resp.get('errcode')}, "
                f"errmsg={resp.get('errmsg')}, open_kfid={open_kfid}"
            )
            return None
        return resp

    # ------------------------------------------------------------------
    # Outbound HTTP wrappers (kf/send_msg)
    # ------------------------------------------------------------------
    def _post_send_msg(self, payload: dict) -> dict:
        url = f"{KF_API_BASE}/send_msg?access_token={self.client.access_token}"
        try:
            resp = requests.post(url, json=payload, timeout=10).json()
        except Exception as e:
            logger.error(f"[wechatcom_kf] send_msg request failed: {e}")
            return {"errcode": -1, "errmsg": str(e)}
        if resp.get("errcode") != 0:
            logger.error(f"[wechatcom_kf] send_msg failed, payload={payload}, resp={resp}")
        return resp

    def _send_text(self, external_userid: str, open_kfid: str, content: str) -> dict:
        return self._post_send_msg({
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgtype": "text",
            "text": {"content": content},
        })

    def _send_image(self, external_userid: str, open_kfid: str, media_id: str) -> dict:
        return self._post_send_msg({
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgtype": "image",
            "image": {"media_id": media_id},
        })

    def _send_voice(self, external_userid: str, open_kfid: str, media_id: str) -> dict:
        return self._post_send_msg({
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgtype": "voice",
            "voice": {"media_id": media_id},
        })

    def _send_video(self, external_userid: str, open_kfid: str, media_id: str) -> dict:
        return self._post_send_msg({
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgtype": "video",
            "video": {"media_id": media_id},
        })

    def _send_file(self, external_userid: str, open_kfid: str, media_id: str) -> dict:
        return self._post_send_msg({
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgtype": "file",
            "file": {"media_id": media_id},
        })

    def _send_link(self, external_userid: str, open_kfid: str, link_data: dict) -> dict:
        return self._post_send_msg({
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgtype": "link",
            "link": link_data,
        })


def _dedup_image_text_pair(messages: list) -> list:
    """
    A WeChat user often sends an image immediately followed by a text
    question (e.g. "what's in this picture?"). When that happens we
    treat them as one combined turn: image first, then text.
    Otherwise (single message or unrelated batch) we return only the
    last message to avoid replying to stale history.
    """
    if not messages:
        return []

    text_messages = [m for m in messages if m["msgtype"] == "text"]
    image_messages = [m for m in messages if m["msgtype"] == "image"]
    if text_messages and image_messages:
        last_text_time = text_messages[-1]["send_time"]
        first_image_time = image_messages[0]["send_time"]
        if abs(last_text_time - first_image_time) <= 5:
            return [image_messages[0], text_messages[-1]]
    return [messages[-1]]


# ----------------------------------------------------------------------
# HTTP handlers (web.py)
# ----------------------------------------------------------------------
class Query:
    def GET(self):
        channel = WechatComKfChannel()
        params = web.input()
        logger.info("[wechatcom_kf] verify params: {}".format(params))
        try:
            signature = params.msg_signature
            timestamp = params.timestamp
            nonce = params.nonce
            echostr = params.echostr
            echostr = channel.crypto.check_signature(signature, timestamp, nonce, echostr)
        except (InvalidSignatureException, InvalidCorpIdException):
            raise web.Forbidden()
        return echostr

    def POST(self):
        channel = WechatComKfChannel()
        params = web.input()
        try:
            signature = params.msg_signature
            timestamp = params.timestamp
            nonce = params.nonce
            raw_body = web.data()
            decrypted = channel.crypto.decrypt_message(raw_body, signature, timestamp, nonce)
        except (InvalidSignatureException, InvalidCorpIdException) as e:
            logger.warning(f"[wechatcom_kf] invalid signature: {e}")
            raise web.Forbidden()

        # We need the Token + OpenKfId fields from the inner XML to call
        # sync_msg. wechatpy's parsed object exposes neither, so we parse
        # the raw XML directly.
        try:
            root = ET.fromstring(decrypted)
        except ET.ParseError as e:
            logger.error(f"[wechatcom_kf] xml parse error: {e}")
            return "success"

        msg_type = (root.findtext("MsgType") or "").strip()
        event = (root.findtext("Event") or "").strip()
        if msg_type != "event" or event != "kf_msg_or_event":
            logger.debug(
                f"[wechatcom_kf] ignored callback msg_type={msg_type}, event={event}"
            )
            return "success"

        token = root.findtext("Token") or ""
        open_kfid = root.findtext("OpenKfId") or ""
        if not token or not open_kfid:
            logger.warning(
                f"[wechatcom_kf] callback missing token or open_kfid: {decrypted}"
            )
            return "success"

        try:
            channel.consume_callback(token, open_kfid)
        except Exception as e:
            logger.exception(f"[wechatcom_kf] consume_callback error: {e}")
        return "success"
