"""独立管理、归档删除、升级和无轮数上限的行为验证。"""
import asyncio
import json
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from test_core import store, seed, library, add_text, BUILTIN, ROOT
from test_projects import ConversationalModel
from server.storage import Store, Conflict, dumps, stamp
from server.research import ResearchManager
from server.app import create_app
from server.exports import backup, preview_restore, restore


def commit(store, kind, key, **fields):
    p = store.propose(kind, {'id':key, **fields})
    return store.confirm(p['id'],p['hash'])


def test_independent_rename_archive_restore_and_stale_preview(store):
    lid = library(store, '近现代伤寒专著'); sid = add_text(store,lid)
    pid = store.projects.create('桂枝汤证解释')['id']
    folder = store.projects.get(pid)['folder']
    assert len(store.libraries()) == len(store.projects.list()) == 1
    commit(store,'library_update',lid,title='近现代医家著作')
    commit(store,'project_update',pid,title='桂枝汤专题')
    assert store.libraries()[0]['title'] == '近现代医家著作'
    assert store.projects.get(pid)['folder'] == folder
    stale = store.propose('library_update',{'id':lid,'title':'过期名称'})
    commit(store,'library_archive',lid)
    assert not store.libraries() and store.libraries(True)[0]['id'] == lid
    assert store.projects.list()[0]['id'] == pid
    with pytest.raises(Conflict): store.confirm(stale['id'],stale['hash'])
    with pytest.raises(ValueError): store.snapshot([lid])
    with pytest.raises(ValueError): add_text(store,lid,'归档后不能导入')
    assert store.source(sid)['chunks']
    commit(store,'library_restore',lid)
    assert sid in store.snapshot([lid])['source_ids']
    commit(store,'project_archive',pid)
    assert store.libraries() and not store.projects.list()
    with pytest.raises(ValueError): store.projects.require_active(pid)
    assert store.projects.get(pid)['archived'] == 1
    commit(store,'project_restore',pid)
    assert store.projects.require_active(pid)['title'] == '桂枝汤专题'


@pytest.mark.asyncio
@pytest.mark.parametrize('archived', [True, False])
async def test_library_delete_keeps_shared_and_historical_sources(store, archived):
    a,b = library(store,'删除目标'),library(store,'保留知识库')
    cited = add_text(store,a)
    shared = add_text(store,a,'两个知识库共用的著作','共享.txt'); assert add_text(store,b,'两个知识库共用的著作','共享.txt') == shared
    pid = store.projects.create('保留的研究')['id']
    manager = ResearchManager(store,ConversationalModel())
    task = manager.start('解释太阳',store.snapshot([a]),pid)
    await manager.running[task['id']]
    p = manager.propose_save(task['id']); store.confirm(p['id'],p['hash'])
    # 任务固定范围之后新增、无引用的资料可以彻底清理。
    unused = add_text(store,a,'新增且未被研究使用的资料','未使用.txt')
    original = store.root/store.source(unused)['original']
    if archived: commit(store,'library_archive',a)
    deletion = store.propose('library_delete',{'id':a})
    assert deletion['payload']['impact']['sources_deleted'] == 1
    assert deletion['payload']['impact']['sources_retained'] == 2
    store.cancel(deletion['id'])
    assert original.exists()
    deletion = store.propose('library_delete',{'id':a})
    first = store.confirm(deletion['id'],deletion['hash'])
    assert first == store.confirm(deletion['id'],deletion['hash'])
    assert not original.exists()
    with pytest.raises(ValueError): store.source(unused)
    assert store.sources(b)[0]['id'] == shared
    assert store.projects.get(pid)['notes'][0]['evidence'][0]['source_id'] == cited
    assert store.chunk(store.source(cited)['chunks'][0]['id'])['text'].startswith('太阳')
    assert (store.root/store.source(cited)['original']).exists()
    # 已有任务继续时仍沿用固定版本；新的对话不能选用已删除知识库。
    manager.resume(task['id']); await manager.running[task['id']]
    assert store.task(task['id'])['status'] == 'awaiting_review'
    with pytest.raises(ValueError): manager.start('新问题',task['scope'],pid)
    raw = Path(backup(store)['path']).read_bytes(); preview = preview_restore(store,raw)
    restored = restore(store,preview['id'],preview['hash'])
    other = Store(restored['directory'],Path(restored['directory'])/'builtin')
    assert other.projects.get(pid)['notes'] and other.source(cited)['chunks']
    assert other.sources(b)[0]['id'] == shared


