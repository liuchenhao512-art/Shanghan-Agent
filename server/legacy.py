# -*- coding: utf-8 -*-
"""伤寒论九家注知识库 · demo 后端（FastAPI）。"""
import os, sqlite3, json, urllib.request
from pathlib import Path
from fastapi import FastAPI, Query, Body
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "resources", "builtin", "kb.sqlite")
STATIC = os.path.join(ROOT, "ui")

# 读取 .env（DeepSeek）
ENV = {}  # 桌面主进程注入模型设置，不再读取旧项目 .env。
DS_KEY = ENV.get("DEEPSEEK_API_KEY", "")
DS_URL = ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DS_MODEL = ENV.get("DEEPSEEK_MODEL", "deepseek-chat")

app = FastAPI(title="伤寒论九家注知识库")

CMT_ORDER = ["成无己", "方有执", "喻昌", "张志聪", "张锡驹", "陈修园", "柯韵伯", "尤在泾", "吴谦"]
# 注家朝代·学派归属已写入 SUMMARY_SYS 背景设定（不注入注文标签、不在输出展示）

# 关联条文连读组（data/parsed/groups.json，用户可编辑，重启生效）
def load_groups():
    p = os.path.join(ROOT, "data", "parsed", "groups.json")
    if not os.path.exists(p):
        return []
    try:
        gs = json.load(open(p, encoding="utf-8")).get("groups", [])
        for i, g in enumerate(gs):
            g["id"] = i
        return gs
    except Exception:
        return []
GROUPS = load_groups()
NUM2GROUP = {n: g for g in GROUPS for n in g["nums"]}

# 教材解析（data/parsed/textbook_notes.json：选读十四五优先，讲义补缺；OCR 提取）
def load_textbook():
    p = os.path.join(ROOT, "data", "parsed", "textbook_notes.json")
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
        return {int(k): v for k, v in d.items()}
    except Exception:
        return {}
TBNOTES = load_textbook()

