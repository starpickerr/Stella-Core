"""Upstream wire adapters exposing the model loop's existing chunk contract."""

from __future__ import annotations

from models.openai_compatible_bot import OpenAICompatibleBot
from models.openai.openai_http_client import OpenAIHTTPClient, OpenAIHTTPError


class OpenAIChatAdapter(OpenAICompatibleBot):
    protocol_id = "openai_chat"

    def __init__(self, provider):
        self.provider = provider

    def get_api_config(self):
        from config import conf
        cfg = conf()
        return {"api_key": self.provider.api_key, "api_base": self.provider.api_base,
                "default_temperature": cfg.get("temperature", 0.9),
                "default_top_p": cfg.get("top_p", 1.0),
                "default_frequency_penalty": cfg.get("frequency_penalty", 0.0),
                "default_presence_penalty": cfg.get("presence_penalty", 0.0)}


class NativeProtocolAdapter:
    def __init__(self, provider, protocol_id):
        self.provider = provider
        self.protocol_id = protocol_id
        if protocol_id == "anthropic_messages":
            from models.claudeapi.claude_api_bot import ClaudeAPIBot
            self.bot = ClaudeAPIBot()
        elif protocol_id == "gemini_native":
            from models.gemini.google_gemini_bot import GoogleGeminiBot
            self.bot = GoogleGeminiBot()
        else:
            raise ValueError(f"unsupported native protocol: {protocol_id}")
        self.bot._stella_api_key = provider.api_key
        self.bot._stella_api_base = provider.api_base

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        return self.bot.call_with_tools(messages, tools=tools, stream=stream, **kwargs)


