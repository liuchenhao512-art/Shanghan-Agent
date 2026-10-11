"""只提取用户指定资料，保留实际定位；不进行 OCR 或扩展联网搜索。"""
from __future__ import annotations
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse, urljoin
import base64
import io
import ipaddress
import json
import re
import socket
import zipfile
import xml.etree.ElementTree as ET
import httpx
from bs4 import BeautifulSoup
from charset_normalizer import from_bytes
from docx import Document
from docx.table import Table
from pypdf import PdfReader
from .storage import digest, uid, stamp

MAX_FILE = 100 * 1024 * 1024

def decode_text(raw):
    for encoding in ('utf-8-sig','utf-16' if raw[:2] in (b'\xff\xfe',b'\xfe\xff') else 'utf-8'):
        try:
            return raw.decode(encoding),encoding
        except UnicodeError:
            pass
    # 既有中文电子书常用 GB18030，短文本的统计猜测容易误判为其他编码。
    try:
        chinese = raw.decode('gb18030')
        if all(c.isprintable() or c in '\n\r\t' for c in chinese):
            return chinese,'gb18030'
    except UnicodeError:
        pass
    result = from_bytes(raw).best()
    if result is None or result.percent_chaos > 15:
        raise ValueError('无法可靠识别文字编码，请另存为 UTF-8 后导入')
    return str(result),result.encoding

def chunks_from_text(text, prefix='', markdown=False):
    chunks = []
    heading = ''
    for paragraph in re.split(r'\n\s*\n|\r?\n',text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if markdown and re.match(r'^#{1,6}\s+',paragraph):
            heading = re.sub(r'^#+\s+','',paragraph)
        # 大段切分保留原字面，不把规范化检索文本用作引文。
        for start in range(0,len(paragraph),1800):
            chunks.append({'locator':'·'.join(x for x in (prefix,heading,f'段{len(chunks)+1}') if x),'text':paragraph[start:start+1800]})
    return chunks

def check_archive(z):
    if len(z.infolist()) > 30000 or sum(i.file_size for i in z.infolist()) > 300*1024*1024:
        raise ValueError('文档解压后过大，无法导入')

def parse_file(name, raw):
    ext = Path(name).suffix.lower()
    metadata = {'filename':Path(name).name,'imported_at':stamp(),'warnings':[]}
    title, author, chunks = Path(name).stem,'',[]
    if ext in ('.txt','.md','.markdown'):
        body,encoding = decode_text(raw)
        chunks = chunks_from_text(body,markdown=ext != '.txt')
        metadata['encoding'] = encoding
        if re.search(r'!\[[^\]]*\]\(',body):
            metadata['warnings'].append('正文含图片链接；图片中的文字不纳入检索，请核对所需图文。')
    elif ext == '.pdf':
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError('PDF 已加密，请提供解密后的副本')
        missing = []
        for i,page in enumerate(reader.pages,1):
            try:
                text = page.extract_text() or ''
            except Exception:
                text = ''
            if not text.strip():
                missing.append(i)
            else:
                chunks += chunks_from_text(text,f'文件第{i}页')
        metadata.update({'page_count':len(reader.pages),'pages_without_text':missing,'coverage':'partial' if missing else 'text_extracted'})
        if missing:
            metadata['warnings'].append('以下页面无可提取文字或为空白：'+','.join(map(str,missing))+ '。如为扫描页，请用外部 OCR 转换为 Markdown 后导入；处理可能需要额外时间或费用。')
        info = reader.metadata
        if info:
            title = str(info.title or title)
            author = str(info.author or '')
    elif ext == '.docx':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            check_archive(z)
        doc = Document(io.BytesIO(raw))
        title = doc.core_properties.title or title
        author = doc.core_properties.author or ''
        heading = ''
        for block in doc.iter_inner_content():
            if isinstance(block,Table):
                text = '\n'.join(' | '.join(cell.text for cell in row.cells) for row in block.rows)
            else:
                text = block.text
                if block.style and block.style.name.startswith('Heading'):
                    heading = text
            if text.strip():
                chunks += chunks_from_text(text,heading or '正文')
        if doc.inline_shapes:
            metadata['warnings'].append('文档包含图片；仅提取正文和表格，图片文字未识别。')
    elif ext == '.epub':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            check_archive(z)
            container = ET.fromstring(z.read('META-INF/container.xml'))
            rootfile = next((e.attrib['full-path'] for e in container.iter() if e.tag.endswith('rootfile')),None)
            if not rootfile:
                raise ValueError('EPUB 缺少内容目录')
            package = ET.fromstring(z.read(rootfile))
            base = PurePosixPath(rootfile).parent
            manifest = {e.attrib['id']:e.attrib for e in package.iter() if e.tag.endswith('}item')}
            for e in package.iter():
                if e.tag.endswith('}title') and e.text:
                    title = e.text
                if e.tag.endswith('}creator') and e.text:
                    author = e.text
            for e in package.iter():
                if not e.tag.endswith('}itemref'):
                    continue
                item = manifest.get(e.attrib.get('idref'),{})
                href = item.get('href','').split('#')[0]
                if not href:
                    continue
                entry = str(base / href)
                soup = BeautifulSoup(z.read(entry),'html.parser')
                for bad in soup(['script','style']):
                    bad.decompose()
                header = soup.find(re.compile('^h[1-6]$'))
                label = header.get_text(' ',strip=True) if header else href
                chunks += chunks_from_text(soup.get_text('\n',strip=True),label)
    elif ext == '.doc':
        raise ValueError('旧版 .doc 请先在 Word 或 WPS 中另存为 .docx 后导入')
    else:
        raise ValueError('支持文字 PDF、EPUB、DOCX、TXT 和 Markdown')
    metadata['character_count'] = sum(len(c['text']) for c in chunks)
    metadata['chunk_count'] = len(chunks)
    if not chunks:
        metadata['warnings'].append('未提取到可用正文，不能正式入库。')
    return {'title':title,'author':author,'format':ext.lstrip('.'),'chunks':chunks,'metadata':metadata}

def validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('请提供完整的公开 http/https 文章链接')
    try:
        addresses = socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)
    except OSError as e:
        raise ValueError('文章域名无法解析') from e
    if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('网页导入仅支持公开文章地址，不读取本机或内网服务')