def db():
    con = sqlite3.connect(Path(DB).as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    return con

@app.get("/api/meta")
def meta():
    con = db()
    cs = [dict(r) for r in con.execute("SELECT * FROM commentators ORDER BY seq")]
    chapters = [r[0] for r in con.execute("SELECT DISTINCT chapter FROM passages ORDER BY seq")]
    n = con.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    con.close()
    return {"commentators": cs, "chapters": chapters, "passage_count": n, "ai": bool(DS_KEY),
            "groups": GROUPS}

@app.get("/api/passages")
def passages(chapter: str = ""):
    con = db()
    if chapter:
        rows = con.execute("SELECT num,chapter,text FROM passages WHERE chapter=? ORDER BY seq", (chapter,)).fetchall()
    else:
        rows = con.execute("SELECT num,chapter,text FROM passages ORDER BY seq").fetchall()
    con.close()
    return [dict(r) for r in rows]

def get_passage_full(num):
    con = db()
    p = con.execute("SELECT num,chapter,text FROM passages WHERE num=?", (num,)).fetchone()
    if not p:
        con.close(); return None
    comments = [dict(r) for r in con.execute(
        "SELECT commentator,segment,text,flag FROM comments WHERE passage_num=? ORDER BY seq", (num,))]
    appendix = [r[0] for r in con.execute(
        "SELECT text FROM appendix WHERE passage_num=? ORDER BY seq", (num,))]
    con.close()
    grouped = []
    for name in CMT_ORDER:
        segs = [c for c in comments if c["commentator"] == name]
        if segs:
            grouped.append({"commentator": name, "flag": segs[0].get("flag", ""), "segments": segs})
    return {"passage": dict(p), "commentators": grouped, "appendix": appendix}

@app.get("/api/passage/{num}")
def passage(num: int):
    d = get_passage_full(num)
    if not d:
        return JSONResponse({"error": "not found"}, status_code=404)
    d["group"] = NUM2GROUP.get(num)
    d["textbook"] = TBNOTES.get(num)
    return d

@app.get("/api/zhijie")
def zhijie_toc():
    con = db()
    rows = con.execute("SELECT DISTINCT href,label FROM zhijie ORDER BY id").fetchall()
    con.close()
    return [dict(r) for r in rows]

@app.get("/api/zhijie/{href}")
def zhijie_chapter(href: str):
    con = db()
    rows = con.execute("SELECT para_idx,tag,text FROM zhijie WHERE href=? ORDER BY para_idx", (href,)).fetchall()
    label = con.execute("SELECT label FROM zhijie WHERE href=? LIMIT 1", (href,)).fetchone()
    con.close()
    return {"label": label[0] if label else href, "paras": [dict(r) for r in rows]}

@app.get("/api/origbooks")
def origbooks():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT book_id,author,book_name,source FROM origbooks ORDER BY seq")]
    con.close()
    return rows

@app.get("/api/origbook/{bid}")
def origbook(bid: str):
    con = db()
    b = con.execute("SELECT book_id,author,book_name,source FROM origbooks WHERE book_id=?", (bid,)).fetchone()
    if not b:
        con.close(); return JSONResponse({"error": "not found"}, status_code=404)
    rows = con.execute("SELECT chap_idx,chap_title,tag,text,gseq FROM origpara WHERE book_id=? ORDER BY gseq", (bid,)).fetchall()
    con.close()
    chapters = []
    last = None
    for r in rows:
        if last is None or r["chap_idx"] != last["idx"]:
            last = {"idx": r["chap_idx"], "title": r["chap_title"], "paras": []}
            chapters.append(last)
        last["paras"].append({"g": r["gseq"], "tag": r["tag"], "text": r["text"]})
    return {**dict(b), "chapters": chapters}

def make_snippet(text, q, win=16):
    i = text.find(q)
    if i < 0:
        return text[:win * 2]
    a = max(0, i - win); b = min(len(text), i + len(q) + win)
    return (("…" if a > 0 else "") + text[a:i] + "[[" + q + "]]" +
            text[i + len(q):b] + ("…" if b < len(text) else ""))

@app.get("/api/search")
def search(q: str = Query(...), kind: str = "", commentator: str = "", limit: int = 80):
    q = q.strip()
    if len(q) < 1:
        return {"results": [], "note": "请输入检索词"}
    con = db()
    like = f"%{q}%"
    results = []
    if kind in ("", "passage"):
        for r in con.execute("SELECT num,chapter,text FROM passages WHERE text LIKE ? ORDER BY seq", (like,)):
            results.append({"kind": "passage", "ref": str(r["num"]), "commentator": "",
                            "chapter": r["chapter"], "snip": make_snippet(r["text"], q)})
    if kind in ("", "comment"):
        cargs = [like]
        csql = "SELECT c.passage_num,c.commentator,c.text,p.chapter FROM comments c JOIN passages p ON p.num=c.passage_num WHERE c.text LIKE ?"
        if commentator:
            csql += " AND c.commentator=?"; cargs.append(commentator)
        csql += " ORDER BY c.seq"
        for r in con.execute(csql, cargs):
            results.append({"kind": "comment", "ref": str(r["passage_num"]), "commentator": r["commentator"],
                            "chapter": r["chapter"], "snip": make_snippet(r["text"], q)})
    if kind in ("", "zhijie"):
        for r in con.execute("SELECT href,label,text FROM zhijie WHERE text LIKE ? ORDER BY id", (like,)):
            results.append({"kind": "zhijie", "ref": r["href"], "commentator": "张锡驹",
                            "chapter": r["label"], "snip": make_snippet(r["text"], q)})
    con.close()
    total = len(results)
    return {"results": results[:limit], "count": total, "truncated": total > limit}

# ---------- AI（DeepSeek，检索增强 + 分层标注） ----------

def ds_stream(messages, temperature=0.4):
    """调用 DeepSeek 流式接口，逐段 yield 文本。"""
    body = json.dumps({"model": DS_MODEL, "messages": messages,
                       "stream": True, "temperature": temperature}).encode("utf-8")
    req = urllib.request.Request(DS_URL + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + DS_KEY})
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
            except Exception:
                continue

