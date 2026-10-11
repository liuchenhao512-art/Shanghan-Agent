"""专题对话、旧数据迁移及文件夹持久化的行为验证。"""
import json
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from test_core import store, seed, library, add_text, ROOT, BUILTIN
from server.storage import Store, stamp, dumps
from server.app import create_app
from server.research import ResearchManager
from server.exports import backup, preview_restore, restore


def test_direct_create_idempotent_cancel_and_folder(store):
    app = create_app(store.root, BUILTIN, ROOT/'ui')
    with TestClient(app) as client:
        assert client.post('/api/v1/libraries', json={'title':'  '}).status_code == 400
        assert client.get('/api/v1/projects').json() == []
        payload = {'title':'桂枝汤证', 'request_id':'a'*32}
        first = client.post('/api/v1/libraries', json=payload).json()
        assert client.post('/api/v1/libraries', json=payload).json()['id'] == first['id']
        assert len(client.get('/api/v1/libraries').json()) == 1
        assert first['title'] == '桂枝汤证'
        assert client.get('/api/v1/projects').json() == []
        project = client.post('/api/v1/projects', json={'title':'独立研究'}).json()
        assert (store.root/project['folder']/'对话记录.md').is_file()
        assert len(client.get('/api/v1/libraries').json()) == 1
        assert client.post('/api/v1/libraries', json={**payload,'title':'不同内容'}).status_code == 400
    with store.connection() as con:
        assert con.execute('SELECT count(*) FROM proposals').fetchone()[0] == 0
    assert not store.projects.create('../../危险/标题')['folder'].startswith('../')


class ConversationalModel:
    def __init__(self): self.inputs = []
    def config(self): return {'configured':True}
    async def complete(self, messages, max_tokens=4000):
        prompt = json.loads(messages[-1]['content']); self.inputs.append(prompt)
        if 'evidence' in prompt:
            evidence = prompt['evidence'][0]
            return dumps({'answer':[{'text':'根据已读原文回答本次追问（程序验证）','citations':[{'evidence_id':evidence['evidence_id'],'quote':'汗出恶风'}]}]}), {}
        if prompt.get('search_results'):
            return dumps({'queries':[],'read_ids':[prompt['search_results'][0]['id']],'finish':True}), {}
        return dumps({'queries':['太阳'],'read_ids':[],'finish':False}), {}


@pytest.mark.asyncio
async def test_followup_context_scope_and_saved_notes(store):
    a = store.projects.create('桂枝汤证')['id']; b = store.projects.create('不同专题')['id']
    la, lb = library(store, '资料A'), library(store, '资料B')
    add_text(store, la); add_text(store, lb, '太阳病，其他专题独有内容。', '另一来源.txt')
    scope = store.snapshot([la]); gateway = ConversationalModel(); manager = ResearchManager(store, gateway)
    first = manager.start('先说明桂枝汤证', scope, a, 'b'*32)
    assert manager.start('先说明桂枝汤证', scope, a, 'b'*32)['id'] == first['id']
    await manager.running[first['id']]
    second = manager.start('刚才说的汗出恶风如何理解？', scope, a)
    await manager.running[second['id']]
    assert json.loads(store.task(second['id'])['context'])[0]['content'] == '先说明桂枝汤证'
    assert gateway.inputs[3]['conversation'][1]['evidence_status'].startswith('历史AI回答')
    project = store.projects.get(a)
    assert len(project['turns']) == 2 and store.projects.get(b)['turns'] == []
    assert all(e['source_id'] in scope['source_ids'] for t in project['turns'] for e in t['evidence'])
    assert '<table>' not in project['turns'][1]['html']
    assert '根据已读原文' in project['turns'][1]['html']
    p = manager.propose_save(second['id']); store.confirm(p['id'], p['hash'])
    note = store.projects.get(a)['notes'][0]
    assert note['project_id'] == a and not store.projects.get(b)['notes']
    folder = store.root/project['folder']
    assert '刚才说的汗出恶风' in (folder/'对话记录.md').read_text(encoding='utf-8')
    assert (folder/'研读草稿'/(second['id']+'.md')).is_file()
    assert (folder/'正式笔记'/(note['id']+'.md')).is_file()
    restarted = Store(store.root, BUILTIN)
    assert [t['id'] for t in restarted.projects.get(a)['turns']] == [first['id'], second['id']]
    raw = Path(backup(restarted)['path']).read_bytes()
    preview = preview_restore(restarted, raw); restored = restore(restarted, preview['id'], preview['hash'])
    target = Store(restored['directory'], Path(restored['directory'])/'builtin')
    assert len(target.projects.get(a)['turns']) == 2
    assert target.projects.get(a)['notes'][0]['id'] == note['id']
    assert (target.root/project['folder']/'对话记录.md').read_bytes() == (folder/'对话记录.md').read_bytes()


