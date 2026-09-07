"""Core acceptance tests run with all outbound sockets denied and no API keys."""
import importlib
import inspect
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.test_parser import ACCEPTANCE_BOL

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def offline_client(monkeypatch, tmp_path):
    for key in list(os.environ):
        if 'API_KEY' in key or key.endswith('_TOKEN'):
            monkeypatch.delenv(key, raising=False)
    original_connect = socket.socket.connect
    def denied(self, address):
        # Windows asyncio implements its internal socketpair through loopback.
        # Permit only that exact stdlib caller; all application connections fail.
        if inspect.currentframe().f_back.f_code is socket.socketpair.__code__:
            return original_connect(self, address)
        raise OSError('Strict offline test: outbound network disabled, including Ollama')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    import database.db as db
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'offline.db'))
    db.init_db()
    application=importlib.import_module('app')
    with TestClient(application.app) as client:
        yield client

@pytest.mark.parametrize('page', ['/', '/search', '/manual', '/assistant', '/mock-test', '/master', '/history', '/settings'])
def test_offline_pages(offline_client, page):
    response=offline_client.get(page)
    assert response.status_code==200
    assert '<html' in response.text.lower()
    assert 'https://cdn' not in response.text


def test_offline_core(offline_client):
    client=offline_client
    assert client.get('/api/health').json()['status']=='ok'
    assert client.get('/api/ollama/status').json()['available'] is False
    codes=client.get('/api/mcodes').json()
    assert codes['count']==len(codes['codes'])>0
    assert client.get('/api/search',params={'q':'M48'}).json()['results'][0]['code']=='M48'
    result=client.post('/api/analyze',json={'text':ACCEPTANCE_BOL}).json()
    expected=[('MM','2 SKDS'),('MA','JOHN SMITH'),('MPO','458921'),('MDOUBL','DO NOT STACK'),('MLIFT','LIFT GATE DELIVERY'),('M24','555-1234')]
    assert [(e['code'],e['value']) for e in result['suggested_entries']]==expected
    assert all(e['status']=='CONFIRMED' for e in result['entries'])
    manual=client.post('/api/analyze',json={'source_type':'manual','fields':{
        'handling_units':'2 SKIDS', 'attn':'JOHN SMITH','references':'PO #: 458921',
        'special_instructions':'DO NOT STACK\nLIFT GATE DELIVERY\nCALL 24 HRS BEFORE DELIVERY',
        'contact_information':'PHONE: 555-1234'}})
    assert manual.status_code==200
    assert [(e['code'],e['value']) for e in manual.json()['suggested_entries']]==expected
    for wording,code in [('CALL FOR APPOINTMENT','MCFA'),('CALL FOR APPOINTMENT 48 HOURS BEFORE DELIVERY','M48'),('CALL BEFORE DELIVERY','MBEFOR')]:
        response=client.post('/api/analyze',json={'text':wording})
        assert [e['code'] for e in response.json()['entries']]==[code]
    history=client.get('/api/history').json()['history']
    assert len(history)==5
    assert len(client.get('/api/history',params={'search':'JOHN'}).json()['history'])==2
    questions=client.get('/api/mock/questions',params={'count':500}).json()['questions']
    authoritative={c['code']:c for c in codes['codes']}
    assert len(questions)==len(authoritative)
    all_questions=client.get('/api/mock/questions',params={'count':0}).json()['questions']
    assert len(all_questions)==len(authoritative)
    for question in questions:
        assert question['meaning']==authoritative[question['code']]['meaning']
        assert question['prompt']==question['meaning'].upper()
    assert client.post('/api/mock/record',json={'code':'m48','correct':False}).status_code==200
    weak=client.get('/api/mock/weak').json()['weak_codes']
    assert weak[0]['code']=='M48' and weak[0]['wrong']==1
    assert [q['code'] for q in client.get('/api/mock/questions',params={'mode':'wrong'}).json()['questions']]==['M48']
    assert client.post('/api/mock/record',json={'code':'M48','correct':True}).status_code==200
    assert client.get('/api/mock/weak').json()['weak_codes'][0]['accuracy']==50.0
    assert client.post('/api/mock/session',json={'mode':'practice','category':'All Categories','total':2,'correct':1}).json()['score']==50
    assert client.get('/api/stats').json()['total_tests']==1
    import database.db as db
    db.init_db()  # Reopen storage: history and progress persist.
    assert len(db.list_history())==5 and db.get_weak_codes()[0]['attempts']==2
    assert client.post('/api/mock/record',json={'code':'FAKE','correct':False}).status_code==422
    assert client.post('/api/mock/session',json={'mode':'practice','category':'All Categories','total':1,'correct':2}).status_code==422


def test_offline_server_startup(tmp_path):
    """Start the real HTTP server under a network-denied child process."""
    import urllib.request
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
    program='''import socket, uvicorn, inspect
from app import app
original_connect = socket.socket.connect
def denied(self, address):
    if inspect.currentframe().f_back.f_code is socket.socketpair.__code__:
        return original_connect(self, address)
    raise OSError('offline test')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='info')
'''.replace('PORT',str(port))
    env={k:v for k,v in os.environ.items() if 'API_KEY' not in k and not k.endswith('_TOKEN')}
    env['TENET_DB_PATH']=str(tmp_path/'server.db')
    log=tmp_path/'server.log'
    with log.open('w') as output:
        process=subprocess.Popen([sys.executable,'-c',program],cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+20
            ready=False
            while time.monotonic()<deadline and process.poll() is None:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.5) as response:
                        ready=response.status==200
                        break
                except OSError:
                    time.sleep(.1)
            assert ready, log.read_text()
        finally:
            process.terminate()
            process.wait(timeout=10)
    text=log.read_text()
    assert 'Application startup complete' in text
    assert 'Traceback' not in text
