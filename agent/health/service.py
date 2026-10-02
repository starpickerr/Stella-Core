"""Local health sample import. No HealthKit access or model transmission."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import uuid
import zipfile
from xml.parsers import expat
from datetime import datetime, timezone, timedelta
from pathlib import Path
from common.state_dir import health_db


class HealthService:
    MAX_UPLOAD = 32 * 1024 * 1024
    MAX_EXPANDED = 128 * 1024 * 1024
    MAX_RECORDS = 500000
    COLUMNS = ('type', 'source', 'device', 'unit', 'value', 'start', 'end', 'created')

    def __init__(self, path=None):
        self.path = Path(path or health_db())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY,filename TEXT NOT NULL,imported_at TEXT NOT NULL,records INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS samples (fingerprint TEXT PRIMARY KEY,type TEXT NOT NULL,source TEXT NOT NULL,device TEXT NOT NULL,unit TEXT NOT NULL,value TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL,created TEXT NOT NULL,start_utc TEXT NOT NULL,end_utc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS import_samples (import_id TEXT NOT NULL REFERENCES imports(id) ON DELETE CASCADE,fingerprint TEXT NOT NULL REFERENCES samples(fingerprint),PRIMARY KEY(import_id,fingerprint));
            ''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @staticmethod
    def _time(raw):
        try:
            value = datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            raise ValueError('Health times must be ISO 8601 with a timezone') from None
        if value.tzinfo is None:
            raise ValueError('Health times must include a timezone')
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _sample(cls, row):
        result = {key: str(row.get(key) or '').strip() for key in cls.COLUMNS}
        if not all(result[key] for key in ('type', 'source', 'value', 'start')):
            raise ValueError('Each health row requires type, source, value and start')
        if any(len(value) > 4096 for value in result.values()):
            raise ValueError('Health field exceeds 4096 characters')
        result['end'] = result['end'] or result['start']
        start = cls._time(result['start']); end = cls._time(result['end'])
        if end < start:
            raise ValueError('Health end precedes start')
        if result['created']:
            cls._time(result['created'])
        # Category values are strings; quantity values must be finite.
        try:
            number = float(result['value'])
        except ValueError:
            number = None
        quantity = result['type'].startswith('HKQuantityTypeIdentifier') or result['type'] in ('steps', 'weight', 'heart_rate', 'distance', 'energy')
        if quantity and number is None:
            raise ValueError('Health quantity samples require a numeric value')
        if number is not None and not math.isfinite(number):
            raise ValueError('Health numeric values must be finite')
        result['device'] = re.sub(r'^<HKDevice: 0x[0-9a-fA-F]+,\s*', '<HKDevice: ', result['device'])
        canonical = dict(result, start=start, end=end,
                         created=cls._time(result['created']) if result['created'] else '')
        if number is not None:
            canonical['value'] = format(number, '.15g')
        fingerprint = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return (fingerprint, *(result[key] for key in cls.COLUMNS), start, end)

    @classmethod
    def parse(cls, filename, data):
        if not isinstance(data, bytes) or len(data) > cls.MAX_UPLOAD:
            raise ValueError('Health upload exceeds 32 MiB')
        suffix = Path(filename).suffix.lower()
        if suffix == '.zip':
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    files = archive.infolist()
                    if len(files) > 10000 or sum(f.file_size for f in files) > cls.MAX_EXPANDED:
                        raise ValueError('Health ZIP expands beyond the 128 MiB limit')
                    candidates = [f for f in files if Path(f.filename).name == 'export.xml' and not f.is_dir()]
                    if len(candidates) != 1:
                        raise ValueError('Health ZIP must contain exactly one export.xml')
                    member = candidates[0]
                    if member.flag_bits & 1:
                        raise ValueError('Encrypted Health ZIP is unsupported')
                    # Read one bounded member into memory; never extract paths.
                    with archive.open(member) as stream:
                        data = stream.read(cls.MAX_EXPANDED + 1)
                    if len(data) > cls.MAX_EXPANDED:
                        raise ValueError('Health XML exceeds 128 MiB')
                    suffix = '.xml'
            except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
                raise ValueError(f'Invalid Health ZIP: {exc}') from None
        rows = []
        if suffix == '.xml':
            parser = expat.ParserCreate()
            depth = 0
            nodes = 0
            def doctype(name, system_id, public_id, internal):
                if system_id or public_id:
                    raise ValueError('External Health XML DTDs are prohibited')
            def entity(*_):
                raise ValueError('Health XML entities are prohibited')
            def start_element(name, a):
                nonlocal depth, nodes
                nodes += 1
                if nodes > 1000000:
                    raise ValueError('Health XML exceeds 1000000 elements')
                depth += 1
                if depth > 32:
                    raise ValueError('Health XML nesting exceeds 32 levels')
                if name == 'Record':
                    rows.append(cls._sample(dict(type=a.get('type'), source=a.get('sourceName'),
                        device=a.get('device'), unit=a.get('unit'), value=a.get('value'),
                        start=a.get('startDate'), end=a.get('endDate'), created=a.get('creationDate'))))
                    if len(rows) > cls.MAX_RECORDS:
                        raise ValueError('Health import exceeds 500000 records')
            def end_element(_):
                nonlocal depth
                depth -= 1
            parser.StartDoctypeDeclHandler = doctype
            parser.EntityDeclHandler = entity
            parser.ExternalEntityRefHandler = entity
            parser.StartElementHandler = start_element
            parser.EndElementHandler = end_element
            try:
                parser.Parse(data, True)
            except expat.ExpatError as exc:
                raise ValueError(f'Invalid Health XML: {exc}') from None
        elif suffix == '.csv':
            try:
                reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
                if not reader.fieldnames or not set(('type','source','value','start')).issubset(reader.fieldnames):
                    raise ValueError('CSV requires type,source,value,start; optional device,unit,end,created')
                for row in reader:
                    rows.append(cls._sample(row))
                    if len(rows) > cls.MAX_RECORDS:
                        raise ValueError('Health import exceeds 500000 records')
            except (UnicodeError, csv.Error) as exc:
                raise ValueError(f'Invalid Health CSV: {exc}') from None
        else:
            raise ValueError('Select an Apple Health XML/ZIP or UTF-8 CSV')
        if not rows:
            raise ValueError('The file contains no health samples')
        return rows

    def import_file(self, filename, data):
        samples = self.parse(filename, data)  # full validation before any write
        import_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            before = db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
            db.execute('INSERT INTO imports VALUES (?,?,?,?)', (import_id, Path(filename).name,
                datetime.now(timezone.utc).isoformat(), len(samples)))
            db.executemany('INSERT OR IGNORE INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?)', samples)
            db.executemany('INSERT OR IGNORE INTO import_samples VALUES (?,?)', [(import_id, row[0]) for row in samples])
            added = db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] - before
        return {'import_id': import_id, 'added': added, 'duplicates': len(samples) - added}

    def delete_import(self, import_id):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            deleted = db.execute('DELETE FROM imports WHERE id=?', (import_id,)).rowcount
            db.execute('DELETE FROM samples WHERE fingerprint NOT IN (SELECT fingerprint FROM import_samples)')
        return bool(deleted)

    @staticmethod
    def _duration(intervals):
        total = 0.0; end = None
        for start, finish in sorted(intervals):
            if end is None or start > end:
                total += (finish-start).total_seconds(); end = finish
            elif finish > end:
                total += (finish-end).total_seconds(); end = finish
        return round(total / 3600, 3)

    def snapshot(self, limit=100):
        with self._connect() as db:
            imports = [dict(row) for row in db.execute('SELECT * FROM imports ORDER BY imported_at DESC LIMIT 100')]
            samples = [dict(row) for row in db.execute('SELECT * FROM samples ORDER BY start_utc DESC LIMIT ?', (max(1,min(limit,500)),))]
            count = db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
            latest = db.execute('SELECT MAX(start_utc) FROM samples').fetchone()[0]
            since = (datetime.fromisoformat(latest) - timedelta(days=30)).isoformat() if latest else ''
        # Stream only the latest data window; never materialize the entire database.
        db = self._connect()
        rows = db.execute('SELECT * FROM samples WHERE start_utc>=? ORDER BY start_utc DESC', (since,))
        groups = {}
        for row in rows:
            day = row['start'][:10]
            key = (day, row['type'], row['source'], row['device'], row['unit'])
            group = groups.setdefault(key, dict(day=day, type=row['type'], source=row['source'],
                device=row['device'], unit=row['unit'], count=0, total=0.0, numeric=True, intervals=[]))
            group['count'] += 1
            if row['type'] in ('HKCategoryTypeIdentifierSleepAnalysis', 'sleep'):
                if row['value'] in ('HKCategoryValueSleepAnalysisAsleep', 'HKCategoryValueSleepAnalysisAsleepUnspecified',
                                    'HKCategoryValueSleepAnalysisAsleepCore', 'HKCategoryValueSleepAnalysisAsleepDeep',
                                    'HKCategoryValueSleepAnalysisAsleepREM', 'asleep', 'core', 'deep', 'rem', '1', '3', '4', '5'):
                    group['intervals'].append((datetime.fromisoformat(row['start_utc']), datetime.fromisoformat(row['end_utc'])))
            else:
                try:
                    group['total'] += float(row['value'])
                except ValueError:
                    group['numeric'] = False
        db.close()
        summary = []
        for group in groups.values():
            intervals = group.pop('intervals')
            if group['type'] in ('HKCategoryTypeIdentifierSleepAnalysis', 'sleep'):
                group['sleep_hours'] = self._duration(intervals)
                group.pop('total'); group.pop('numeric')
            elif not group.pop('numeric'):
                group.pop('total')
            else:
                group['average'] = group['total'] / group['count']
            summary.append(group)
        return {'imports': imports, 'summary': summary[:500], 'samples': samples, 'sample_count': count}
