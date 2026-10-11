"""可独立阅读的成果，以及可校验、排除密钥的备份包。"""
from pathlib import Path, PurePosixPath
from urllib.parse import quote
import html
import io
import json
import shutil
import sqlite3
import zipfile
from markdown_it import MarkdownIt
from .storage import digest, dumps, uid, stamp

def export_markdown(note, attachment_links=None):
    body = note['body']
    if note.get('evidence'):
        body += '\n\n## 可核对来源记录\n\n'
        for i,e in enumerate(note['evidence'],1):
            body += f"{i}. {e.get('title','书名待核')}；{e.get('author') or '作者待核'}；{e.get('locator','位置待核')}。资料标识：{e['id']}\n"
            if attachment_links and e['id'] in attachment_links:
                body += f"   [查看原文快照]({attachment_links[e['id']]})\n"
    return body

def markdown_bundle(store, note):
    """导出自足的相对路径资料包；内置原文保存快照，个人来源附带原件。"""
    token = uid()
    directory = store.root/'exports'/('markdown-'+token)
    attachment_name = '附件-'+token[:12]
    attachments = directory/attachment_name
    attachments.mkdir(parents=True)
    links, copied = {}, {}
    for evidence in note.get('evidence', []):
        chunk = store.chunk(evidence['id'])
        if not evidence.get('quote') or evidence['quote'] not in chunk['text']:
            raise ValueError('导出引用与保存的原文不一致，请重新核对')
        source = store.source(chunk['source_id'])
        filename = '来源-'+digest(evidence['id'])[:20]+'.md'
        links[evidence['id']] = quote(attachment_name+'/'+filename)
        content = f"# {evidence.get('title') or source['title']}\n\n作者：{evidence.get('author') or '待核'}\n\n位置：{evidence['locator']}\n\n资料标识：{evidence['id']}\n\n来源类型：{source['origin']}\n\n"
        if not source['builtin']:
            original = (store.root/source['original']).resolve()
            if not original.is_relative_to(store.root/'originals') or not original.is_file() or digest(original.read_bytes()) != source['sha256']:
                raise ValueError('原始资料缺失或校验不一致，导出已停止')
            if source['id'] not in copied:
                copied[source['id']] = '原件-'+source['id']+original.suffix
                shutil.copy2(original, attachments/copied[source['id']])
            content += f"[打开原始文件]({quote(copied[source['id']])})\n\n"
        content += '## 提取原文快照\n\n'+chunk['text']+'\n'
        (attachments/filename).write_text(content, encoding='utf-8')
    target = directory/'note.md'
    target.write_text(export_markdown(note, links), encoding='utf-8')
    return {'markdown_path':str(target),'attachments_path':str(attachments),'attachments_name':attachment_name}

