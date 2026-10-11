"""复现实际组合词漏检，并核对正常对话、按需检索和引用边界。"""
import asyncio
import json
from pathlib import Path
import pytest
from test_core import store, seed, library, add_text, BUILTIN, ROOT
from server.storage import Store, dumps
from server.research import ResearchManager, validate_draft
from server.exports import markdown_bundle, backup, preview_restore, restore
from server.app import create_app
from fastapi.testclient import TestClient


class Model:
    def __init__(self, reply): self.reply, self.inputs = reply, []
    def config(self): return {'configured':True}
    async def complete(self, messages, *args, **kwargs):
        prompt = json.loads(messages[-1]['content']); self.inputs.append(prompt)
        reply = self.reply(prompt)
        return (reply if isinstance(reply,str) else dumps(reply)), {}


async def run(store, model, question, scope, pid=None):
    manager = ResearchManager(store,model)
    task = manager.start(question,scope,pid)
    await asyncio.wait_for(manager.running[task['id']],timeout=15)
    return manager,store.task(task['id'])


@pytest.mark.parametrize('query', ['桂枝汤 注家 阐释','伤寒论 太阳病 提纲','桂枝湯'])
def test_actual_failed_queries_now_cover_nine_commentators(store, query):
    scope = store.snapshot([],True)
    result = store.search(query,scope,12)
    assert len(result) == 12
    assert len({r['author'] for r in result if r['author']}) == 9
    assert all(r['source_id'] in scope['source_ids'] for r in result)
    assert all(any(word in store.cc.convert(r['text']).lower() for word in r['matched_terms']) for r in result)


def test_author_target_pagination_and_short_terms(store):
    scope = store.snapshot([],True)
    first = store.search('成无己 桂枝汤',scope,12)
    second = store.search('成无己 桂枝汤',scope,12,12)
    assert first and second and {r['author'] for r in first+second} == {'成无己'}
    assert not ({r['id'] for r in first} & {r['id'] for r in second})
    assert store.search('太阳',scope)
    assert {r['id'] for r in store.search('桂枝湯',scope)} == {r['id'] for r in store.search('桂枝汤',scope)}


def test_fallback_is_scoped_and_never_searches_ai_notes(store):
    a,b = library(store,'A'),library(store,'B')
    sid = add_text(store,a,'太阳病，所选知识库原文。')
    add_text(store,b,'太阳病，范围外的秘密材料。')
    scope = store.snapshot([a])
    p = store.propose('note_save',{'title':'AI旧结论','body':'太阳病，独立原文中没有的标记。','evidence':[]})
    store.confirm(p['id'],p['hash'])
    assert {r['source_id'] for r in store.search('太阳病 注家 阐释',scope)} == {sid}
    assert not store.search('范围外的秘密材料',scope)
    assert not store.search('独立原文中没有的标记',scope)


@pytest.mark.asyncio
async def test_plain_chat_empty_scope_history_save_restart_and_backup(store):
    scope = store.snapshot([],False,allow_empty=True)
    pid = store.projects.create('正常对话')['id']
    model = Model(lambda p: {'queries':[],'read_ids':[],'finish':True,'general_answer':'你好，可以一起讨论研究思路。'})
    manager,first = await run(store,model,'你好',scope,pid)
    assert first['status']=='awaiting_review' and first['draft']['basis']=='model' and not first['evidence']
    assert len(model.inputs)==1 and '本次未引用知识库资料' in first['draft']['body']
    _,second = await run(store,model,'继续刚才的话题',scope,pid)
    assert model.inputs[-1]['conversation'][0]['content']=='你好'
    p = manager.propose_save(first['id']); result = store.confirm(p['id'],p['hash'])
    note = next(n for n in store.notes() if n['id']==result['id'])
    exported = markdown_bundle(store,note)
    assert '本次未引用知识库资料' in Path(exported['markdown_path']).read_text('utf-8')
    restarted = Store(store.root,BUILTIN)
    assert len(restarted.projects.get(pid)['turns'])==2
    preview = preview_restore(restarted,Path(backup(restarted)['path']).read_bytes())
    restored = restore(restarted,preview['id'],preview['hash'])
    other = Store(restored['directory'],Path(restored['directory'])/'builtin')
    assert other.projects.get(pid)['notes'][0]['body']==note['body']
    assert not other.projects.get(pid)['turns'][0]['evidence']


@pytest.mark.asyncio
async def test_zero_hits_still_calls_model_for_answer(store):
    scope = store.snapshot([],True)
    def reply(p):
        if 'evidence' in p:
            assert p['evidence']==[] and p['retrieval']['searched']
            return {'general_answer':'可以先从研究对象、问题和验证方法三方面梳理思路。'}
        return {'queries':['程序测试完全不存在词语XYZ739'],'read_ids':[],'finish':True}
    model = Model(reply);_,result = await run(store,model,'怎样梳理研究思路',scope)
    assert result['status']=='awaiting_review' and result['draft']['basis']=='model'
    assert len(model.inputs)==2 and '梳理思路' in result['draft']['body']
    assert '尚未获得可核对的原文证据，请补充资料或调整检索问题' not in result['draft']['body']
    assert '不能据此判断' in result['draft']['body'] and not result['draft']['evidence']