def passage_context(num):
    """组装某条的库内上下文（条文+各家注）供 LLM。"""
    d = get_passage_full(num)
    if not d:
        return "", None
    p = d["passage"]
    lines = [f"【原文·第{p['num']}条·{p['chapter']}】{p['text']}"]
    tb = TBNOTES.get(p["num"])
    if tb:
        tparts = []
        if tb.get("tiyao"):
            tparts.append("提要：" + tb["tiyao"])
        if tb.get("jiexi"):
            tparts.append("解析：" + tb["jiexi"])
        if tb.get("bingji"):
            tparts.append("病机：" + tb["bingji"])
        if tparts:
            lines.append("【教材解析·" + str(tb.get('source') or '教材来源待核') + "】" + "\n".join(tparts))
    for g in d["commentators"]:
        tag = "（自动对齐，待人工复核）" if g.get("flag") == "review" else ""
        txt = "".join(s["text"] for s in g["segments"])
        lines.append(f"【{g['commentator']}注{tag}】{txt}")
    return "\n\n".join(lines), d

SUMMARY_SYS = (
    "你是《伤寒论》教学助手，面向中医院校学生。仅依据【提供的库内材料】作答，不得虚构条文或注家观点；"
    "若材料不足以回答，明说'库内材料未涉及'。用简体中文，条理清晰，避免直接给临床诊疗建议。"
    "输出必须直接以第一个小标题开始，严禁任何开场白、引入语、过渡语（如'好的，同学们''我们来看第N条'"
    "'教材已给出……现在我们来比较'之类）与总结性结语，也不要复述条文或教材内容。"
    "做注家比较归组时，一律以各家对本条的实际学术观点与思想特点分类，"
    "不以学派门户（错简重订/维护旧论等）分类，也不要给医家附加'（朝代·学派）'式标签。")

@app.post("/api/ai/summary")
def ai_summary(payload: dict = Body(...)):
    if not DS_KEY:
        return JSONResponse({"error": "未配置 DeepSeek API Key"}, status_code=400)
    nums = payload.get("nums")
    if nums:  # 合参连读：多条联合导读
        nums = [int(n) for n in nums][:4]
        parts = []
        for n in nums:
            ctx, d = passage_context(n)
            if ctx:
                parts.append(ctx)
        if not parts:
            return JSONResponse({"error": "条文不存在"}, status_code=404)
        label = payload.get("label", "")
        ns = "、".join(str(n) for n in nums)
        user = (f"以下是《伤寒论》紧密关联的第{ns}条（{label}）及各家注：\n\n" + "\n\n====\n\n".join(parts) +
                "\n\n这几条文意直承、需合参理解。请完成：\n"
                "① 用 3-4 句话说明这组条文的整体脉络：前后如何承接、对举或递进；\n"
                "② 指出合读之后才能看清、单读易误解的要点；\n"
                "③ 简要比较各注家对这组条文关系的处理（每家一行）。\n"
                "格式用简短小标题+要点，控制在 500 字内。所有论断须基于上述材料。")
        msgs = [{"role": "system", "content": SUMMARY_SYS}, {"role": "user", "content": user}]
        return StreamingResponse(ds_stream(msgs), media_type="text/plain; charset=utf-8")
    num = int(payload.get("num", 0))
    ctx, d = passage_context(num)
    if not ctx:
        return JSONResponse({"error": "条文不存在"}, status_code=404)
    names = "、".join(g["commentator"] for g in d["commentators"])
    if TBNOTES.get(num):
        # 教材解析已在前端直接展示，AI 做逐家比较＋注家之间的概括比较
        user = (f"以下是《伤寒论》第{num}条、教材解析及各家注（{names}）：\n\n{ctx}\n\n"
                "教材（伤寒论选读）的提要与解析已直接展示给学生，请勿重复概括病机。\n"
                "请完成两件事：\n"
                "①【各家侧重】分条比较各注家的解读侧重（每家一行，标明医家名，指出其独特视角）；\n"
                "②【注家纵横】用 3-4 句话对各注家做概括比较：按各家对本条的学术观点与思想特点归组"
                "（观点相近者为一组，不按学派门户分），点明本条注解上的核心分歧与互补；"
                "若某家与教材解析明显互补或有出入，一并点出。\n"
                "格式用小标题+要点，控制在 450 字内。所有论断须基于上述材料。")
    else:
        user = (f"以下是《伤寒论》第{num}条及各家注（{names}）：\n\n{ctx}\n\n"
                "请完成三件事：\n"
                "①【病机要点】用 2-3 句话概括本条条文的核心病机与要点；\n"
                "②【各家侧重】分条比较各注家的解读侧重（每家一行，标明医家名，指出其独特视角）；\n"
                "③【注家纵横】用 3-4 句话对各注家做概括比较：按各家对本条的学术观点与思想特点归组"
                "（观点相近者为一组，不按学派门户分），点明本条注解上的核心分歧与互补。\n"
                "格式用小标题+要点，控制在 500 字内。所有论断须基于上述材料。")
    msgs = [{"role": "system", "content": SUMMARY_SYS}, {"role": "user", "content": user}]
    return StreamingResponse(ds_stream(msgs), media_type="text/plain; charset=utf-8")

