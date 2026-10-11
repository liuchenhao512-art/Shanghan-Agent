"""对话回答分层展示：模型知识、可核对原文和书目元信息分别保存。"""
import re


def citation_label(item):
    return f"{item['title']}；{item.get('author') or '作者待核'}；{item['locator']}"


def partial_body(question, evidence, reason):
    return f'# {question}\n\n> {reason}\n\n' + (f'已取得{len(evidence)}段资料，正在整理与核对。\n' if evidence else '正在理解问题并组织回答。\n')


def unverified_text(text):
    # 模型自己的文字不能伪装成由后端签发的原文证据编号。
    return re.sub(r'\[E\d+\]|〔未核验引用〕', '', text)


def conversation_body(draft):
    """仅整理对话显示，旧草稿、正式笔记及导出原件保持原样。"""
    body = draft.get('body', '')
    # 自动生成的原文清单由页面底部可打开的参考资料卡片替代。
    body = re.split(r'\n## (?:原文与出处|参考资料)\s*\n+(?=### \[E\d+\])', body, maxsplit=1)[0]
    banners = (
        '模型自身知识与分析 · 未经本库原文核验',
        '基于本轮知识库原文的分析 · 引文已核对，论断与证据的关系仍需人工审阅',
        '本次未引用知识库资料。',
        '本次仅查看书目，未引用正文。',
    )
    for banner in banners:
        body = re.sub(r'^> '+re.escape(banner)+r'\s*$', '', body, flags=re.M)
    body = body.replace('〔未核验引用〕', '')
    valid = {e['evidence_id'] for e in draft.get('evidence', []) if e.get('evidence_id')}
    body = re.sub(r'\[(E\d+)\]', lambda m: m[0] if m[1] in valid else '', body)
    return re.sub(r'^# [^\n]*\n', '', body, count=1).strip()


def validate_draft(question, data, evidence, catalogue=None, retrieval=None):
    by_id = {e['evidence_id']: e for e in evidence}
    warnings = []
    def claim(item):
        if not isinstance(item,dict) or not isinstance(item.get('text'),str):
            return None
        citations = item.get('citations',[])
        if not isinstance(citations,list):
            citations = []
        refs, quotes = [], []
        for cite in citations:
            if not isinstance(cite,dict):
                continue
            e = by_id.get(cite.get('evidence_id')) if isinstance(cite.get('evidence_id'),str) else None
            quote = cite.get('quote','')
            if e and isinstance(quote,str) and quote.strip() and quote in e['text']:
                refs.append(e['evidence_id']); quotes.append((e['evidence_id'],quote))
            else:
                warnings.append('已剔除一项无法与本轮已读原文匹配的引用。')
        if not refs:
            warnings.append('一项缺少有效原文支持的论断未纳入有据结论，也未转作模型知识。')
            return None
        return {'text':unverified_text(item['text']),'refs':list(dict.fromkeys(refs)),'quotes':quotes}
    sections = {}
    for key in ('answer','comparison','consensus','differences'):
        items = data.get(key,[])
        sections[key] = [c for item in items if (c:=claim(item))] if isinstance(items,list) else []
        if key == 'consensus':
            independent = []
            for c in sections[key]:
                sources = {('author',by_id[eid]['author']) if by_id[eid].get('author') else
                           ('source',by_id[eid]['source_id']) for eid in c['refs']}
                if len(sources) >= 2:
                    independent.append(c)
                else:
                    warnings.append('不足两个独立来源支持的内容未列为共识。')
            sections[key] = independent
    general = data.get('general_answer','')
    general = unverified_text(general.strip()) if isinstance(general,str) else ''
    requested = data.get('catalogue_ids',[])
    requested = {s for s in requested if isinstance(s,str)} if isinstance(requested,list) else set()
    books = [s for s in catalogue or [] if s['id'] in requested]
    if requested-set(s['id'] for s in books):
        warnings.append('已剔除不在本轮所选资料目录中的书目。')
    used = {}
    for items in sections.values():
        for c in items:
            for eid,quote in c.pop('quotes'):
                saved = used.setdefault(eid,{**by_id[eid],'quote':quote,'quotes':[]})
                if quote not in saved['quotes']:
                    saved['quotes'].append(quote)
    grounded = any(sections.values())
    body = '# '+question+'\n\n'
    if general:
        body += general+'\n\n'
    if grounded:
        body += '\n\n'.join(c['text']+' '+' '.join('['+r+']' for r in c['refs']) for c in sections['answer'])+'\n\n'
        if sections['comparison']:
            body += '## 观点比较\n\n| 观点概括 | 原文证据 |\n| --- | --- |\n'
            for c in sections['comparison']:
                body += '| '+c['text'].replace('|','／').replace('\n',' ')+' | '+'、'.join('['+r+']' for r in c['refs'])+' |\n'
        for key,title in (('consensus','共识'),('differences','分歧')):
            if sections[key]:
                body += '\n## '+title+'\n\n'+'\n'.join('- '+c['text']+' '+' '.join('['+r+']' for r in c['refs']) for c in sections[key])+'\n'
    if books:
        body += '\n## 所选资料目录\n\n> 来自本地书目记录；收录情况不代表已阅读全文。\n\n| 书目 | 作者 | 类型 | 段数 |\n| --- | --- | --- | --- |\n'
        def cell(value): return str(value or '待补充').replace('|','／').replace('\n',' ')
        for b in books:
            body += '| '+' | '.join(cell(v) for v in (b['title'],b.get('author'),b.get('origin') if b['kind']=='builtin' else b['kind'],b['chunks']))+' |\n'
    retrieval = retrieval or {}
    if retrieval.get('searched') and not evidence:
        body += '\n> 本轮检索未命中可用原文，不能据此判断知识库或某位作者没有相关论述。以上模型回答不作为原文依据。\n'
    if not general and not grounded and not books:
        body += '本轮回答没有通过原文引用核验的内容。可继续对话，或重新检索后核对。\n'
    gaps = data.get('gaps',[])
    gaps = [g for g in gaps if isinstance(g,str)] if isinstance(gaps,list) else []
    notes = [*gaps,*dict.fromkeys(warnings)]
    if notes:
        body += '\n## 资料缺口与核对事项\n\n'+'\n'.join('- '+unverified_text(g) for g in notes)+'\n'
    if used:
        body += '\n## 参考资料\n\n'
        for eid,e in used.items():
            body += f"### [{eid}] {citation_label(e)}\n\n"
            for quote in e['quotes']:
                body += '> '+quote.replace('\n','\n> ')+'\n\n'
            if e.get('origin','').startswith(('https://','http://')):
                body += '来源：'+e['origin']+'\n\n'
        body += '> 引用编号对应以上原文，其余内容为AI分析。\n'
    else:
        body += '\n> '+('本次仅查看书目，未引用正文。' if books else '本次未引用知识库资料。')+'\n'
    basis = 'mixed' if general and grounded else 'sources' if grounded else 'catalogue' if books else 'model'
    return {'body':body,'sections':sections,'general_answer':general,'basis':basis,
            'evidence':list(used.values()),'catalogue':books,'retrieval':retrieval,'warnings':list(dict.fromkeys(warnings))}
