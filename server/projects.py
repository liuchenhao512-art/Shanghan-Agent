"""专题对话与资料文件夹。SQLite 为主记录，目录保存可直接阅读的副本。"""
import json
import hashlib
import re
import uuid
from pathlib import Path
from markdown_it import MarkdownIt
from .answers import conversation_body


class ProjectWorkspace:
    def __init__(self, store):
        self.store = store
        self.markdown = MarkdownIt('commonmark', {'html': False, 'linkify': False}).enable('table')
        self.sync_all()

    def create(self, title, request_id=None):
        title = str(title).strip()
        if not title or len(title) > 120:
            raise ValueError('专题名称应为1至120字')
        pid = request_id or uuid.uuid4().hex
        if not isinstance(pid, str) or not re.fullmatch(r'[a-f0-9]{32}', pid):
            raise ValueError('创建标识无效，请重新打开新建窗口')
        with self.store.connection(True) as con:
            old = con.execute('SELECT * FROM research_projects WHERE id=?', (pid,)).fetchone()
            if old and (old['deleted'] or old['archived'] or old['title'] != title):
                raise ValueError('此创建请求已经使用，请重新发起')
            if not old:
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .')[:45] or '专题'
                con.execute('INSERT INTO research_projects(id,title,folder,scope) VALUES(?,?,?,?)',
                    (pid, title, '专题/'+name+'-'+pid[:8], json.dumps({'library_ids':[], 'builtin':True})))
        self.sync(pid)
        return self.get(pid)

    def list(self, archived=False):
        with self.store.connection() as con:
            return [dict(r) for r in con.execute('''SELECT p.id,p.title,p.folder,p.archived,p.revision,
                (SELECT count(*) FROM tasks WHERE project_id=p.id) AS conversation_count,
                (SELECT count(*) FROM notes WHERE project_id=p.id AND deleted=0) AS note_count
                FROM research_projects p WHERE p.deleted=0 AND p.archived=? ORDER BY p.rowid DESC''',(int(archived),))]

    def get(self, pid, include_deleted=False):
        with self.store.connection() as con:
            row = con.execute('SELECT * FROM research_projects WHERE id=?', (pid,)).fetchone()
            if not row or (row['deleted'] and not include_deleted):
                raise ValueError('专题不存在或已删除')
            turns = [self.store.task(r[0]) for r in con.execute('SELECT id FROM tasks WHERE project_id=? ORDER BY rowid', (pid,))]
            notes = [{**dict(r),'evidence':json.loads(r['evidence'])} for r in con.execute('SELECT * FROM notes WHERE project_id=? AND deleted=0 ORDER BY rowid DESC', (pid,))]
            result = {**dict(row), 'scope':json.loads(row['scope']), 'turns':turns, 'notes':notes}
            for turn in turns:
                # 兼容旧回复的展示，不回写草稿或人工编辑的正式笔记。
                turn['html'] = self.markdown.render(conversation_body(turn['draft']))
                turn['activity'] = self.store.events(turn['id'])[-12:]
            return result

    def set_scope(self, pid, scope):
        self.require_active(pid)
        library_ids = list(dict.fromkeys(scope.get('library_ids', [])))
        with self.store.connection(True) as con:
            for lid in library_ids:
                if not con.execute('SELECT 1 FROM libraries WHERE id=? AND deleted=0 AND archived=0', (lid,)).fetchone():
                    raise ValueError('所选知识库已归档、删除或不存在')
            con.execute('UPDATE research_projects SET scope=? WHERE id=?', (json.dumps({'library_ids':library_ids,'builtin':bool(scope.get('builtin'))}), pid))
        self.sync(pid)

    def require_active(self, pid):
        project = self.get(pid)
        if project['archived']:
            raise ValueError('请先恢复已归档的研究专题，再继续对话')
        return project

    def history(self, pid):
        # 仅传同一专题的最近对话，用来理解追问，旧回答不能作为证据。
        result = []
        for turn in self.get(pid)['turns'][-8:]:
            result.append({'role':'user','content':turn['question']})
            result.append({'role':'assistant','content':conversation_body(turn['draft'])[:3000], 'evidence_status':'历史AI回答，仅用于理解追问，需重新读取原文'})
        return result

    def folder_path(self, project):
        target = (self.store.root/project['folder']).resolve()
        if not target.is_relative_to(self.store.root/'专题'):
            raise ValueError('专题文件夹路径无效')
        return target

    @staticmethod
    def artifact_name(key):
        key = str(key)
        return (key if re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', key) else hashlib.sha256(key.encode()).hexdigest())+'.md'

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_text(encoding='utf-8') == content:
            return
        temporary = path.with_name(path.name+'.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(path)

    def sync(self, pid):
        # 与数据库写入共用锁，防止不同回合同时写同一专题副本。
        with self.store.lock:
            project = self.get(pid, True)
            target = self.folder_path(project)
            transcript = '# '+project['title']+'\n\n> 对话与AI草稿自动保留；未经人工核对的回复不是独立原始证据。\n\n'
            for turn in project['turns']:
                transcript += '## 用户\n\n'+turn['question']+'\n\n## 研读助手\n\n'+(turn['draft'].get('body') or '本轮尚未生成回复。')+'\n\n'
                if turn['error']:
                    transcript += '调用状态：'+turn['error']+'\n\n'
                self.write(target/'研读草稿'/self.artifact_name(turn['id']), turn['draft'].get('body',''))
            self.write(target/'对话记录.md', transcript)
            self.write(target/'专题记录.json', json.dumps(project, ensure_ascii=False, indent=2))
            source_ids = set(project['scope'].get('library_ids', []))
            sources = list({s['id']:{k:s[k] for k in ('id','title','author','origin','original','sha256')} for lid in source_ids for s in self.store.sources(lid)}.values())
            self.write(target/'资料清单.json', json.dumps(sources, ensure_ascii=False, indent=2))
            with self.store.connection() as con:
                for note in con.execute('SELECT * FROM notes WHERE project_id=?', (pid,)):
                    content = ('> 此笔记已移出正式笔记列表，保留供历史核对。\n\n' if note['deleted'] else '')+note['body']
                    self.write(target/'正式笔记'/self.artifact_name(note['id']), content)

    def sync_all(self):
        with self.store.connection(True) as con:
            con.execute('UPDATE notes SET project_id=(SELECT project_id FROM tasks WHERE tasks.id=notes.task_id) WHERE project_id IS NULL AND task_id IS NOT NULL')
            ids = [r[0] for r in con.execute('SELECT id FROM research_projects WHERE deleted=0')]
        for pid in ids:
            self.sync(pid)

    def sync_task(self, tid):
        task = self.store.task(tid)
        if task.get('project_id'):
            self.sync(task['project_id'])
