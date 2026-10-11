"""本地存储、不可变来源及确认提案。正式变更统一在事务中完成。"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import sqlite3
import threading
import time
import uuid
import re
from opencc import OpenCC

def uid():
    return uuid.uuid4().hex

def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else dumps(value).encode()).hexdigest()

class Conflict(ValueError):
    pass

class Store:
    def __init__(self, directory, builtin):
        self.root = Path(directory).resolve()
        self.builtin = Path(builtin).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for child in ('originals', 'staging', 'exports'):
            (self.root / child).mkdir(exist_ok=True)
        self.path = self.root / 'personal.sqlite'
        self.lock = threading.RLock()
        self.cc = OpenCC('t2s')
        with self.connection() as con:
            con.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS libraries(id TEXT PRIMARY KEY,title TEXT NOT NULL,revision INTEGER DEFAULT 1,deleted INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,title TEXT,author TEXT,kind TEXT,origin TEXT,sha256 TEXT,metadata TEXT,original TEXT,revision INTEGER DEFAULT 1,deleted INTEGER DEFAULT 0,builtin INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS membership(library_id TEXT REFERENCES libraries(id),source_id TEXT REFERENCES sources(id),PRIMARY KEY(library_id,source_id));
            CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,source_id TEXT REFERENCES sources(id),ordinal INTEGER,locator TEXT,text TEXT,normalized TEXT);
            CREATE INDEX IF NOT EXISTS chunk_source ON chunks(source_id,ordinal);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(chunk_id UNINDEXED,body,tokenize='trigram');
            CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,kind TEXT,payload TEXT,guards TEXT,hash TEXT,state TEXT,created TEXT,result TEXT);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,question TEXT,scope TEXT,status TEXT,round INTEGER DEFAULT 0,evidence TEXT DEFAULT '[]',draft TEXT DEFAULT '{}',error TEXT DEFAULT '',created TEXT,updated TEXT);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event TEXT,data TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY,title TEXT,body TEXT,evidence TEXT,task_id TEXT,revision INTEGER DEFAULT 1,deleted INTEGER DEFAULT 0,created TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS note_task ON notes(task_id) WHERE task_id IS NOT NULL AND deleted=0;
            INSERT OR IGNORE INTO meta VALUES('schema_version','1');
            ''')
            con.execute("UPDATE tasks SET status='interrupted',updated=? WHERE status IN ('running','stopping')", (stamp(),))
        self._seed_builtin()
        from .migration import migrate_projects
        migrate_projects(self)
        from .lifecycle import Lifecycle
        self.lifecycle = Lifecycle(self)
        from .projects import ProjectWorkspace
        self.projects = ProjectWorkspace(self)

    @contextmanager
    def connection(self, write=False):
        with self.lock:
            con = sqlite3.connect(self.path, timeout=30)
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            try:
                if write:
                    con.execute('BEGIN IMMEDIATE')
                yield con
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()

    def _seed_builtin(self):
        version = digest((self.builtin / 'kb.sqlite').read_bytes())[:16]
        self.corpus_version = version
        with self.connection() as con:
            if con.execute('SELECT 1 FROM meta WHERE key=?', ('builtin:' + version,)).fetchone():
                return
        legacy = sqlite3.connect((self.builtin / 'kb.sqlite').as_uri() + '?mode=ro', uri=True)
        legacy.row_factory = sqlite3.Row
        with self.connection(True) as con:
            # 内置来源版本化，旧引用仍可解析；检索只使用当前内置版本。
            records = [('passages', '伤寒论基准条文', '', '经典原文')]
            records += [('comment:' + r['name'], r['book'] + '·逐条注文', r['name'], '注家观点') for r in legacy.execute('SELECT * FROM commentators ORDER BY seq')]
            records += [('book:' + r['book_id'], r['book_name'], r['author'], '注家原书') for r in legacy.execute('SELECT * FROM origbooks ORDER BY seq')]
            records += [('textbook', '教材解析汇编', '', '教材解读')]
            for key, title, author, category in records:
                sid = 'builtin:' + version + ':' + key
                con.execute('INSERT INTO sources(id,title,author,kind,origin,sha256,metadata,original,builtin) VALUES(?,?,?,?,?,?,?,?,1)',
                            (sid,title,author,'builtin',category,version,dumps({'category':category,'corpus_version':version}),''))
                if key == 'passages':
                    rows = [(r['num'], f"第{r['num']}条·{r['chapter']}", r['text']) for r in legacy.execute('SELECT * FROM passages ORDER BY seq')]
                elif key.startswith('comment:'):
                    rows = [(r['id'], f"第{r['passage_num']}条·段{r['segment'] or 1}·{r['flag'] or '既有对齐'}", r['text']) for r in legacy.execute('SELECT * FROM comments WHERE commentator=? ORDER BY seq',(author,))]
                elif key.startswith('book:'):
                    rows = [(r['gseq'], f"{r['chap_title']}·段{r['para_idx']+1}",r['text']) for r in legacy.execute('SELECT * FROM origpara WHERE book_id=? ORDER BY gseq',(key[5:],))]
                else:
                    tb = json.loads((self.builtin / 'parsed/textbook_notes.json').read_text(encoding='utf-8'))
                    rows = [(int(n),f"第{n}条·{v.get('source','来源待核')}",'\n'.join(v.get(k,'') for k in ('tiyao','jiexi','bingji','zhifa') if isinstance(v.get(k,''),str))) for n,v in tb.items()]
                self._add_chunks(con,sid,[{'ordinal': n,'locator':loc,'text':t} for n,loc,t in rows])
            con.execute('INSERT INTO meta VALUES(?,?)', ('builtin:' + version, stamp()))
        legacy.close()

    def _add_chunks(self, con, source_id, chunks):
        for i, item in enumerate(chunks):
            cid = source_id + ':' + str(i)
            normalized = self.cc.convert(item['text'])
            con.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?)',(cid,source_id,item.get('ordinal',i+1),item['locator'],item['text'],normalized))
            con.execute('INSERT INTO chunk_fts(chunk_id,body) VALUES(?,?)',(cid,normalized))

    def create_library(self, title, request_id=None):
        title = str(title).strip()
        if not title or len(title) > 120:
            raise ValueError('知识库名称应为1至120字')
        key = request_id or uid()
        if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key):
            raise ValueError('创建标识无效，请重新打开新建窗口')
        with self.connection(True) as con:
            old = con.execute('SELECT * FROM libraries WHERE id=?',(key,)).fetchone()
            if old and (old['deleted'] or old['archived'] or old['title'] != title):
                raise ValueError('此创建请求已经使用，请重新发起')
            if not old:
                con.execute('INSERT INTO libraries(id,title) VALUES(?,?)',(key,title))
            return dict(con.execute('SELECT * FROM libraries WHERE id=?',(key,)).fetchone())

    def libraries(self, archived=False):
        with self.connection() as con:
            return [dict(r) for r in con.execute('SELECT l.*,COUNT(s.id) AS source_count FROM libraries l LEFT JOIN membership m ON m.library_id=l.id LEFT JOIN sources s ON s.id=m.source_id AND s.deleted=0 WHERE l.deleted=0 AND l.archived=? GROUP BY l.id ORDER BY l.rowid',(int(archived),))]

    def sources(self, library_id=None, include_builtin=False):
        with self.connection() as con:
            sql = 'SELECT DISTINCT s.* FROM sources s'
            args = []
            if library_id:
                sql += ' JOIN membership m ON m.source_id=s.id WHERE m.library_id=? AND s.deleted=0'
                args.append(library_id)
            else:
                sql += ' WHERE s.deleted=0 AND s.builtin=?'
                args.append(1 if include_builtin else 0)
            if include_builtin:
                sql += ' AND s.sha256=?'
                args.append(self.corpus_version)
            return [{**dict(r),'metadata':json.loads(r['metadata'])} for r in con.execute(sql+' ORDER BY s.rowid',args)]

    def snapshot(self, library_ids, builtin=False, allow_empty=False):
        with self.connection() as con:
            ids = []
            titles = []
            for lid in dict.fromkeys(library_ids):
                library = con.execute('SELECT * FROM libraries WHERE id=? AND deleted=0 AND archived=0',(lid,)).fetchone()
                if not library:
                    raise ValueError('所选知识库已归档、删除或不存在，请恢复后再选用')
                titles.append(library['title'])
                ids += [r[0] for r in con.execute('SELECT s.id FROM membership m JOIN sources s ON s.id=m.source_id WHERE m.library_id=? AND s.deleted=0',(lid,))]
            if builtin:
                ids += [r[0] for r in con.execute('SELECT id FROM sources WHERE builtin=1 AND sha256=?',(self.corpus_version,))]
                titles.append('内置经典知识库')
            if not ids and not allow_empty:
                raise ValueError('所选范围没有可检索的资料，请先导入或选择内置知识库')
            scope = {'library_ids':library_ids,'titles':titles,'builtin':builtin,'source_ids':sorted(set(ids)),'created':stamp()}
        scope['catalogue'] = self.catalogue(scope)
        return scope

    def catalogue(self, scope):
        from .retrieval import catalogue
        return catalogue(self,scope)

    def search(self, query, scope, limit=30, offset=0):
        from .retrieval import search
        return search(self,query,scope,limit,offset)

    def chunk(self, chunk_id, scope=None):
        with self.connection() as con:
            row = con.execute('SELECT c.*,s.title,s.author,s.origin FROM chunks c JOIN sources s ON s.id=c.source_id WHERE c.id=?',(chunk_id,)).fetchone()
            if not row or (scope is not None and row['source_id'] not in scope['source_ids']):
                raise ValueError('引用不在本次资料范围内或不存在')
            return dict(row)

    def source(self, source_id):
        with self.connection() as con:
            row = con.execute('SELECT * FROM sources WHERE id=?',(source_id,)).fetchone()
            if not row:
                raise ValueError('资料不存在')
            result = dict(row)
            result['metadata'] = json.loads(result['metadata'])
            result['chunks'] = [dict(r) for r in con.execute('SELECT id,ordinal,locator,text FROM chunks WHERE source_id=? ORDER BY ordinal',(source_id,))]
            result['library_ids'] = [r[0] for r in con.execute('SELECT library_id FROM membership WHERE source_id=?',(source_id,))]
            return result

    def propose(self, kind, payload):
        from .lifecycle import KINDS
        permitted = KINDS | {'library_create','import','source_update','source_delete','note_save','note_update','note_delete'}
        if kind not in permitted:
            raise ValueError('不支持的管理操作')
        guards = []
        with self.connection() as con:
            def guard(table, key):
                row = con.execute(f'SELECT * FROM {table} WHERE id=? AND deleted=0',(key,)).fetchone()
                if not row:
                    raise ValueError('操作目标不存在或已删除')
                if table == 'sources' and row['builtin']:
                    raise ValueError('内置资料只读')
                guards.append([table,key,row['revision']])
                return row
            if kind in KINDS:
                payload = self.lifecycle.prepare(con,kind,payload,guard)
            if kind in ('source_update','source_delete'):
                row = guard('sources',payload['id'])
                payload = dict(payload)
                payload['previous'] = {'title':row['title'],'author':row['author']}
                if kind == 'source_update':
                    payload['author'] = payload.get('author',row['author'])
                    payload['metadata'] = {**json.loads(row['metadata']),**payload.get('metadata',{})}
            if kind in ('note_update','note_delete'):
                row = guard('notes',payload['id'])
                payload = {**payload,'previous':{'title':row['title']}}
                if kind == 'note_update':
                    payload['evidence'] = payload.get('evidence',json.loads(row['evidence']))
            if kind in ('import','source_update'):
                preserved_archived = set()
                if kind == 'source_update':
                    preserved_archived = {r[0] for r in con.execute('SELECT l.id FROM libraries l JOIN membership m ON l.id=m.library_id WHERE m.source_id=? AND l.archived=1 AND l.deleted=0',(payload['id'],))}
                    payload['library_ids'] = list(dict.fromkeys([*payload.get('library_ids',[]),*sorted(preserved_archived)]))
                payload['library_titles'] = {}
                if not payload.get('library_ids'):
                    raise ValueError('至少选择一个目标知识库')
                for lid in payload['library_ids']:
                    library = guard('libraries',lid)
                    payload['library_titles'][lid] = library['title'] + ('（已归档，保留原关联）' if lid in preserved_archived else '')
                    if library['archived'] and lid not in preserved_archived:
                        raise ValueError('请先恢复已归档的知识库，再导入或调整资料')
            if kind.endswith('_create') or kind in ('library_update','project_update','source_update','note_save','note_update'):
                if not str(payload.get('title','')).strip():
                    raise ValueError('标题不能为空')
                if kind in ('library_create','library_update','project_update') and len(str(payload.get('title',''))) > 120:
                    raise ValueError('标题最多120字')
        pid = uid()
        h = digest({'kind':kind,'payload':payload,'guards':guards})
        with self.connection(True) as con:
            con.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?)',(pid,kind,dumps(payload),dumps(guards),h,'pending',stamp(),None))
        return self.proposal(pid)

    def proposal(self, pid):
        with self.connection() as con:
            row = con.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
            if not row:
                raise ValueError('预览已不存在')
            return {**dict(row),'payload':json.loads(row['payload']),'guards':json.loads(row['guards']),'result':json.loads(row['result']) if row['result'] else None}

    def cancel(self, pid):
        with self.connection(True) as con:
            con.execute("UPDATE proposals SET state='cancelled' WHERE id=? AND state='pending'",(pid,))
        return self.proposal(pid)

    def confirm(self, pid, preview_hash):
        from .lifecycle import KINDS
        with self.connection(True) as con:
            row = con.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
            if not row or row['hash'] != preview_hash:
                raise Conflict('确认内容与预览不一致，请重新预览')
            if row['state'] == 'committed':
                return json.loads(row['result'])
            if row['state'] != 'pending':
                raise Conflict('该方案已取消或失效')
            for table, key, revision in json.loads(row['guards']):
                current = con.execute(f'SELECT revision,deleted FROM {table} WHERE id=?',(key,)).fetchone()
                if not current or current['deleted'] or current['revision'] != revision:
                    raise Conflict('资料已发生变化，请重新生成预览')
            p = json.loads(row['payload'])
            kind = row['kind']
            result = {'id':p.get('id',uid()),'kind':kind}
            key = result['id']
            if kind == 'library_create':
                con.execute('INSERT INTO libraries(id,title) VALUES(?,?)',(key,p['title'].strip()))
            elif kind in KINDS:
                self.lifecycle.apply(con,kind,p)
            elif kind == 'import':
                existing = con.execute('SELECT id FROM sources WHERE sha256=? AND builtin=0 AND deleted=0',(p['sha256'],)).fetchone()
                if existing:
                    key = result['id'] = existing[0]
                    result['reused'] = True
                else:
                    key = result['id'] = p['source_id']
                    original = self.root / p['original']
                    if not original.is_file() or digest(original.read_bytes()) != p['sha256']:
                        raise Conflict('暂存原文件缺失或发生变化，请重新导入')
                    if not p['chunks']:
                        raise ValueError('没有可用正文，无法正式入库')
                    con.execute('INSERT INTO sources(id,title,author,kind,origin,sha256,metadata,original) VALUES(?,?,?,?,?,?,?,?)',
                                (key,p['title'],p.get('author',''),p['format'],p.get('origin',''),p['sha256'],dumps(p.get('metadata',{})),p['original']))
                    self._add_chunks(con,key,p['chunks'])
                for lid in p['library_ids']:
                    con.execute('INSERT OR IGNORE INTO membership VALUES(?,?)',(lid,key))
            elif kind == 'source_update':
                con.execute('UPDATE sources SET title=?,author=?,metadata=?,revision=revision+1 WHERE id=?',(p['title'],p.get('author',''),dumps(p.get('metadata',{})),key))
                con.execute('DELETE FROM membership WHERE source_id=?',(key,))
                for lid in p['library_ids']:
                    con.execute('INSERT INTO membership VALUES(?,?)',(lid,key))
            elif kind == 'source_delete':
                # 软删除保留不可变正文，使历史任务和已保存笔记的引用仍可核实。
                con.execute('UPDATE sources SET deleted=1,revision=revision+1 WHERE id=?',(key,))
            elif kind == 'note_save':
                if p.get('task_id') and con.execute('SELECT 1 FROM notes WHERE task_id=? AND deleted=0',(p['task_id'],)).fetchone():
                    raise Conflict('此任务已有已保存笔记，请重新预览以更新已有版本')
                evidence = p.get('evidence',[])
                for e in evidence:
                    ch = self.chunk(e['id'])
                    if not e.get('quote','').strip() or e['quote'] not in ch['text']:
                        raise ValueError('引用文本与原文不一致')
                con.execute('INSERT INTO notes(id,title,body,evidence,task_id,created) VALUES(?,?,?,?,?,?)',
                            (key,p['title'],p['body'],dumps(evidence),p.get('task_id'),stamp()))
            elif kind == 'note_update':
                for e in p.get('evidence',[]):
                    ch = self.chunk(e['id'])
                    if not e.get('quote','').strip() or e['quote'] not in ch['text']:
                        raise ValueError('引用文本与原文不一致')
                con.execute('UPDATE notes SET title=?,body=?,evidence=?,revision=revision+1 WHERE id=?',(p['title'],p['body'],dumps(p.get('evidence',[])),key))
            elif kind == 'note_delete':
                con.execute('UPDATE notes SET deleted=1,revision=revision+1 WHERE id=?',(key,))
            con.execute("UPDATE proposals SET state='committed',result=? WHERE id=?",(dumps(result),pid))
        self.projects.sync_all()
        self.lifecycle.clean_files()
        return result

    def notes(self):
        with self.connection() as con:
            return [{**dict(r),'evidence':json.loads(r['evidence'])} for r in con.execute('SELECT * FROM notes WHERE deleted=0 ORDER BY created DESC')]

    def task(self, task_id):
        with self.connection() as con:
            row = con.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not row:
                raise ValueError('研究任务不存在')
            return {**dict(row),**{k:json.loads(row[k]) for k in ('scope','evidence','draft')}}

    def update_task(self, task_id, **values):
        allowed = {'status','round','evidence','draft','error'}
        if not set(values) <= allowed:
            raise ValueError('不支持的任务字段')
        values['updated'] = stamp()
        with self.connection(True) as con:
            con.execute('UPDATE tasks SET '+','.join(k+'=?' for k in values)+' WHERE id=?',
                        [dumps(v) if isinstance(v,(list,dict)) else v for v in values.values()]+[task_id])
        self.projects.sync_task(task_id)

    def event(self, task_id, event, data):
        with self.connection(True) as con:
            con.execute('INSERT INTO events(task_id,event,data,created) VALUES(?,?,?,?)',(task_id,event,dumps(data),stamp()))

    def events(self, task_id, after=0):
        with self.connection() as con:
            return [{**dict(r),'data':json.loads(r['data'])} for r in con.execute('SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq',(task_id,after))]