@pytest.mark.parametrize('archived', [True, False])
def test_delete_rechecks_new_sharing_and_rolls_back(store, archived):
    a,b = library(store,'A'),library(store,'B'); sid = add_text(store,a)
    if archived: commit(store,'library_archive',a)
    p = store.propose('library_delete',{'id':a})
    add_text(store,b)
    with pytest.raises(Conflict): store.confirm(p['id'],p['hash'])
    assert any(l['id']==a for l in store.libraries(archived))
    assert store.sources(a)[0]['id'] == sid
    assert store.proposal(p['id'])['state'] == 'pending'


@pytest.mark.asyncio
@pytest.mark.parametrize('archived', [True, False])
async def test_delete_project_keeps_independent_library_and_files(store, archived):
    lid = library(store,'原始著作'); sid = add_text(store,lid)
    pid = store.projects.create('待删除研究')['id']; manager = ResearchManager(store,ConversationalModel())
    task = manager.start('解释太阳',store.snapshot([lid]),pid); await manager.running[task['id']]
    note = manager.propose_save(task['id']); store.confirm(note['id'],note['hash'])
    folder = store.projects.folder_path(store.projects.get(pid))
    if archived:
        commit(store,'project_archive',pid)
        with pytest.raises(ValueError): manager.resume(task['id'])
    p = store.propose('project_delete',{'id':pid})
    assert p['payload']['impact']['conversations'] == p['payload']['impact']['notes'] == 1
    store.cancel(p['id'])
    assert folder.exists() and store.task(task['id']) and store.projects.get(pid)['notes']
    stale = store.propose('project_delete',{'id':pid})
    commit(store,'project_update',pid,title='删除前改名')
    with pytest.raises(Conflict): store.confirm(stale['id'],stale['hash'])
    assert folder.exists() and store.task(task['id'])
    p = store.propose('project_delete',{'id':pid})
    result = store.confirm(p['id'],p['hash'])
    assert store.confirm(p['id'],p['hash']) == result
    assert not folder.exists()
    assert store.source(sid)['chunks'] and store.libraries()[0]['id'] == lid
    with pytest.raises(ValueError): store.task(task['id'])
    restarted = Store(store.root,BUILTIN)
    assert not restarted.projects.list(True) and not folder.exists()
    with restarted.connection() as con:
        assert con.execute('SELECT count(*) FROM events').fetchone()[0] == 0
        assert not con.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.asyncio
async def test_unlimited_loop_can_stop_and_busy_archive_is_blocked(store):
    lid = library(store,'长期研读'); add_text(store,lid); pid = store.projects.create('持续研究')['id']
    ready = asyncio.Event()
    class LongModel(ConversationalModel):
        count = 0
        async def complete(self,*args,**kwargs):
            self.count += 1
            if self.count == 11: ready.set()
            await asyncio.sleep(.01)
            return dumps({'queries':['太阳'],'read_ids':[],'finish':False}), {}
    manager = ResearchManager(store,LongModel()); task = manager.start('持续查阅',store.snapshot([lid]),pid)
    await asyncio.wait_for(ready.wait(),timeout=5)
    assert store.task(task['id'])['round'] >= 10
    for kind,key in [('library_archive',lid),('project_archive',pid)]:
        with pytest.raises(ValueError): store.propose(kind,{'id':key})
    await manager.stop(task['id'])
    assert store.task(task['id'])['status'] == 'stopped'
    commit(store,'project_archive',pid)


def test_v2_migration_removes_old_foreign_keys_and_preserves_ids(store):
    lid = library(store,'旧版绑定项目'); sid = add_text(store,lid)
    # 重建真实v2结构：研究专题和任务 project_id 均引用 libraries。
    with store.connection(True) as con:
        con.execute('DROP TABLE research_projects')
        con.execute('CREATE TABLE research_projects(id TEXT PRIMARY KEY REFERENCES libraries(id),folder TEXT NOT NULL,scope TEXT NOT NULL)')
        con.execute('INSERT INTO research_projects VALUES(?,?,?)',(lid,'专题/旧项目-'+lid[:8],dumps({'library_ids':[lid],'builtin':False})))
        con.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
        con.execute('INSERT INTO tasks(id,question,scope,status,created,updated,project_id,draft) VALUES(?,?,?,?,?,?,?,?)',('old','旧问题',dumps({'library_ids':[lid],'source_ids':[sid],'titles':['旧版绑定项目']}),'limited',stamp(),stamp(),lid,dumps({'body':'旧版草稿'})))
    con = sqlite3.connect(store.path)
    con.execute('PRAGMA foreign_keys=OFF')
    for table in ('tasks','notes'):
        sql = con.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]
        sql = sql.replace('REFERENCES research_projects(id)','REFERENCES libraries(id)')
        con.execute('PRAGMA writable_schema=ON')
        con.execute('UPDATE sqlite_master SET sql=? WHERE name=?',(sql,table))
    con.execute('PRAGMA writable_schema=OFF'); con.commit(); con.close()
    new = Store(store.root,BUILTIN)
    assert new.projects.get(lid)['turns'][0]['id'] == 'old'
    assert new.projects.get(lid)['turns'][0]['draft']['body'] == '旧版草稿'
    assert list((store.root/'migrations').glob('*.sqlite'))
    other = new.projects.create('新独立研究')['id']
    with new.connection(True) as con:
        assert con.execute('PRAGMA foreign_key_list(tasks)').fetchone()['table'] == 'research_projects'
        con.execute('INSERT INTO tasks(id,question,scope,status,created,updated,project_id) VALUES(?,?,?,?,?,?,?)',('new','问题','{}','stopped',stamp(),stamp(),other))
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
    assert len(Store(store.root,BUILTIN).libraries()) == 1


