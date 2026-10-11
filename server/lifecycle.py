"""知识库和研究专题的独立生命周期；预览绑定依赖，删除保留历史证据。"""
import json
import shutil
from pathlib import Path
from .storage import Conflict, digest, dumps

KINDS = {prefix+'_'+action for prefix in ('library','project') for action in ('update','archive','restore','delete')}


class Lifecycle:
    def __init__(self, store):
        self.store = store
        with store.connection(True) as con:
            con.execute('CREATE TABLE IF NOT EXISTS cleanup(path TEXT PRIMARY KEY,kind TEXT NOT NULL)')
        self.clean_files()

    def assert_idle(self, con, kind, key):
        for row in con.execute("SELECT project_id,scope FROM tasks WHERE status IN ('running','stopping')"):
            if (kind.startswith('project_') and row['project_id'] == key) or (
                kind.startswith('library_') and key in json.loads(row['scope']).get('library_ids', [])):
                raise ValueError('相关研读正在运行，请先停止或等待完成')

    def referenced_sources(self, con):
        used = set()
        for row in con.execute('SELECT scope,evidence FROM tasks'):
            # 保留固定范围的全部正文，保证历史任务主动继续时仍可复现。
            used.update(json.loads(row['scope']).get('source_ids', []))
            used.update(e['source_id'] for e in json.loads(row['evidence']) if e.get('source_id'))
        for row in con.execute('SELECT evidence FROM notes'):
            for e in json.loads(row[0]):
                if e.get('source_id'):
                    used.add(e['source_id'])
                elif e.get('id'):
                    ch = con.execute('SELECT source_id FROM chunks WHERE id=?',(e['id'],)).fetchone()
                    if ch: used.add(ch[0])
        return used

    def impact(self, con, kind, key):
        if kind == 'project_delete':
            tasks = [dict(r) for r in con.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY id',(key,))]
            notes = [dict(r) for r in con.execute('SELECT * FROM notes WHERE project_id=? ORDER BY id',(key,))]
            return {'conversations':len(tasks),'notes':len(notes),'sources_deleted':0,
                    'message':'删除本专题全部对话、草稿、笔记及专题文件夹；引用的独立知识库和原始资料保留。',
                    'dependency_hash':digest([tasks,notes])}
        used = self.referenced_sources(con)
        rows = []
        for source in con.execute('SELECT s.* FROM sources s JOIN membership m ON s.id=m.source_id WHERE m.library_id=? ORDER BY s.id',(key,)):
            shared = [r[0] for r in con.execute('SELECT m.library_id FROM membership m JOIN libraries l ON l.id=m.library_id WHERE source_id=? AND l.id<>? AND l.deleted=0 ORDER BY l.id',(source['id'],key))]
            reason = '其他知识库共用' if shared else '历史引用或研读范围需要' if source['id'] in used else ''
            rows.append({'id':source['id'],'title':source['title'],'revision':source['revision'],'shared':shared,'retained':bool(reason),'reason':reason})
        return {'sources':rows,'sources_deleted':sum(not s['retained'] for s in rows),
                'sources_retained':sum(s['retained'] for s in rows),
                'message':'删除知识库及不再使用的资料；其他库共用资料、核对历史引用与继续历史研读所需原文保留。',
                'dependency_hash':digest(rows)}

    def prepare(self, con, kind, payload, guard):
        table = 'libraries' if kind.startswith('library_') else 'research_projects'
        row = guard(table, payload['id'])
        action = kind.split('_',1)[1]
        if action != 'update':
            self.assert_idle(con,kind,payload['id'])
        # 知识库和研究专题均可直接预览删除；恢复操作仍仅适用于归档项。
        if action == 'restore' and not row['archived']:
            raise ValueError('请先归档，再从已归档列表中操作')
        if action == 'archive' and row['archived']:
            raise ValueError('该项目已经归档')
        payload = {**payload,'previous':{'title':row['title']}}
        if action == 'delete':
            payload['impact'] = self.impact(con,kind,payload['id'])
        return payload

    def apply(self, con, kind, payload):
        table = 'libraries' if kind.startswith('library_') else 'research_projects'
        action, key = kind.split('_',1)[1], payload['id']
        if action != 'update': self.assert_idle(con,kind,key)
        if action == 'delete':
            if self.impact(con,kind,key) != payload['impact']:
                raise Conflict('删除范围或引用已发生变化，请重新预览')
            if table == 'research_projects':
                folder = con.execute('SELECT folder FROM research_projects WHERE id=?',(key,)).fetchone()[0]
                con.execute('INSERT OR IGNORE INTO cleanup VALUES(?,?)',(folder,'project'))
                con.execute('DELETE FROM events WHERE task_id IN (SELECT id FROM tasks WHERE project_id=?)',(key,))
                con.execute('DELETE FROM notes WHERE project_id=?',(key,))
                con.execute('DELETE FROM tasks WHERE project_id=?',(key,))
            else:
                con.execute('DELETE FROM membership WHERE library_id=?',(key,))
                for source in payload['impact']['sources']:
                    if source['shared']: continue
                    if source['retained']:
                        con.execute('UPDATE sources SET deleted=1,revision=revision+1 WHERE id=?',(source['id'],))
                    else:
                        self.purge_source(con,source['id'])
            con.execute('UPDATE '+table+' SET deleted=1,revision=revision+1 WHERE id=?',(key,))
        elif action == 'update':
            con.execute('UPDATE '+table+' SET title=?,revision=revision+1 WHERE id=?',(payload['title'].strip(),key))
        else:
            con.execute('UPDATE '+table+' SET archived=?,revision=revision+1 WHERE id=?',(int(action=='archive'),key))

    def purge_source(self, con, sid):
        row = con.execute('SELECT original FROM sources WHERE id=? AND builtin=0',(sid,)).fetchone()
        if not row: return
        original = row[0]
        con.execute('DELETE FROM membership WHERE source_id=?',(sid,))
        con.execute('DELETE FROM chunk_fts WHERE chunk_id IN (SELECT id FROM chunks WHERE source_id=?)',(sid,))
        con.execute('DELETE FROM chunks WHERE source_id=?',(sid,))
        con.execute('DELETE FROM sources WHERE id=?',(sid,))
        if original and not con.execute('SELECT 1 FROM sources WHERE original=?',(original,)).fetchone():
            con.execute('INSERT OR IGNORE INTO cleanup VALUES(?,?)',(original,'original'))

    def clean_files(self):
        # 文件删除在事务提交后执行。失败保留队列，下次启动重试，避免回滚时丢原件。
        with self.store.connection(True) as con:
            for row in con.execute('SELECT * FROM cleanup').fetchall():
                raw = self.store.root/row['path']
                target = raw.resolve()
                base = self.store.root/('专题' if row['kind']=='project' else 'originals')
                if target == base or not target.is_relative_to(base) or any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in [raw,*raw.parents] if p != self.store.root and p.is_relative_to(self.store.root)):
                    continue
                try:
                    if row['kind']=='project' and target.is_dir(): shutil.rmtree(target)
                    elif target.is_file(): target.unlink()
                    con.execute('DELETE FROM cleanup WHERE path=?',(row['path'],))
                except OSError:
                    continue
