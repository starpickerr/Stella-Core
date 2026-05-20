# encoding:utf-8
"""
ZhipuAI (BigModel) voice service.

ASR : glm-asr-2512 via the OpenAI-compatible /audio/transcriptions endpoint.
TTS : not yet implemented.

Endpoint accepts multipart/form-data with `model`, `file`, and `stream`.
File size <= 25MB, duration <= 30s per request.
"""
import os

import requests

from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from voice import audio_convert
from voice.voice import Voice


DEFAULT_ASR_MODEL = "glm-asr-2512"
DEFAULT_API_BASE = "https://open.bigmodel.cn/api/paas/v4"
MAX_FILE_BYTES = 25 * 1024 * 1024
REQUEST_TIMEOUT = (5, 60)


class ZhipuAIVoice(Voice):
    def __init__(self):
        # api_key / base read per-call so live config edits take effect.
        pass

    def voiceToText(self, voice_file: str):
        try:
            voice_file = self._ensure_compatible_format(voice_file)

            try:
                size = os.path.getsize(voice_file)
                if size > MAX_FILE_BYTES:
                    logger.warning(
                        f"[ZhipuAIVoice] audio file {size}B exceeds {MAX_FILE_BYTES}B; "
                        f"glm-asr-2512 may reject it"
                    )
            except OSError:
                pass

            api_key = conf().get("zhipu_ai_api_key", "")
            if not api_key:
                logger.error("[ZhipuAIVoice] zhipu_ai_api_key is not configured")
                return Reply(ReplyType.ERROR, "未配置 ZhipuAI API key")

            api_base = (conf().get("zhipu_ai_api_base") or DEFAULT_API_BASE).rstrip("/")
            url = f"{api_base}/audio/transcriptions"
            model = conf().get("voice_to_text_model") or DEFAULT_ASR_MODEL

            with open(voice_file, "rb") as f:
                files = {"file": (os.path.basename(voice_file), f)}
                data = {"model": model, "stream": "false"}
                headers = {"Authorization": f"Bearer {api_key}"}
                response = requests.post(
                    url, headers=headers, files=files, data=data, timeout=REQUEST_TIMEOUT
                )

            if response.status_code != 200:
                logger.error(
                    f"[ZhipuAIVoice] voiceToText failed: status={response.status_code} "
                    f"body={response.text[:500]}"
                )
                return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

            payload = response.json()
            text = (payload.get("text") or "").strip()
            if not text:
                logger.error(f"[ZhipuAIVoice] voiceToText empty text: {payload}")
                return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

            logger.info(f"[ZhipuAIVoice] voiceToText model={model} text={text}")
            return Reply(ReplyType.TEXT, text)
        except Exception as e:
            logger.exception(f"[ZhipuAIVoice] voiceToText exception: {e}")
            return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

    def textToVoice(self, text: str):
        return Reply(ReplyType.ERROR, "ZhipuAI 语音合成尚未接入")

    @staticmethod
    def _ensure_compatible_format(voice_file: str) -> str:
        # glm-asr-2512 only accepts .wav / .mp3 — convert everything else
        # (webm from the browser mic, m4a/amr/silk from chat channels, etc).
        lower = voice_file.lower()
        if lower.endswith(".mp3") or lower.endswith(".wav"):
            return voice_file
        try:
            mp3_file = os.path.splitext(voice_file)[0] + ".mp3"
            audio_convert.any_to_mp3(voice_file, mp3_file)
            return mp3_file
        except Exception as e:
            logger.warning(
                f"[ZhipuAIVoice] convert {voice_file} to mp3 failed: {e}; "
                f"submitting original file"
            )
            return voice_file