def test_archived_api_blocks_new_messages_and_imports(store):
    app = create_app(store.root,BUILTIN,ROOT/'ui'); store = app.state.store
    lid = library(store,'归档知识库'); add_text(store,lid); pid = store.projects.create('归档研究')['id']
    commit(store,'project_archive',pid); commit(store,'library_archive',lid)
    with TestClient(app) as client:
        assert client.get('/api/v1/libraries').json() == []
        assert client.get('/api/v1/projects?archived=true').json()[0]['id'] == pid
        assert client.post('/api/v1/projects/'+pid+'/messages',json={'message':'继续'}).status_code == 400
        assert client.post('/api/v1/search',json={'query':'太阳','library_ids':[lid]}).status_code == 400


def test_delete_transaction_failure_preserves_original(store):
    lid = library(store,'回滚'); sid = add_text(store,lid); original = store.root/store.source(sid)['original']
    p = store.propose('library_delete',{'id':lid})
    with store.connection(True) as con:
        con.execute("CREATE TRIGGER reject_delete BEFORE UPDATE OF deleted ON libraries BEGIN SELECT RAISE(ABORT,'模拟事务失败'); END")
    with pytest.raises(sqlite3.IntegrityError): store.confirm(p['id'],p['hash'])
    assert original.exists() and store.source(sid)['chunks']
    assert store.proposal(p['id'])['state'] == 'pending'
    with store.connection() as con: assert not con.execute('SELECT * FROM cleanup').fetchall()


@pytest.mark.asyncio
async def test_twelve_rounds_produce_validated_answer_and_source(store):
    lid = library(store,'深入研读'); sid = add_text(store,lid)
    pid = store.projects.create('超过八轮')['id']
    class DeepModel(ConversationalModel):
        count = 0
        async def complete(self,messages,*args,**kwargs):
            prompt = json.loads(messages[-1]['content'])
            if 'evidence' in prompt: return await super().complete(messages,*args,**kwargs)
            self.count += 1
            if self.count == 1: return dumps({'queries':['太阳'],'read_ids':[],'finish':False}),{}
            return dumps({'queries':[],'read_ids':[prompt['search_results'][0]['id']],
                'finish':self.count==12,'reason':'第12步完成程序验证所需阅读'}),{}
    manager = ResearchManager(store,DeepModel()); task = manager.start('深入核对太阳病',store.snapshot([lid]),pid)
    await asyncio.wait_for(manager.running[task['id']],timeout=10)
    result = store.task(task['id'])
    assert result['round'] == 12 and result['status'] == 'awaiting_review'
    assert result['draft']['evidence'][0]['source_id'] == sid
    assert '汗出恶风' in result['draft']['body']


def test_edit_shared_source_keeps_archived_membership(store):
    a,b = library(store,'归档著作库'),library(store,'正在整理的著作库')
    sid = add_text(store,a); assert add_text(store,b) == sid
    commit(store,'library_archive',a)
    p = store.propose('source_update',{'id':sid,'title':'核对后的书名','library_ids':[b]})
    assert '保留原关联' in p['payload']['library_titles'][a]
    store.confirm(p['id'],p['hash'])
    assert set(store.source(sid)['library_ids']) == {a,b}
    assert store.sources(a)[0]['title'] == '核对后的书名'


@pytest.mark.asyncio
async def test_invalid_model_action_stops_instead_of_repeating(store):
    lid = library(store,'模型格式失败'); add_text(store,lid)
    class Invalid(ConversationalModel):
        async def complete(self,*args,**kwargs): return '{}',{}
    manager = ResearchManager(store,Invalid()); task = manager.start('格式验证',store.snapshot([lid]))
    await asyncio.wait_for(manager.running[task['id']],timeout=3)
    assert store.task(task['id'])['status'] == 'failed'