async def parse_url(url):
    original = url
    raw = b''
    async with httpx.AsyncClient(timeout=30,follow_redirects=False,trust_env=False) as client:
        for _ in range(5):
            validate_public_url(url)
            async with client.stream('GET',url,headers={'User-Agent':'Mozilla/5.0 ShanghanReader/0.1','Accept-Language':'zh-CN,zh;q=0.9'}) as response:
                if response.is_redirect:
                    url = urljoin(url,response.headers.get('location',''))
                    continue
                if response.status_code != 200:
                    raise ValueError(f'文章访问失败（HTTP {response.status_code}），可改用文件导入')
                if 'html' not in response.headers.get('content-type',''):
                    raise ValueError('该地址未返回网页正文，请下载文档后使用文件导入')
                async for data in response.aiter_bytes():
                    raw += data
                    if len(raw)>10*1024*1024:
                        raise ValueError('网页过大，请使用文件导入')
                break
        else:
            raise ValueError('网页重定向过多')
    soup = BeautifulSoup(raw,'html.parser')
    title = soup.title.get_text(' ',strip=True) if soup.title else original
    content = soup.select_one('#js_content') or soup.find('article') or soup.find('main')
    warnings = []
    if content is None:
        content = soup.body or soup
        warnings.append('未识别到明确文章区域，请核对是否混入导航或缺少正文。')
    for bad in content(['script','style','nav','footer','form','noscript']):
        bad.decompose()
    text = content.get_text('\n',strip=True)
    if len(text)<100 or any(x in text[:500] for x in ('环境异常','访问过于频繁','完成验证后','请先登录')):
        raise ValueError('未能完整获取文章正文，可能存在登录或访问限制，请改用文件导入')
    result = {'title':title,'author':'','format':'web','origin':original,'chunks':chunks_from_text(text),
              'metadata':{'url':original,'resolved_url':url,'fetched_at':stamp(),'warnings':warnings,'character_count':len(text)}}
    return raw,result

def stage(store, raw, parsed, library_ids, filename):
    if len(raw)>MAX_FILE:
        raise ValueError('单份资料暂支持最大100MB')
    sid = uid()
    suffix = '.html' if parsed['format']=='web' else Path(filename).suffix.lower()
    relative = 'originals/' + digest(raw) + suffix
    target = store.root / relative
    if not target.exists():
        target.write_bytes(raw)
    payload = {**parsed,'source_id':sid,'sha256':digest(raw),'original':relative,'library_ids':library_ids}
    payload['metadata']['bibliography_status'] = '待核对'
    duplicates = [s for s in store.sources() if s['sha256']==payload['sha256']]
    if duplicates:
        payload['metadata']['warnings'].append('检测到已入库的相同文件；确认后仅关联目标知识库，不覆盖原资料。')
    return store.propose('import',payload)