def test_upgrade_v1_preserves_old_tasks_and_notes(store):
    lid = library(store, '已有资料专题'); sid = add_text(store, lid)
    with store.connection(True) as con:
        con.execute('DROP INDEX task_project'); con.execute('DROP INDEX note_project')
        con.execute('ALTER TABLE tasks DROP COLUMN project_id'); con.execute('ALTER TABLE tasks DROP COLUMN context')
        con.execute('ALTER TABLE notes DROP COLUMN project_id'); con.execute('DROP TABLE research_projects')
        con.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        for tid, scope in [('old-topic', {'library_ids':[lid],'source_ids':[sid]}), ('old-builtin', {'library_ids':[],'source_ids':[]})]:
            con.execute('INSERT INTO tasks(id,question,scope,status,created,updated,draft) VALUES(?,?,?,?,?,?,?)', (tid,'旧研读问题',dumps(scope),'awaiting_review',stamp(),stamp(),dumps({'body':'旧回答仍需保留'})))
        con.execute('INSERT INTO notes(id,title,body,evidence,task_id,created) VALUES(?,?,?,?,?,?)', ('old-note','既有笔记','旧内容','[]','old-topic',stamp()))
    old_backup = Path(backup(store)['path']).read_bytes()
    upgraded = Store(store.root, BUILTIN)
    assert upgraded.task('old-topic')['project_id'] == lid
    assert upgraded.projects.get(lid)['notes'][0]['body'] == '旧内容'
    assert len(upgraded.projects.list()) == 2
    assert upgraded.projects.get(upgraded.task('old-builtin')['project_id'])['title'] == '历史研读'
    assert upgraded.source(sid)['chunks'][0]['text'].startswith('太阳病')
    again = Store(store.root, BUILTIN)
    assert len(again.projects.list()) == 2
    preview = preview_restore(again, old_backup)
    restored = restore(again, preview['id'], preview['hash'])
    old_restored = Store(restored['directory'], Path(restored['directory'])/'builtin')
    assert old_restored.projects.get(lid)['notes'][0]['body'] == '旧内容'


def test_chat_html_does_not_execute_imported_or_model_markup(store):
    pid = store.projects.create('安全显示')['id']
    with store.connection(True) as con:
        con.execute('INSERT INTO tasks(id,question,scope,status,created,updated,project_id,draft) VALUES(?,?,?,?,?,?,?,?)', ('html-test','问题',dumps({'titles':[]}), 'failed',stamp(),stamp(),pid,dumps({'body':'<script>alert(1)</script>\n\n[链接](javascript:alert(1))'})))
    html = store.projects.get(pid)['turns'][0]['html']
    assert '<script>' not in html and 'href="javascript:' not in html
    with store.connection(True) as con:
        con.execute("UPDATE tasks SET id='../../escape' WHERE id='html-test'")
    store.projects.sync(pid)
    folder = store.projects.folder_path(store.projects.get(pid))
    assert len(list((folder/'研读草稿').glob('*.md'))) == 1
    assert not (store.root/'escape.md').exists()
