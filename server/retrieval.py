"""限定资料范围的关键词检索，按注家均衡返回结果；不把AI笔记加入语料。"""
import re
from collections import defaultdict

GENERIC_TERMS = {'伤寒论', '各家', '各个', '医家', '注家', '注解', '阐释', '解读',
                 '解释', '观点', '原文', '条文', '认识', '相关', '比较', '分析', '如何',
                 '哪些', '有哪些', '内容', '资料', '论述', '学说', '注释', '各家注释'}


def catalogue(store, scope):
    ids = scope.get('source_ids', [])
    if not ids:
        return []
    with store.connection() as con:
        return [dict(r) for r in con.execute('''SELECT s.id,s.title,s.author,s.origin,s.kind,
            s.sha256 AS version,(SELECT count(*) FROM chunks c WHERE c.source_id=s.id) AS chunks
            FROM sources s WHERE s.id IN ('''+','.join('?' for _ in ids)+') ORDER BY s.rowid', ids)]


def terms(query):
    words = list(dict.fromkeys(re.findall(r'[\w]+', query.lower())))[:12]
    meaningful = [w for w in words if w not in GENERIC_TERMS]
    return meaningful or words


def family(item):
    # 原书与逐条注文中的同一注家只占一个来源轮次。
    return ('author', item['author']) if item.get('author') else ('source', item['source_id'])


def balanced(items, limit):
    buckets = defaultdict(list)
    for item in items:
        buckets[family(item)].append(item)
    result = []
    while buckets and len(result) < limit:
        for key in list(buckets):
            result.append(buckets[key].pop(0))
            if not buckets[key]:
                del buckets[key]
            if len(result) == limit:
                break
    return result


def window(text, normalized, needles, size=2500):
    positions = [normalized.lower().find(word.lower()) for word in needles if word]
    positions = [p for p in positions if p >= 0]
    start = max(0, min(positions) - min(250, size//4)) if positions else 0
    start = min(start, max(0, len(text)-size))
    return text[start:start+size], start


def search(store, query, scope, limit=30, offset=0):
    query = store.cc.convert(str(query).strip()).lower()
    ids = scope.get('source_ids', [])
    if not query or not ids:
        return []
    if len(query) > 200:
        raise ValueError('检索词请控制在200字以内')
    limit = max(1, min(int(limit), 80))
    offset = max(0, min(int(offset), 5000))
    words = terms(query)
    if not words:
        return []
    sources = catalogue(store, scope)
    # 明确写出的作者限定范围；一般的“注家”等词不会成为正文必含条件。
    named_authors = {s['author'] for s in sources if s['author'] and store.cc.convert(s['author']).lower() in words}
    if named_authors:
        ids = [s['id'] for s in sources if s['author'] in named_authors]
        words = [w for w in words if w not in {store.cc.convert(a).lower() for a in named_authors}]
    searchable = [w for w in words if len(w) >= 3]
    short = [w for w in words if len(w) < 3]
    predicates, args = [], []
    if searchable:
        predicates.append('c.id IN (SELECT chunk_id FROM chunk_fts WHERE chunk_fts MATCH ?)')
        args.append(' OR '.join('"'+w.replace('"','""')+'"' for w in searchable))
    for word in short:
        predicates.append('instr(lower(c.normalized),?)>0'); args.append(word)
    score = 'CASE WHEN instr(lower(c.normalized),?)>0 THEN 100 ELSE 0 END'
    score_args = [query]
    for word in words:
        score += ' + CASE WHEN instr(lower(c.normalized),?)>0 THEN 10 ELSE 0 END'
        score_args.append(word)
    # 不先截断整库前N项，先按来源分组，之后轮流返回，保证其他注家可见。
    sql = '''WITH candidates AS (
        SELECT c.id,c.source_id,c.ordinal,c.locator,c.text,c.normalized,s.title,s.author,s.origin,
        '''+score+''' AS relevance,
        CASE WHEN s.author<>'' THEN 'author:'||s.author ELSE 'source:'||s.id END AS family
        FROM chunks c JOIN sources s ON s.id=c.source_id
        WHERE c.source_id IN ('''+','.join('?' for _ in ids)+') AND ('+(' OR '.join(predicates) or '1')+''')),
        ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY family ORDER BY relevance DESC,ordinal,id) AS rank FROM candidates)
        SELECT * FROM ranked WHERE rank<=? ORDER BY relevance DESC,rank,family,ordinal,id'''
    with store.connection() as con:
        rows = [dict(r) for r in con.execute(sql,[*score_args,*ids,*args,offset+limit])]
    result = balanced(rows,offset+limit)[offset:offset+limit]
    for row in result:
        row['snippet'], _ = window(row['text'], row.pop('normalized'), words, 350)
        row['matched_terms'] = words
        row.pop('family',None); row.pop('rank',None)
    return result
