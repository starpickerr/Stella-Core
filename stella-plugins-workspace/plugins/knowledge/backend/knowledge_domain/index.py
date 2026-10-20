"""Knowledge-owned hybrid index. Authoritative Markdown never depends on Memory."""
from contextlib import closing
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path


class KnowledgeIndex:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / '.knowledge-index.sqlite'
        self.storage = self
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS documents(path TEXT PRIMARY KEY, content TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS vectors(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.commit()

    def delete_by_path(self, path):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DELETE FROM documents WHERE path=?', (path,))
            db.commit()

    async def sync(self):
        rows = []
        for file in sorted(self.root.rglob('*.md')):
            if file.is_symlink() or not file.resolve().is_relative_to(self.root):
                continue
            relative = file.relative_to(self.root)
            if any(part.startswith('.') for part in relative.parts):
                continue
            rows.append(('knowledge/' + relative.as_posix(), file.read_text(encoding='utf-8')))
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute('DELETE FROM documents')
                db.executemany('INSERT INTO documents VALUES (?,?)', rows)

    async def search(self, query, max_results=10, min_score=0.1):
        if not isinstance(query, str) or not query.strip():
            raise ValueError('query required')
        if not 1 <= int(max_results) <= 100 or not 0 <= float(min_score) <= 1:
            raise ValueError('invalid search limits')
        await self.sync()
        tokens = re.findall(r'\w+', query.casefold())
        candidates = []
        with closing(sqlite3.connect(self.path)) as db:
            for path, content in db.execute('SELECT path,content FROM documents ORDER BY path'):
                lines = content.splitlines()
                for start in range(0, len(lines), 30):
                    snippet = '\n'.join(lines[start:start+40])[:6000]
                    lexical = sum(token in snippet.casefold() for token in tokens) / max(len(tokens), 1)
                    candidates.append(dict(path=path, snippet=snippet, start_line=start+1,
                                           end_line=min(start+40,len(lines)), score=lexical))
        try:
            from stella_host import invoke
            status = invoke('stella.models@1', 'embedding_status', {})
            model = status.get('value') or {}
            if model.get('dimensions') and candidates:
                texts = [query, *[row['snippet'] for row in candidates]]
                vectors = self._embed(texts, model, invoke)
                for row, vector in zip(candidates, vectors[1:]):
                    semantic = self._cosine(vectors[0], vector)
                    row['score'] = max(row['score'], 0.7 * semantic + 0.3 * row['score'])
        except (ImportError, RuntimeError, PermissionError, ValueError, KeyError):
            # Optional model failure preserves lexical retrieval and documents.
            pass
        return sorted((row for row in candidates if row['score'] > 0 and row['score'] >= min_score),
                      key=lambda row: -row['score'])[:int(max_results)]

    def _embed(self, texts, model, invoke):
        keys = [hashlib.sha256((json.dumps(model, sort_keys=True) + text).encode()).hexdigest() for text in texts]
        with closing(sqlite3.connect(self.path)) as db:
            found = dict(db.execute('SELECT key,value FROM vectors'))
            missing = list(dict.fromkeys(index for index, key in enumerate(keys) if key not in found))
            for offset in range(0, len(missing), 24):
                indices = missing[offset:offset+24]
                result = invoke('stella.models@1', 'embed', {'texts': [texts[index] for index in indices]})
                if result.get('status') != 'succeeded':
                    raise RuntimeError('embedding unavailable')
                vectors = result['value']['vectors']
                if len(vectors) != len(indices):
                    raise ValueError('invalid embedding batch result')
                for index, vector in zip(indices, vectors):
                    found[keys[index]] = json.dumps(vector)
                    db.execute('INSERT OR REPLACE INTO vectors VALUES (?,?)', (keys[index], found[keys[index]]))
            db.commit()
            return [json.loads(found[key]) for key in keys]

    @staticmethod
    def _cosine(left, right):
        if len(left) != len(right):
            return 0
        denominator = math.sqrt(sum(value*value for value in left) * sum(value*value for value in right))
        return max(0, sum(a*b for a,b in zip(left,right)) / denominator) if denominator else 0