@pytest.mark.asyncio
async def test_finish_with_queries_reads_multiple_authors_and_mixes_answer(store):
    def reply(p):
        if 'evidence' not in p:
            return {'queries':['桂枝汤 注家 阐释'],'read_ids':[],'finish':True}
        assert len({e['author'] for e in p['evidence'] if e['author']})==9
        return {'general_answer':'比较时可以关注证候、病机和方药解释三个维度。',
                'answer':[{'text':'本次实际取回的原文片段如下，需继续核对解释。',
                    'citations':[{'evidence_id':e['evidence_id'],'quote':e['text'][:24]} for e in p['evidence']]}]}
    _,result = await run(store,Model(reply),'各家如何解释桂枝汤',store.snapshot([],True))
    assert result['status']=='awaiting_review' and result['draft']['basis']=='mixed'
    assert len(result['draft']['evidence'])==12
    for e in result['draft']['evidence']:
        assert e['quote'] in store.chunk(e['id'])['text']


@pytest.mark.asyncio
async def test_catalogue_question_uses_metadata_without_body_search(store):
    def reply(p):
        if 'evidence' in p:
            return {'catalogue_ids':[b['id'] for b in p['catalogue']]}
        assert p['catalogue_total']==20
        return {'queries':[],'read_ids':[],'show_catalogue':True,'finish':True}
    _,result = await run(store,Model(reply),'内置经典知识库包含哪些内容',store.snapshot([],True))
    assert result['status']=='awaiting_review' and result['draft']['basis']=='catalogue'
    assert len(result['draft']['catalogue'])==20 and not result['draft']['evidence']
    assert '伤寒论基准条文' in result['draft']['body'] and '教材解析汇编' in result['draft']['body']
    assert not any(e['event']=='search' for e in store.events(result['id']))


@pytest.mark.asyncio
async def test_model_targeted_source_cannot_escape_selected_scope(store):
    a,b = library(store,'所选库'),library(store,'未选库')
    sid = add_text(store,a); outside = add_text(store,b,'未选知识库独有原文。')
    model = Model(lambda p:{'queries':[{'query':'太阳','source_ids':[outside]}],'read_ids':[],'finish':True})
    _,result = await run(store,model,'查阅原文',store.snapshot([a]))
    assert result['status']=='failed' and not result['evidence']
    assert '范围之外' in result['error']


def test_invalid_quotes_are_not_laundered_as_general_answer(store):
    scope = store.snapshot([],True);ch=store.search('桂枝汤',scope)[0]
    evidence = [{**ch,'evidence_id':'E001'}]
    draft = validate_draft('问题',{'general_answer':'一般讨论[E999]。',
        'answer':[{'text':'伪造的注家判断','citations':[{'evidence_id':'E001','quote':'原文里没有的这句话XYZ'}]}],
        'catalogue_ids':['outside']},evidence,scope['catalogue'])
    assert '伪造的注家判断' not in draft['body'] and '[E999]' not in draft['body']
    assert draft['warnings'] and not draft['evidence'] and not draft['catalogue']
    assert '一般讨论' in draft['body'] and '本次未引用知识库资料' in draft['body']


@pytest.mark.asyncio
async def test_plain_text_compatible_service_stays_unverified(store):
    _,result=await run(store,Model(lambda p:'你好，我们可以继续讨论这个专题。[E001]'), '你好',store.snapshot([],True))
    assert result['status']=='awaiting_review' and result['draft']['basis']=='model'
    assert not result['draft']['evidence'] and '[E001]' not in result['draft']['body']


@pytest.mark.asyncio
async def test_api_failure_and_stop_keep_state_without_fake_answer(store):
    class Broken(Model):
        async def complete(self,*args,**kwargs): raise ValueError('模型服务返回 HTTP 503')
    manager,result=await run(store,Broken(None),'你好',store.snapshot([],False,allow_empty=True))
    assert result['status']=='failed' and '503' in result['error'] and not result['draft'].get('general_answer')
    class Slow(Model):
        async def complete(self,*args,**kwargs): await asyncio.sleep(60)
    manager=ResearchManager(store,Slow(None));task=manager.start('停止对话',store.snapshot([],False,allow_empty=True))
    await asyncio.sleep(.02);await manager.stop(task['id'])
    assert store.task(task['id'])['status']=='stopped'


def test_empty_scope_chat_endpoint_reaches_model_configuration(store):
    app=create_app(store.root,BUILTIN,ROOT/'ui')
    with TestClient(app) as client:
        pid=client.post('/api/v1/projects',json={'title':'普通对话'}).json()['id']
        r=client.post('/api/v1/projects/'+pid+'/messages',json={'message':'你好','scope':{'library_ids':[],'builtin':False}})
        assert r.status_code==400 and '配置在线模型' in r.text and '没有可检索' not in r.text
