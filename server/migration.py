"""把旧版一一对应的知识库与专题拆开，保留标识和全部历史关联。"""
import json
import re
import sqlite3
import uuid


def migrate_projects(store):
    with store.lock:
        con = sqlite3.connect(store.path)
        con.row_factory = sqlite3.Row
        try:
            if con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '3':
                return
            # 在任何结构改写之前保存一致的数据库副本。
            if con.execute('SELECT 1 FROM libraries UNION SELECT 1 FROM tasks LIMIT 1').fetchone():
                directory = store.root/'migrations'
                directory.mkdir(exist_ok=True)
                with sqlite3.connect(directory/('before-v3-'+uuid.uuid4().hex[:8]+'.sqlite')) as saved:
                    con.backup(saved)
            con.execute('PRAGMA foreign_keys=OFF')
            con.execute('BEGIN IMMEDIATE')
            columns = {r['name'] for r in con.execute('PRAGMA table_info(libraries)')}
            if 'archived' not in columns:
                con.execute('ALTER TABLE libraries ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
            old_projects = []
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='research_projects'").fetchone():
                old_projects = [dict(r) for r in con.execute('SELECT * FROM research_projects')]
                con.execute('DROP TABLE research_projects')
            con.execute('''CREATE TABLE research_projects(id TEXT PRIMARY KEY,title TEXT NOT NULL,
                folder TEXT NOT NULL,scope TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
                archived INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0)''')
            previous = {r['id']:r for r in old_projects}
            for row in con.execute('SELECT * FROM libraries').fetchall():
                old = previous.get(row['id'], {})
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', row['title']).strip(' .')[:45] or '专题'
                con.execute('INSERT INTO research_projects(id,title,folder,scope,archived) VALUES(?,?,?,?,?)',
                    (row['id'], row['title'], old.get('folder', '专题/'+name+'-'+row['id'][:8]),
                     old.get('scope', json.dumps({'library_ids':[row['id']], 'builtin':True})), row['deleted']))
            # 重建旧表，去除 project_id 指向 libraries 的外键，改为独立的研究专题。
            for table in ('tasks', 'notes'):
                columns = {r['name'] for r in con.execute('PRAGMA table_info('+table+')')}
                if 'project_id' not in columns:
                    con.execute('ALTER TABLE '+table+' ADD COLUMN project_id TEXT REFERENCES research_projects(id)')
                if table == 'tasks' and 'context' not in columns:
                    con.execute("ALTER TABLE tasks ADD COLUMN context TEXT NOT NULL DEFAULT '[]'")
                sql = con.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0]
                sql = re.sub(r'REFERENCES\s+libraries\s*\(id\)', 'REFERENCES research_projects(id)', sql, flags=re.I)
                sql = re.sub(r'CREATE TABLE\s+"?'+table+r'"?', 'CREATE TABLE '+table+'_v3', sql, count=1, flags=re.I)
                con.execute(sql)
                con.execute('INSERT INTO '+table+'_v3 SELECT * FROM '+table)
                con.execute('DROP TABLE '+table)
                con.execute('ALTER TABLE '+table+'_v3 RENAME TO '+table)
            legacy_id = None
            def legacy():
                nonlocal legacy_id
                if legacy_id is None:
                    legacy_id = uuid.uuid4().hex
                    con.execute('INSERT INTO research_projects(id,title,folder,scope) VALUES(?,?,?,?)',
                        (legacy_id, '历史研读', '专题/历史研读-'+legacy_id[:8], '{"library_ids":[],"builtin":true}'))
                return legacy_id
            for row in con.execute('SELECT id,scope FROM tasks WHERE project_id IS NULL').fetchall():
                ids = json.loads(row['scope']).get('library_ids', [])
                pid = next((i for i in ids if con.execute('SELECT 1 FROM research_projects WHERE id=?',(i,)).fetchone()), None)
                con.execute('UPDATE tasks SET project_id=? WHERE id=?', (pid or legacy(), row['id']))
            con.execute('UPDATE notes SET project_id=(SELECT project_id FROM tasks WHERE id=notes.task_id) WHERE project_id IS NULL')
            if con.execute('SELECT 1 FROM notes WHERE project_id IS NULL').fetchone():
                con.execute('UPDATE notes SET project_id=? WHERE project_id IS NULL', (legacy(),))
            con.execute('CREATE INDEX task_project ON tasks(project_id)')
            con.execute('CREATE INDEX note_project ON notes(project_id)')
            con.execute('CREATE UNIQUE INDEX note_task ON notes(task_id) WHERE task_id IS NOT NULL AND deleted=0')
            con.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
            if con.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('旧数据关联核验失败，升级已回滚')
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
