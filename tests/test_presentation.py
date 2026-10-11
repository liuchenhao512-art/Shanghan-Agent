"""验证新回复的引用边界，以及旧对话显示清理不改写正式记录。"""
import json
import pytest
from test_core import store, seed, library, add_text, BUILTIN
from test_rag import Model, run
from server.answers import validate_draft, conversation_body
from server.storage import Store, dumps


def test_no_placeholder_or_banner_and_only_valid_references():
    e={'id':'chunk1','source_id':'source1','evidence_id':'E001','text':'太阳病，汗出恶风。',
       'title':'测试著作','author':'测试作者','locator':'第1段'}
    draft=validate_draft('说明',{'general_answer':'一般认识[E001][E404]。〔未核验引用〕',
        'answer':[{'text':'有据分析[E404]','citations':[{'evidence_id':'E001','quote':'汗出恶风'}]},
                  {'text':'伪造结论','citations':[{'evidence_id':'E404','quote':'不存在'}]}]},[e])
    assert draft['general_answer']=='一般认识。'
    assert '[E404]' not in draft['body'] and '未核验引用' not in draft['body']
    assert '未经本库原文核验' not in draft['body'] and '伪造结论' not in draft['body']
    assert len(draft['evidence'])==1 and draft['evidence'][0]['quote']=='汗出恶风'
    assert '## 参考资料' in draft['body'] and '其余内容为AI分析' in draft['body']
    shown=conversation_body(draft)
    assert '有据分析 [E001]' in shown and '### [E001]' not in shown


@pytest.mark.asyncio
async def test_old_chat_clean_view_preserves_draft_notes_and_citations(store):
    lid=library(store,'历史资料');sid=add_text(store,lid)
    pid=store.projects.create('旧版对话')['id']
    _,task=await run(store,Model(lambda p:{'finish':True,'general_answer':'测试回复'}),'问题',store.snapshot([lid]),pid)
    ch=store.chunk(store.source(sid)['chunks'][0]['id'])
    e={**ch,'evidence_id':'E001','quote':'汗出恶风'}
    raw='# 问题\n\n> 模型自身知识与分析 · 未经本库原文核验\n\n一般分析〔未核验引用〕[E777]。\n\n> 基于本轮知识库原文的分析 · 引文已核对，论断与证据的关系仍需人工审阅\n\n有据分析 [E001]\n\n## 原文与出处\n\n### [E001] 测试资料\n\n> 汗出恶风\n'
    draft={'body':raw,'evidence':[e],'basis':'mixed'}
    store.update_task(task['id'],draft=draft)
    p=store.propose('note_save',{'title':'旧笔记','body':raw,'evidence':[e],'task_id':task['id']})
    store.confirm(p['id'],p['hash'])
    shown=store.projects.get(pid)['turns'][0]
    assert '未核验引用' not in shown['html'] and '模型自身知识与分析' not in shown['html']
    assert '基于本轮知识库原文的分析' not in shown['html'] and '[E777]' not in shown['html']
    assert '[E001]' in shown['html'] and '有据分析' in shown['html']
    assert shown['draft']==draft and store.task(task['id'])['draft']['body']==raw
    assert store.notes()[0]['body']==raw
    assert '未核验引用' not in store.projects.history(pid)[1]['content']
    restarted=Store(store.root,BUILTIN)
    assert restarted.task(task['id'])['draft']['body']==raw and restarted.notes()[0]['body']==raw
    assert restarted.projects.get(pid)['turns'][0]['html']==shown['html']


@pytest.mark.asyncio
async def test_new_library_import_and_multi_library_chat_scope(store):
    a=store.create_library('新建资料库A')['id'];b=store.create_library('新建资料库B')['id']
    assert not store.snapshot([a],allow_empty=True)['source_ids']
    sa=add_text(store,a,'泽漆甲库原文，只在甲库出现。','甲.txt')
    sb=add_text(store,b,'泽漆乙库原文，只在乙库出现。','乙.txt')
    def reply(p):
        if 'evidence' not in p:return {'queries':['泽漆'],'finish':True}
        return {'answer':[{'text':'本轮所选库的资料','citations':[
            {'evidence_id':e['evidence_id'],'quote':e['text']} for e in p['evidence']]}]}
    _,one=await run(store,Model(reply),'查泽漆',store.snapshot([a]))
    _,both=await run(store,Model(reply),'查泽漆',store.snapshot([a,b]))
    assert {e['source_id'] for e in one['draft']['evidence']}=={sa}
    assert {e['source_id'] for e in both['draft']['evidence']}=={sa,sb}
