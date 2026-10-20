"""Public model mechanism for approved plugin calls. Credentials remain in Core."""
import threading
from contextvars import ContextVar, copy_context

_BOUND_MODEL = ContextVar('plugin_bound_model', default=None)


def bind_model(model):
    return _BOUND_MODEL.set(model)


def reset_model(token):
    _BOUND_MODEL.reset(token)


def _invoke(method, payload):
    if method in {'embedding_status', 'embed'}:
        from models.embedding import create_default_embedding_provider
        provider = create_default_embedding_provider()
        if method == 'embedding_status':
            value = {'dimensions': provider.dimensions if provider else None, 'provider': type(provider).__name__, 'model': getattr(provider, 'model', '')}
        else:
            texts = payload.get('texts')
            if not isinstance(texts, list) or not 1 <= len(texts) <= 128 or any(not isinstance(text, str) for text in texts):
                raise ValueError('invalid embedding batch')
            if sum(map(len, texts)) > 200_000:
                raise ValueError('embedding batch too large')
            if provider is None:
                return {'status': 'failed', 'sideEffects': 'none', 'error': {'code': 'unavailable', 'message': 'embedding not configured'}}
            value = {'vectors': provider.embed_batch(texts), 'dimensions': provider.dimensions}
    elif method == 'complete':
        request = payload.get('request')
        allowed = {'messages', 'temperature', 'max_tokens', 'system'}
        if not isinstance(request, dict) or set(request) - allowed:
            raise ValueError('model request required')
        import json
        maximum = request.get('max_tokens')
        if maximum is not None and (type(maximum) is not int or not 1 <= maximum <= 32768):
            raise ValueError('invalid model token limit')
        if not isinstance(request.get('messages'), list) or len(request['messages']) > 1000:
            raise ValueError('invalid model messages')
        if len(json.dumps(request)) > 1_000_000:
            raise ValueError('model request too large')
        model = _BOUND_MODEL.get()
        if model is None:
            from bridge.agent_bridge import AgentLLMModel
            model = AgentLLMModel()
        from agent.protocol.models import LLMRequest
        response = model.call(LLMRequest(**{**request, 'stream': False, 'tools': None}))
        # Normalize the public response rather than exporting SDK objects.
        import types
        if isinstance(response, types.GeneratorType):
            response = next(response, {})
        if not isinstance(response, (str, dict, list)):
            response = response.model_dump() if hasattr(response, 'model_dump') else str(response)
        value = {'response': response}
    else:
        raise PermissionError('model method is not public')
    return {'status': 'succeeded', 'sideEffects': 'none', 'value': value}


# Bound model work separately from plugin RPC. A timed-out remote request may
# still finish in Core, but its result cannot resume an expired plugin write.
_MODEL_SLOTS = threading.BoundedSemaphore(4)


def invoke(method, payload):
    from core.plugins.caller import remaining_invocation_seconds
    remaining_invocation_seconds()
    if not _MODEL_SLOTS.acquire(blocking=False):
        raise RuntimeError('model service busy; retry later')
    done = threading.Event()
    result = []
    errors = []
    context = copy_context()
    def run():
        try:
            result.append(context.run(_invoke, method, payload))
        except Exception as exc:
            errors.append(exc)
        finally:
            _MODEL_SLOTS.release()
            done.set()
    threading.Thread(target=run, daemon=True, name='plugin-model').start()
    while not done.wait(0.025):
        remaining_invocation_seconds()
    remaining_invocation_seconds()
    if errors:
        raise errors[0]
    return result[0]
