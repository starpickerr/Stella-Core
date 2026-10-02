import io
import sqlite3
import zipfile
import pytest
from agent.health import HealthService
from common.runtime_identity import identity_scope


def xml(records, dtd=''):
    return ('<?xml version="1.0"?>' + dtd + '<HealthData>' + records + '</HealthData>').encode()


def record(value='500', source='Phone', kind='HKQuantityTypeIdentifierStepCount',
           start='2026-10-02 00:00:00 +0800', end='2026-10-02 01:00:00 +0800', device='Phone'):
    return f'<Record type="{kind}" sourceName="{source}" device="{device}" unit="count" value="{value}" startDate="{start}" endDate="{end}"/>'


def test_apple_structural_dtd_and_zip_never_extracts(tmp_path):
    service = HealthService(tmp_path/'health.db')
    declaration = '<!DOCTYPE HealthData [<!ELEMENT HealthData (Record*)><!ELEMENT Record EMPTY><!ATTLIST Record type CDATA #REQUIRED>]>'
    data = xml(record(), declaration)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('../../apple_health_export/export.xml', data)
    result = service.import_file('health.zip', archive.getvalue())
    assert result['added'] == 1
    assert not (tmp_path.parent / 'apple_health_export').exists()
    duplicate = service.import_file('health.xml', data)
    assert duplicate['added'] == 0 and duplicate['duplicates'] == 1
    assert service.delete_import(result['import_id'])
    assert service.snapshot()['sample_count'] == 1
    assert service.delete_import(duplicate['import_id'])
    assert service.snapshot()['sample_count'] == 0


@pytest.mark.parametrize('declaration', [
    '<!DOCTYPE HealthData [<!ENTITY secret "private">]>',
    '<!DOCTYPE HealthData SYSTEM "file:///etc/passwd">',
    '<!DOCTYPE HealthData PUBLIC "Health" "https://example.com/health.dtd">',
])
def test_xml_entities_and_external_dtd_rejected(tmp_path, declaration):
    service = HealthService(tmp_path/'health.db')
    with pytest.raises(ValueError):
        service.import_file('health.xml', xml(record(), declaration))
    assert service.snapshot()['imports'] == []


def test_atomic_csv_unit_source_sleep_and_canonical_dedup(tmp_path):
    service = HealthService(tmp_path/'health.db')
    csv = b'type,source,device,unit,value,start,end\nsteps,Phone,Phone,count,500,2026-10-02T00:00:00Z,\nsteps,Watch,Watch,count,1000,2026-10-02T00:00:00Z,\nweight,Scale,Scale,lb,150,2026-10-02T00:00:00Z,\nsleep,Watch,Watch,,inbed,2026-10-02T00:00:00Z,2026-10-02T09:00:00Z\nsleep,Watch,Watch,,asleep,2026-10-02T01:00:00Z,2026-10-02T08:00:00Z\nsleep,Watch,Watch,,core,2026-10-02T01:00:00Z,2026-10-02T04:00:00Z\nsleep,Watch,Watch,,deep,2026-10-02T03:00:00Z,2026-10-02T05:00:00Z\n'
    result = service.import_file('health.csv', csv)
    assert result['added'] == 7
    snap = service.snapshot()
    assert sorted(r['total'] for r in snap['summary'] if r['type']=='steps') == [500,1000]
    assert next(r for r in snap['summary'] if r['type']=='sleep')['sleep_hours'] == 7
    assert next(r for r in snap['samples'] if r['type']=='weight')['unit']=='lb'
    variant = b'type,source,device,unit,value,start,end\nsteps,Phone,Phone,count,500.0,2026-10-02T08:00:00+08:00,\n'
    assert service.import_file('variant.csv',variant)['added']==0
    with pytest.raises(ValueError):
        service.import_file('bad.csv', csv + b'weight,Scale,,kg,NaN,2026-10-02T00:00:00Z,\n')
    assert service.snapshot()['sample_count']==7


def test_invalid_limits_and_deep_xml_are_atomic(tmp_path, monkeypatch):
    service=HealthService(tmp_path/'health.db')
    for data in (xml(record()+'<bad>'), ('<a>'*33+'</a>'*33).encode()):
        with pytest.raises(ValueError):
            service.import_file('health.xml',data)
    monkeypatch.setattr(HealthService,'MAX_RECORDS',1)
    with pytest.raises(ValueError,match='records'):
        service.import_file('health.xml',xml(record()+record(source='Watch')))
    assert service.snapshot()['sample_count']==0
    monkeypatch.setattr(HealthService,'MAX_EXPANDED',20)
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('export.xml',xml(record()))
    with pytest.raises(ValueError,match='128 MiB'):
        service.import_file('health.zip',archive.getvalue())


def test_users_cannot_read_or_delete_each_others_health(tmp_path, monkeypatch):
    monkeypatch.setattr('agent.health.service.health_db',lambda: tmp_path/( __import__('common.runtime_identity',fromlist=['current_identity']).current_identity().user_id+'.db'))
    with identity_scope(user_id='user1'):
        first=HealthService(); result=first.import_file('a.xml',xml(record()))
    with identity_scope(user_id='user2'):
        second=HealthService()
        assert second.snapshot()['sample_count']==0
        assert not second.delete_import(result['import_id'])
    assert first.snapshot()['sample_count']==1


def test_real_multipart_http_upload_preserves_binary_zip(tmp_path):
    import subprocess, sys
    code = '''
import io,json,sys,zipfile
from pathlib import Path
import web
from agent.health import service
from channel.web import web_channel
service.health_db=lambda: Path(sys.argv[1])/'health.db'
web_channel._require_auth=lambda: None
xml=b'<!DOCTYPE HealthData [<!ELEMENT HealthData (Record*)><!ELEMENT Record EMPTY>]><HealthData><Record type="HKQuantityTypeIdentifierStepCount" sourceName="Phone" unit="count" value="500" startDate="2026-10-02T00:00:00Z" endDate="2026-10-02T01:00:00Z"/></HealthData>'
archive=io.BytesIO()
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z: z.writestr('apple_health_export/export.xml',xml)
boundary='test-stella-upload-boundary'
payload=b'--'+boundary.encode()+b'\\r\\nContent-Disposition: form-data; name="file"; filename="health.zip"\\r\\nContent-Type: application/zip\\r\\n\\r\\n'+archive.getvalue()+b'\\r\\n--'+boundary.encode()+b'--\\r\\n'
app=web.application(('/api/health/import','Import'), {'Import':web_channel.HealthImportHandler})
env={'REQUEST_METHOD':'POST','PATH_INFO':'/api/health/import','SCRIPT_NAME':'','QUERY_STRING':'','SERVER_NAME':'127.0.0.1','SERVER_PORT':'80','SERVER_PROTOCOL':'HTTP/1.1','wsgi.version':(1,0),'wsgi.url_scheme':'http','wsgi.input':io.BytesIO(payload),'wsgi.errors':sys.stderr,'wsgi.multithread':False,'wsgi.multiprocess':False,'wsgi.run_once':False,'CONTENT_TYPE':'multipart/form-data; boundary='+boundary,'CONTENT_LENGTH':str(len(payload))}
status=[]
response=b''.join(app.wsgifunc()(env,lambda value,headers:status.append(value)))
assert status[0].startswith('200'), response
result=json.loads(response)
assert result['status']=='success' and result['added']==1,result
print('binary multipart upload passed')
'''
    result = subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr+result.stdout