def export_html(note):
    md = MarkdownIt('commonmark',{'html':False,'linkify':False}).enable('table')
    body = md.render(export_markdown(note))
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>'''+html.escape(note['title'])+'''</title>
    <style>@page{size:A4;margin:18mm 16mm}body{font:12pt/1.8 "Microsoft YaHei","PingFang SC",sans-serif;color:#20231e}h1{font-size:21pt}h2{font-size:16pt;border-bottom:1px solid #aaa;page-break-after:avoid}h3{font-size:12pt;page-break-after:avoid}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{border:1px solid #aaa;padding:6pt;overflow-wrap:anywhere;vertical-align:top}thead{display:table-header-group}tr{break-inside:avoid}blockquote{border-left:3px solid #bbb;padding-left:10pt;margin-left:0;color:#444}p,li{overflow-wrap:anywhere}a{color:#222}img{max-width:100%}</style></head><body>'''+body+'</body></html>'

def backup(store):
    token = uid()
    temp = store.root/'staging'/('backup-'+token+'.sqlite')
    target = store.root/'exports'/('伤寒论知识库备份-'+token[:8]+'.shanghan.zip')
    files = {}
    with store.connection() as source:
        dest = sqlite3.connect(temp)
        source.backup(dest)
        dest.close()
        files['personal.sqlite'] = temp
        for folder,base in (('originals',store.root/'originals'),('builtin',store.builtin),('专题',store.root/'专题')):
            for p in base.rglob('*'):
                if p.is_file() and not p.is_symlink():
                    files[folder+'/'+p.relative_to(base).as_posix()] = p
        manifest = {'format':'shanghan-backup','version':1,'created':stamp(),'corpus_version':store.corpus_version,'files':{}}
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,path in files.items():
                raw = path.read_bytes()
                manifest['files'][name] = {'sha256':digest(raw),'bytes':len(raw)}
                z.writestr(name,raw)
            z.writestr('manifest.json',dumps(manifest))
    temp.unlink(missing_ok=True)
    return {'filename':target.name,'path':str(target),'bytes':target.stat().st_size}

def inspect_backup(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            if len(names)!=len(set(names)) or len(names)>100000 or sum(i.file_size for i in z.infolist())>4*1024**3:
                raise ValueError('备份含重复条目或解压后过大')
            manifest = json.loads(z.read('manifest.json'))
            if manifest.get('format')!='shanghan-backup' or manifest.get('version')!=1:
                raise ValueError('不支持的备份格式或版本')
            if set(names)!=set(manifest['files'])|{'manifest.json'}:
                raise ValueError('备份清单与文件不一致')
            for name,info in manifest['files'].items():
                path = PurePosixPath(name)
                if '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts or not (name=='personal.sqlite' or name.startswith(('originals/','builtin/','专题/'))):
                    raise ValueError('备份含不允许的文件路径')
                data = z.read(name)
                if len(data)!=info['bytes'] or digest(data)!=info['sha256']:
                    raise ValueError('备份校验失败：'+name)
            if 'personal.sqlite' not in manifest['files'] or 'builtin/kb.sqlite' not in manifest['files']:
                raise ValueError('备份缺少数据库或内置语料')
            return manifest
    except (zipfile.BadZipFile,KeyError,json.JSONDecodeError) as e:
        raise ValueError('备份包损坏或缺少必要清单') from e

def preview_restore(store,raw):
    manifest = inspect_backup(raw)
    token = uid()
    (store.root/'staging'/(token+'.restore.zip')).write_bytes(raw)
    # 只读核验清单中的数据库，展示将恢复的具体对象。
    preview_db = store.root/'staging'/(token+'.preview.sqlite')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            preview_db.write_bytes(archive.read('personal.sqlite'))
        connection = sqlite3.connect(preview_db.as_uri()+'?mode=ro', uri=True)
        try:
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('备份数据库完整性检查未通过')
            contents = {
                'libraries':[r[0] for r in connection.execute('SELECT title FROM libraries WHERE deleted=0')],
                'sources':[r[0] for r in connection.execute('SELECT title FROM sources WHERE deleted=0 AND builtin=0')],
                'notes':[r[0] for r in connection.execute('SELECT title FROM notes WHERE deleted=0')],
            }
            project_columns = {r[1] for r in connection.execute('PRAGMA table_info(research_projects)')}
            if 'title' in project_columns:
                contents['projects'] = [r[0] for r in connection.execute('SELECT title FROM research_projects WHERE deleted=0')]
                contents['archived_libraries'] = [r[0] for r in connection.execute('SELECT title FROM libraries WHERE deleted=0 AND archived=1')]
                contents['archived_projects'] = [r[0] for r in connection.execute('SELECT title FROM research_projects WHERE deleted=0 AND archived=1')]
        finally:
            connection.close()
    finally:
        preview_db.unlink(missing_ok=True)
    return {'id':token,'hash':digest(raw),'created':manifest['created'],'file_count':len(manifest['files']),
            'bytes':sum(f['bytes'] for f in manifest['files'].values()),'corpus_version':manifest['corpus_version'],'contents':contents,
            'description':'恢复到独立目录，当前知识库保持不变；模型密钥需另行配置。'}

def restore(store,token,expected_hash):
    if len(token)!=32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('恢复预览无效')
    source = store.root/'staging'/(token+'.restore.zip')
    raw = source.read_bytes()
    if digest(raw)!=expected_hash:
        raise ValueError('备份已发生变化，请重新预览')
    inspect_backup(raw)
    target = store.root.parent/('restored-'+token)
    if target.exists():
        raise ValueError('该备份已经恢复，请使用已生成的数据目录')
    target.mkdir()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for name in z.namelist():
                if name=='manifest.json':
                    continue
                out = target/PurePosixPath(name)
                out.parent.mkdir(parents=True,exist_ok=True)
                out.write_bytes(z.read(name))
        con = sqlite3.connect(target/'personal.sqlite')
        check = con.execute('PRAGMA integrity_check').fetchone()[0]
        version = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        fk = con.execute('PRAGMA foreign_key_check').fetchall()
        if check!='ok' or not version or version[0] not in ('1','2','3') or fk:
            con.close()
            raise ValueError('备份数据库完整性检查未通过')
        try:
            for original,expected in con.execute('SELECT original,sha256 FROM sources WHERE builtin=0'):
                original_path = (target/original).resolve()
                if not original_path.is_relative_to(target/'originals') or not original_path.is_file() or digest(original_path.read_bytes())!=expected:
                    raise ValueError('备份中的原始资料缺失或校验不一致')
            for (evidence_json,) in con.execute('SELECT evidence FROM notes'):
                for evidence in json.loads(evidence_json):
                    row = con.execute('SELECT text FROM chunks WHERE id=?',(evidence['id'],)).fetchone()
                    if not row or not evidence.get('quote') or evidence['quote'] not in row[0]:
                        raise ValueError('备份中的笔记引用无法与原文对应')
            con.execute('DELETE FROM chunk_fts')
            con.execute('INSERT INTO chunk_fts(chunk_id,body) SELECT id,normalized FROM chunks')
            con.commit()
        finally:
            con.close()
        for part in ('originals','staging','exports'):
            (target/part).mkdir(exist_ok=True)
        return {'directory':str(target),'verified':True}
    except Exception:
        # 只回滚本函数刚创建且经过边界验证的恢复目录。
        if target.parent==store.root.parent and target.name=='restored-'+token:
            shutil.rmtree(target)
        raise
