# encoding:utf-8
"""
DashScope (Aliyun Bailian) voice service.

ASR : qwen3-asr-flash via dashscope.MultiModalConversation
TTS : not yet implemented (see CosyVoice / qwen3-tts)

Why MultiModalConversation instead of the OpenAI-compatible endpoint:
  - SDK is already a project dep (used by chat/vision)
  - Native API accepts local file:// paths up to 100 QPS without an OSS
    round-trip, which is what we need for the "send a short voice
    message" flow. Public URLs / Base64 also work.
"""
import os
from typing import Optional

import dashscope
from dashscope import MultiModalConversation

from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from voice import audio_convert
from voice.voice import Voice


DEFAULT_ASR_MODEL = "qwen3-asr-flash"
# qwen3-asr-flash hard cap (single file, sync call). Longer audio needs
# qwen3-asr-flash-filetrans which is async-only and out of scope here.
MAX_DURATION_SECONDS = 300
MAX_FILE_BYTES = 10 * 1024 * 1024


class DashScopeVoice(Voice):
    def __init__(self):
        # api_key is applied per-call (chat bot does the same) so a live
        # config change via the web console takes effect without restart.
        pass

    def voiceToText(self, voice_file: str):
        try:
            voice_file = self._ensure_compatible_format(voice_file)

            try:
                size = os.path.getsize(voice_file)
                if size > MAX_FILE_BYTES:
                    logger.warning(
                        f"[DashScopeVoice] audio file {size}B exceeds {MAX_FILE_BYTES}B; "
                        f"qwen3-asr-flash may reject it"
                    )
            except OSError:
                pass

            api_key = conf().get("dashscope_api_key", "")
            if not api_key:
                logger.error("[DashScopeVoice] dashscope_api_key is not configured")
                return Reply(ReplyType.ERROR, "未配置 DashScope API key")
            dashscope.api_key = api_key

            model = conf().get("voice_to_text_model") or DEFAULT_ASR_MODEL
            abs_path = os.path.abspath(voice_file)
            file_uri = f"file://{abs_path}"

            messages = [
                {"role": "user", "content": [{"audio": file_uri}]},
            ]
            response = MultiModalConversation.call(
                model=model,
                messages=messages,
                result_format="message",
                asr_options={"enable_itn": False, "enable_lid": True},
            )

            text = self._extract_text(response)
            if text is None:
                logger.error(f"[DashScopeVoice] voiceToText failed: {response}")
                return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

            logger.info(f"[DashScopeVoice] voiceToText model={model} text={text}")
            return Reply(ReplyType.TEXT, text)
        except Exception as e:
            logger.exception(f"[DashScopeVoice] voiceToText exception: {e}")
            return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

    def textToVoice(self, text: str):
        # TTS will be added in a follow-up commit (qwen3-tts / cosyvoice).
        return Reply(ReplyType.ERROR, "DashScope 语音合成尚未接入")

    @staticmethod
    def _ensure_compatible_format(voice_file: str) -> str:
        """Convert AMR/SILK to mp3 since qwen3-asr-flash doesn't accept them.
        Other formats (mp3/wav/m4a/aac/opus/webm) are passed through.
        """
        lower = voice_file.lower()
        if lower.endswith(".amr") or lower.endswith(".silk") or lower.endswith(".slk"):
            try:
                mp3_file = os.path.splitext(voice_file)[0] + ".mp3"
                audio_convert.any_to_mp3(voice_file, mp3_file)
                return mp3_file
            except Exception as e:
                logger.warning(
                    f"[DashScopeVoice] convert {voice_file} to mp3 failed: {e}; "
                    f"submitting original file"
                )
        return voice_file

    @staticmethod
    def _extract_text(response) -> Optional[str]:
        """Pull the recognized text out of MultiModalConversation response.

        Successful shape (result_format="message"):
          response.output.choices[0].message.content -> list of {"text": "..."}
          or in some SDK versions a plain string.
        """
        try:
            if getattr(response, "status_code", 200) != 200:
                return None
            choices = response.output.get("choices") or []
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content")
            if isinstance(content, str):
                return content.strip() or None
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        parts.append(item["text"])
                    elif isinstance(item, str):
                        parts.append(item)
                text = "".join(parts).strip()
                return text or None
            return None
        except Exception:
            return None
