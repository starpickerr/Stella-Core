# -*- coding=utf-8 -*-
"""
Adapter that turns a single `sync_msg` item from WeCom customer-service
into a CoW `ChatMessage` object.
"""
from wechatpy.enterprise import WeChatClient

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.log import logger
from common.tmp_dir import TmpDir


class WechatComKfMessage(ChatMessage):
    """
    msg structure (from cgi-bin/kf/sync_msg):
        {
          "msgid": "...",
          "send_time": 1700000000,
          "origin": 3,
          "msgtype": "text" | "image" | "voice" | ...,
          "open_kfid": "wkxxxx",
          "external_userid": "wmxxxx",
          "text": {"content": "..."},
          "image": {"media_id": "..."},
          "voice": {"media_id": "..."},
          ...
        }
    """

    def __init__(self, msg: dict, client: WeChatClient = None, is_group: bool = False):
        # NOTE: skip parent constructor because it expects a wechatpy parsed
        # message object, while here we receive a raw dict from sync_msg.
        super().__init__(msg)
        self.is_group = is_group
        self.msg_id = msg.get("msgid")
        self.create_time = msg.get("send_time")
        self.origin = msg.get("origin")
        self.msgtype = msg.get("msgtype")
        self.open_kfid = msg.get("open_kfid")
        self.external_userid = msg.get("external_userid")

        if self.msgtype == "text":
            self.ctype = ContextType.TEXT
            self.content = msg.get("text", {}).get("content", "")
        elif self.msgtype == "image":
            self.ctype = ContextType.IMAGE
            media_id = msg.get("image", {}).get("media_id", "")
            self.content = TmpDir().path() + media_id + ".jpg"

            def download_image():
                response = client.media.download(media_id)
                if response.status_code == 200:
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechatcom_kf] Failed to download image, {response.content}")

            self._prepare_fn = download_image
        elif self.msgtype == "voice":
            self.ctype = ContextType.VOICE
            media_id = msg.get("voice", {}).get("media_id", "")
            # WeCom returns amr by default; downstream voice pipeline will convert.
            self.content = TmpDir().path() + media_id + ".amr"

            def download_voice():
                response = client.media.download(media_id)
                if response.status_code == 200:
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechatcom_kf] Failed to download voice, {response.content}")

            self._prepare_fn = download_voice
        else:
            raise NotImplementedError(
                f"[wechatcom_kf] Unsupported message type: {self.msgtype}"
            )

        self.from_user_id = self.external_userid
        self.to_user_id = self.open_kfid
        self.other_user_id = self.external_userid
