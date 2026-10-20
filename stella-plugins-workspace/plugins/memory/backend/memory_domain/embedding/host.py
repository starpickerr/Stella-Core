"""Embedding calls cross the approved host model boundary; no credentials in workers."""
class EmbeddingCache:
    def __init__(self, max_size=100):
        self._cache = {}
        self.max_size = max_size

    def get(self, text, provider, model):
        return self._cache.get((text, provider, model))

    def put(self, text, provider, model, value):
        key = (text, provider, model)
        if len(self._cache) >= self.max_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = value

    set = put

    def clear(self):
        self._cache.clear()


class EmbeddingProvider:
    def __init__(self, dimensions, provider='', model=''):
        self.dimensions = dimensions
        self.provider = provider
        self.model = model

    def embed_batch(self, texts):
        from stella_host import invoke
        vectors = []
        for start in range(0, len(texts), 24):
            batch = texts[start:start + 24]
            result = invoke('stella.models@1', 'embed', {'texts': batch})
            if result['status'] != 'succeeded':
                raise RuntimeError('embedding unavailable')
            items = result['value']['vectors']
            if len(items) != len(batch):
                raise ValueError('incomplete embedding batch')
            vectors.extend(items)
        return vectors

    def embed_query(self, text):
        return self.embed_batch([text])[0]


def create_default_embedding_provider():
    from stella_host import invoke
    result = invoke('stella.models@1', 'embedding_status', {})
    metadata = result.get('value') or {}
    dimensions = metadata.get('dimensions')
    return EmbeddingProvider(dimensions, metadata.get('provider', ''), metadata.get('model', '')) if dimensions else None