def retrieve(q, k=6):
    """简易检索：从条文/注文中取与查询词相关的片段作 AI 上下文。"""
    con = db()
    like = f"%{q}%"
    hits = []
    for r in con.execute("SELECT num,text FROM passages WHERE text LIKE ? ORDER BY seq LIMIT ?", (like, k)):
        hits.append(f"【原文·第{r['num']}条】{r['text']}")
    for r in con.execute("SELECT passage_num,commentator,text FROM comments WHERE text LIKE ? ORDER BY seq LIMIT ?", (like, k)):
        hits.append(f"【{r['commentator']}·第{r['passage_num']}条注】{r['text'][:220]}")
    con.close()
    return hits

CHAT_SYS = (
    "你是《伤寒论》教学知识库的问答助手，面向中医院校学生。回答规则："
    "①涉及条文原文、注家观点时，必须依据【库内检索材料】，并标注出处（第N条/医家）；材料没有就说'库内未检索到'。"
    "②医史背景、名词常识等库外通识可作答，但需注明'（库外常识）'。"
    "③不提供临床诊疗、处方剂量等建议，引导回到经典学习。用简体中文，启发式，简明。")

@app.post("/api/ai/chat")
def ai_chat(payload: dict = Body(...)):
    if not DS_KEY:
        return JSONResponse({"error": "未配置 DeepSeek API Key"}, status_code=400)
    q = (payload.get("q") or "").strip()
    history = payload.get("history", [])[-6:]
    cur_num = payload.get("num")
    if not q:
        return JSONResponse({"error": "空问题"}, status_code=400)
    # 检索增强
    kws = q
    hits = retrieve(kws)
    ctx_parts = []
    if cur_num:
        pc, _ = passage_context(int(cur_num))
        if pc:
            ctx_parts.append("【当前正在阅读】\n" + pc[:1500])
    if hits:
        ctx_parts.append("【检索到的相关材料】\n" + "\n".join(hits))
    ctx = "\n\n".join(ctx_parts) if ctx_parts else "（本次未检索到直接相关的库内材料）"
    msgs = [{"role": "system", "content": CHAT_SYS}]
    for h in history:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"][:1500]})
    msgs.append({"role": "user", "content": f"{ctx}\n\n———\n学生提问：{q}"})
    return StreamingResponse(ds_stream(msgs), media_type="text/plain; charset=utf-8")

@app.get("/")
def index():
    # 本地教学原型更新频繁，禁止浏览器复用旧版入口页。
    # CSS/JS 均内嵌于 index.html，入口页刷新即可获得完整最新版界面。
    return FileResponse(
        os.path.join(STATIC, "index.html"),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

app.mount("/", StaticFiles(directory=STATIC, check_dir=False), name="static")