class OpenAIResponsesAdapter(OpenAICompatibleBot):
    """Translate stateless Responses requests and SSE into chat loop events."""

    protocol_id = "openai_responses"

    def __init__(self, provider):
        self.provider = provider
        self._opaque_by_call = {}
        self._opaque_by_text = {}

    def _remember_opaque(self, response):
        pending = []
        for item in response.get("output", []):
            if item.get("type") == "reasoning":
                if not item.get("encrypted_content"):
                    raise ValueError("Responses reasoning state was not returned for stateless continuation")
                pending.append(item)
            elif item.get("type") == "function_call" and pending:
                self._opaque_by_call[item["call_id"]] = list(pending)
                pending.clear()
            elif item.get("type") == "message" and pending:
                content = "".join(part.get("text") or "" for part in item.get("content", [])
                                  if part.get("type") == "output_text")
                if content:
                    self._opaque_by_text[content] = list(pending)
                    pending.clear()
        if pending:
            raise ValueError("Responses returned unpaired reasoning state")
        for mapping in (self._opaque_by_call, self._opaque_by_text):
            while len(mapping) > 64:
                mapping.pop(next(iter(mapping)))

    def _input(self, messages):
        for message in messages:
            if message.get("_gemini_raw_parts"):
                raise ValueError("Responses cannot replay Gemini provider state")
            content = message.get("content")
            if isinstance(content, list):
                kinds = {part.get("type") for part in content if isinstance(part, dict)}
                if any(not isinstance(part, dict) for part in content):
                    raise ValueError("unsupported Responses content block")
                if "thinking" in kinds:
                    raise ValueError("Responses cannot replay provider-specific thinking blocks")
                if kinds - {"text", "tool_use", "tool_result", "image_url"}:
                    raise ValueError(f"unsupported Responses content blocks: {sorted(map(str, kinds))}")
                if "tool_result" in kinds and kinds - {"text", "tool_result"}:
                    raise ValueError("Responses cannot mix tool results with image content")
        chat = self._convert_messages_to_openai_format(messages)
        result = []
        for message in chat:
            role = message.get("role")
            if message.get("reasoning_content"):
                raise ValueError("Responses cannot replay provider-specific reasoning state from this session")
            if role == "tool":
                result.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                               "output": str(message.get("content") or "")})
                continue
            if role not in ("user", "assistant", "system", "developer"):
                raise ValueError(f"unsupported Responses message role: {role}")
            content = message.get("content") or ""
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append({"type": "input_text" if role != "assistant" else "output_text",
                                      "text": part.get("text") or ""})
                    elif part.get("type") == "image_url" and role == "user":
                        image = part.get("image_url")
                        parts.append({"type": "input_image", "image_url": image.get("url") if isinstance(image, dict) else image})
                    else:
                        raise ValueError(f"unsupported Responses content block: {part.get('type')}")
                content = parts
            if content:
                if role == "assistant" and isinstance(content, str):
                    result.extend(self._opaque_by_text.get(content, []))
                result.append({"role": role, "content": content})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                result.extend(self._opaque_by_call.get(call["id"], []))
                result.append({"type": "function_call", "call_id": call["id"],
                               "name": function["name"], "arguments": function.get("arguments") or "{}"})
        return result

    @staticmethod
    def _tools(tools):
        result = []
        for tool in tools or []:
            function = tool.get("function") if tool.get("type") == "function" else tool
            result.append({"type": "function", "name": function["name"],
                           "description": function.get("description") or "",
                           "parameters": function.get("parameters") or function.get("input_schema") or
                                         {"type": "object", "properties": {}},
                           "strict": False})
        return result

    @staticmethod
    def _usage(usage):
        usage = usage or {}
        prompt = usage.get("input_tokens", 0)
        completion = usage.get("output_tokens", 0)
        return {"prompt_tokens": prompt, "completion_tokens": completion,
                "total_tokens": usage.get("total_tokens", prompt + completion)}

    def _response(self, response):
        self._remember_opaque(response)
        content = "".join(part.get("text") or "" for item in response.get("output", [])
                          if item.get("type") == "message"
                          for part in item.get("content", []) if part.get("type") == "output_text")
        calls = [{"id": item["call_id"], "type": "function",
                  "function": {"name": item["name"], "arguments": item.get("arguments") or "{}"}}
                 for item in response.get("output", []) if item.get("type") == "function_call"]
        return {"choices": [{"message": {"role": "assistant", "content": content,
                                         **({"tool_calls": calls} if calls else {})},
                             "finish_reason": "tool_calls" if calls else "stop"}],
                "usage": OpenAIResponsesAdapter._usage(response.get("usage"))}

    def _stream(self, events):
        indices, arguments = {}, {}
        emitted_text = False
        for event in events:
            if event.get("error"):
                yield event
                return
            kind = event.get("type")
            if kind == "response.output_text.delta":
                emitted_text = True
                yield {"choices": [{"delta": {"content": event.get("delta") or ""}}]}
            elif kind == "response.refusal.delta":
                emitted_text = True
                yield {"choices": [{"delta": {"content": event.get("delta") or ""}}]}
            elif kind == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    key = event.get("output_index", len(indices))
                    indices[item.get("id") or key] = key
                    arguments[key] = ""
                    yield {"choices": [{"delta": {"tool_calls": [{"index": key,
                        "id": item.get("call_id") or item.get("id"),
                        "function": {"name": item.get("name") or "", "arguments": ""}}]}}]}
            elif kind == "response.function_call_arguments.delta":
                key = event.get("output_index", indices.get(event.get("item_id")))
                if key is None:
                    raise ValueError("Responses argument delta arrived before its function call")
                delta = event.get("delta") or ""
                arguments[key] = arguments.get(key, "") + delta
                yield {"choices": [{"delta": {"tool_calls": [{"index": key,
                    "function": {"arguments": delta}}]}}]}
            elif kind == "response.function_call_arguments.done":
                key = event.get("output_index", indices.get(event.get("item_id")))
                if key is None:
                    raise ValueError("Responses function call completed before it was announced")
                complete = event.get("arguments") or ""
                previous = arguments.get(key, "")
                if not complete.startswith(previous):
                    raise ValueError("Responses function arguments changed while streaming")
                missing = complete[len(previous):]
                if missing:
                    yield {"choices": [{"delta": {"tool_calls": [{"index": key,
                        "function": {"arguments": missing}}]}}]}
                arguments[key] = complete
            elif kind == "response.completed":
                response = event.get("response") or {}
                self._remember_opaque(response)
                if not emitted_text:
                    text = "".join(part.get("text") or part.get("refusal") or ""
                                   for item in response.get("output", []) if item.get("type") == "message"
                                   for part in item.get("content", []))
                    if text:
                        yield {"choices": [{"delta": {"content": text}}]}
                yield {"choices": [{"delta": {},
                    "finish_reason": "tool_calls" if arguments else "stop"}],
                    "usage": OpenAIResponsesAdapter._usage(response.get("usage"))}
            elif kind == "response.incomplete":
                response = event.get("response") or {}
                yield {"choices": [{"delta": {}, "finish_reason": "length"}],
                       "usage": OpenAIResponsesAdapter._usage(response.get("usage"))}
            elif kind in ("response.failed", "error"):
                error = (event.get("response") or {}).get("error") or event.get("error") or {}
                yield {"error": True, "message": error.get("message") if isinstance(error, dict) else str(error),
                       "status_code": event.get("status_code") or 500}
                return

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        from config import conf
        model = kwargs.get("model")
        if not model:
            raise ValueError("Responses requires an explicit model")
        payload = {"model": model, "input": self._input(messages), "stream": stream,
                   "store": False, "include": ["reasoning.encrypted_content"]}
        if kwargs.get("system"):
            payload["instructions"] = kwargs["system"]
        if tools:
            payload["tools"] = self._tools(tools)
            payload["tool_choice"] = kwargs.get("tool_choice", "auto")
        if kwargs.get("max_tokens"):
            payload["max_output_tokens"] = kwargs["max_tokens"]
        if kwargs.get("reasoning_effort"):
            payload["reasoning"] = {"effort": kwargs["reasoning_effort"]}
        client = OpenAIHTTPClient(proxy=conf().get("proxy") or None)
        try:
            result = client._request(path="/responses", payload=payload,
                                     api_key=self.provider.api_key,
                                     api_base=self.provider.api_base, timeout=None,
                                     stream=stream)
            return self._stream(result) if stream else self._response(result)
        except OpenAIHTTPError as exc:
            error = {"error": True, "message": exc.message, "status_code": exc.status_code}
            return iter((error,)) if stream else error


def create_protocol_adapter(provider, binding):
    if binding.protocol_id == "openai_chat":
        return OpenAIChatAdapter(provider)
    if binding.protocol_id == "openai_responses":
        return OpenAIResponsesAdapter(provider)
    if binding.protocol_id in ("anthropic_messages", "gemini_native"):
        return NativeProtocolAdapter(provider, binding.protocol_id)
    raise ValueError(f"unsupported upstream protocol: {binding.protocol_id}")
