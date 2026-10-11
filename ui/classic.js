
const CMT_STYLE={
  "成无己":{c:"var(--cheng)",book:"金·注解伤寒论",bid:"cheng"},
  "方有执":{c:"var(--fang)",book:"明·伤寒论条辨",bid:"fang"},
  "喻昌":{c:"var(--yu)",book:"清·尚论篇",bid:"yu"},
  "张志聪":{c:"var(--zzc)",book:"清·伤寒论集注",bid:"zzc"},
  "张锡驹":{c:"var(--zhi)",book:"清·伤寒论直解",bid:"zhi"},
  "陈修园":{c:"var(--chen)",book:"清·伤寒论浅注",bid:"chen"},
  "柯韵伯":{c:"var(--ke)",book:"清·伤寒论注",bid:"ke"},
  "尤在泾":{c:"var(--you)",book:"清·伤寒贯珠集",bid:"you"},
  "吴谦":{c:"var(--wu)",book:"清·医宗金鉴",bid:"wu"},
};
// ===== 界面偏好（风格/字号/注家筛选，localStorage 记忆） =====
(function(){
  let t=localStorage.getItem('kb_theme')||'';
  const f=localStorage.getItem('kb_fz')||'';
  if(t==='xuan'){t='classic';localStorage.setItem('kb_theme',t);}
  const syncBrand=theme=>{document.getElementById('brandTitle').textContent=theme?'傷寒論九家注':'伤寒论九家注';};
  if(t)document.documentElement.dataset.theme=t;
  if(f)document.documentElement.dataset.fz=f;
  syncBrand(t);
  const ts=document.getElementById('themeSel'), fs=document.getElementById('fzSel');
  ts.value=t; fs.value=f;
  ts.onchange=()=>{ if(ts.value)document.documentElement.dataset.theme=ts.value;
    else delete document.documentElement.dataset.theme; syncBrand(ts.value); localStorage.setItem('kb_theme',ts.value); };
  fs.onchange=()=>{ if(fs.value)document.documentElement.dataset.fz=fs.value;
    else delete document.documentElement.dataset.fz; localStorage.setItem('kb_fz',fs.value); };
})();
let cmtOff=new Set(JSON.parse(localStorage.getItem('kb_cmtoff')||'[]'));
function saveCmtOff(){ localStorage.setItem('kb_cmtoff',JSON.stringify([...cmtOff])); }
function applyCmtFilter(){
  document.querySelectorAll('#content .cmt[data-cmt]').forEach(cd=>{
    cd.style.display=cmtOff.has(cd.dataset.cmt)?'none':''; });
}
function cmtBar(){
  const bar=document.createElement('div'); bar.className='cmtbar';
  const lab=document.createElement('span'); lab.className='lab'; lab.textContent='注家'; bar.appendChild(lab);
  Object.keys(CMT_STYLE).forEach(n=>{
    const st=CMT_STYLE[n];
    const ch=document.createElement('div');
    ch.className='cmtchip'+(cmtOff.has(n)?' off':'');
    ch.innerHTML='<span class="cdot" style="background:'+st.c+'"></span>'+n;
    ch.title=(cmtOff.has(n)?'点击显示 ':'点击隐藏 ')+st.book;
    ch.onclick=()=>{ if(cmtOff.has(n))cmtOff.delete(n); else cmtOff.add(n);
      ch.classList.toggle('off',cmtOff.has(n)); saveCmtOff(); applyCmtFilter(); };
    bar.appendChild(ch); });
  const all=document.createElement('div'); all.className='cmtchip'; all.style.fontWeight='600';
  all.textContent='全部'; all.title='显示全部九家';
  all.onclick=()=>{ cmtOff.clear(); saveCmtOff();
    bar.querySelectorAll('.cmtchip').forEach(x=>x.classList.remove('off')); applyCmtFilter(); };
  bar.appendChild(all);
  return bar;
}
document.getElementById('cmtbarbox').appendChild(cmtBar());
function syncCmtbar(){ document.getElementById('cmtbarbox').style.display=(VIEW==='jizhu')?'':'none'; }
let META=null,VIEW="jizhu",curChapter="",passages=[],curNum=null,AION=false,busy=false,chatHistory=[];
let books=[],curBook=null,bookCache={},pendingLocate=null,curLocateText=null;
let curGroup=null,NUM2GROUP={};
const $=s=>document.querySelector(s);
const el=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};
async function api(u){const r=await fetch(u);if(!r.ok)throw new Error(u+' '+r.status);return r.json();}
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function norm(s){return (s||'').replace(/[^一-鿿]/g,'');}

// 主工作区：目录折叠、学习助手左右拖动调宽、localStorage 记忆
const WORKSPACE_LAYOUT_KEY='kb_workspace_layout_v1';
const WORKSPACE_LAYOUT_DEFAULT={sideCollapsed:false,aiWidth:402};
const SIDE_WIDTH=250,SIDE_COLLAPSED_WIDTH=42,AI_WIDTH_MIN=320,AI_WIDTH_MAX=720,CENTER_WIDTH_MIN=540;
let workspaceLayout=loadWorkspaceLayout(),aiWidthDragging=false;
function loadWorkspaceLayout(){
  try{const x=JSON.parse(localStorage.getItem(WORKSPACE_LAYOUT_KEY)||'{}');return {
    sideCollapsed:!!x.sideCollapsed,
    aiWidth:Number.isFinite(x.aiWidth)?x.aiWidth:WORKSPACE_LAYOUT_DEFAULT.aiWidth};}
  catch(_){return {...WORKSPACE_LAYOUT_DEFAULT};}
}
function saveWorkspaceLayout(){try{localStorage.setItem(WORKSPACE_LAYOUT_KEY,JSON.stringify(workspaceLayout));}catch(_){}}
function clampAIWidth(width){
  const layout=$('.layout'),sideWidth=workspaceLayout.sideCollapsed?SIDE_COLLAPSED_WIDTH:SIDE_WIDTH;
  const available=Math.max(AI_WIDTH_MIN,layout.clientWidth-sideWidth-CENTER_WIDTH_MIN-9);
  return Math.round(Math.min(AI_WIDTH_MAX,available,Math.max(AI_WIDTH_MIN,width)));
}
function applyWorkspaceLayout(save=false){
  const layout=$('.layout'),sideShell=$('#sideShell'),sideToggle=$('#sideToggle'),ai=$('#aipanel'),divider=$('#aiWidthDivider');
  sideShell.classList.toggle('collapsed',workspaceLayout.sideCollapsed);
  layout.classList.toggle('side-collapsed',workspaceLayout.sideCollapsed);
  sideToggle.textContent=workspaceLayout.sideCollapsed?'展开目录':'收起';
  sideToggle.title=workspaceLayout.sideCollapsed?'展开篇章与条文目录':'折叠篇章与条文目录';
  sideToggle.setAttribute('aria-expanded',String(!workspaceLayout.sideCollapsed));
  // 窄屏仅临时压缩实际显示宽度，不覆盖用户记忆的首选宽度；窗口放大后自动恢复。
  const renderedAIWidth=clampAIWidth(workspaceLayout.aiWidth);
  ai.style.width=renderedAIWidth+'px';
  divider.setAttribute('aria-valuenow',String(renderedAIWidth));
  divider.setAttribute('aria-valuetext','学习助手宽度 '+renderedAIWidth+' 像素');
  if(save)saveWorkspaceLayout();
}
function setAIWidthFromX(clientX){
  const rect=$('.layout').getBoundingClientRect();
  workspaceLayout.aiWidth=clampAIWidth(rect.right-clientX);
  applyWorkspaceLayout();
}
function initWorkspaceLayout(){
  const layout=$('.layout'),divider=$('#aiWidthDivider');
  applyWorkspaceLayout();
  $('#sideToggle').onclick=()=>{workspaceLayout.sideCollapsed=!workspaceLayout.sideCollapsed;applyWorkspaceLayout(true);};
  divider.addEventListener('pointerdown',e=>{
    aiWidthDragging=true;divider.classList.add('dragging');layout.classList.add('ai-width-dragging');
    divider.setPointerCapture(e.pointerId);e.preventDefault();
  });
  divider.addEventListener('pointermove',e=>{if(aiWidthDragging)setAIWidthFromX(e.clientX);});
  const finish=e=>{if(!aiWidthDragging)return;aiWidthDragging=false;divider.classList.remove('dragging');layout.classList.remove('ai-width-dragging');
    if(divider.hasPointerCapture&&divider.hasPointerCapture(e.pointerId))divider.releasePointerCapture(e.pointerId);saveWorkspaceLayout();};
  divider.addEventListener('pointerup',finish);divider.addEventListener('pointercancel',finish);
  divider.addEventListener('dblclick',()=>{workspaceLayout.aiWidth=WORKSPACE_LAYOUT_DEFAULT.aiWidth;applyWorkspaceLayout(true);});
  divider.addEventListener('keydown',e=>{
    if(e.key==='ArrowLeft'||e.key==='ArrowRight'){
      workspaceLayout.aiWidth+=e.key==='ArrowLeft'?24:-24;applyWorkspaceLayout(true);e.preventDefault();
    }else if(e.key==='Home'){workspaceLayout.aiWidth=WORKSPACE_LAYOUT_DEFAULT.aiWidth;applyWorkspaceLayout(true);e.preventDefault();}
  });
  window.addEventListener('resize',()=>applyWorkspaceLayout());
}

// 学习助手上下分区：拖动调节、双向折叠、localStorage 记忆
const AI_LAYOUT_KEY='kb_ai_layout_v1',AI_LAYOUT_DEFAULT={ratio:.42,guideFolded:false,chatFolded:false};
let aiLayout=loadAILayout(),aiDragging=false;
function loadAILayout(){
  try{const x=JSON.parse(localStorage.getItem(AI_LAYOUT_KEY)||'{}');return {
    ratio:Number.isFinite(x.ratio)?Math.min(.75,Math.max(.2,x.ratio)):AI_LAYOUT_DEFAULT.ratio,
    guideFolded:!!x.guideFolded,chatFolded:!!x.chatFolded};}
  catch(_){return {...AI_LAYOUT_DEFAULT};}
}
function saveAILayout(){try{localStorage.setItem(AI_LAYOUT_KEY,JSON.stringify(aiLayout));}catch(_){}}
function guideVisible(){return getComputedStyle($('#guide')).display!=='none';}
function clampAIRatio(ratio){
  const panel=$('#aipanel'),head=panel.querySelector('.ai-head'),divider=$('#aiDivider'),total=panel.clientHeight;
  if(!total)return Math.min(.75,Math.max(.2,ratio));
  const usable=Math.max(1,total-head.offsetHeight-divider.offsetHeight);
  const minGuide=Math.min(120,usable*.35),minChat=Math.min(170,usable*.42);
  const maxGuide=Math.max(minGuide,total-head.offsetHeight-divider.offsetHeight-minChat);
  return Math.min(maxGuide/total,Math.max(minGuide/total,ratio));
}
function applyAILayout(save=false){
  const guide=$('#guide'),chat=$('#chatSection'),divider=$('#aiDivider');
  if(aiLayout.guideFolded&&aiLayout.chatFolded)aiLayout.chatFolded=false;
  guide.classList.toggle('folded',aiLayout.guideFolded);
  chat.classList.toggle('folded',aiLayout.chatFolded);
  $('#guideToggle').textContent=aiLayout.guideFolded?'展开导读':'收起导读';
  $('#guideToggle').setAttribute('aria-expanded',String(!aiLayout.guideFolded));
  $('#chatToggle').textContent=aiLayout.chatFolded?'展开问答':'收起问答';
  $('#chatToggle').setAttribute('aria-expanded',String(!aiLayout.chatFolded));
  divider.classList.toggle('hidden',!guideVisible()||aiLayout.guideFolded||aiLayout.chatFolded);
  if(aiLayout.guideFolded)guide.style.flex='0 0 38px';
  else if(aiLayout.chatFolded)guide.style.flex='1 1 auto';
  else {aiLayout.ratio=clampAIRatio(aiLayout.ratio);guide.style.flex='0 0 '+(aiLayout.ratio*100).toFixed(1)+'%';}
  if(save)saveAILayout();
}
function resetAILayout(){aiLayout={...AI_LAYOUT_DEFAULT};applyAILayout(true);}
function setAIRatioFromY(clientY){
  const panel=$('#aipanel'),head=panel.querySelector('.ai-head'),divider=$('#aiDivider');
  const rect=panel.getBoundingClientRect(),total=panel.clientHeight;
  if(total<=0)return;
  const y=clientY-rect.top-head.offsetHeight;
  aiLayout.ratio=clampAIRatio(y/total);
  applyAILayout();
}
function syncAILayout(){requestAnimationFrame(()=>applyAILayout());}
function initAILayout(){
  const divider=$('#aiDivider'); applyAILayout();
  divider.addEventListener('pointerdown',e=>{if(divider.classList.contains('hidden'))return;
    aiDragging=true;divider.classList.add('dragging');divider.setPointerCapture(e.pointerId);e.preventDefault();});
  divider.addEventListener('pointermove',e=>{if(aiDragging)setAIRatioFromY(e.clientY);});
  const finish=e=>{if(!aiDragging)return;aiDragging=false;divider.classList.remove('dragging');
    if(divider.hasPointerCapture&&divider.hasPointerCapture(e.pointerId))divider.releasePointerCapture(e.pointerId);saveAILayout();};
  divider.addEventListener('pointerup',finish);divider.addEventListener('pointercancel',finish);
  divider.addEventListener('dblclick',()=>{aiLayout.ratio=AI_LAYOUT_DEFAULT.ratio;applyAILayout(true);});
  divider.addEventListener('keydown',e=>{if(e.key==='ArrowUp'||e.key==='ArrowDown'){
    aiLayout.ratio=Math.min(.75,Math.max(.2,aiLayout.ratio+(e.key==='ArrowDown' ? .03 : -.03)));applyAILayout(true);e.preventDefault();
  }else if(e.key==='Home'){aiLayout.ratio=AI_LAYOUT_DEFAULT.ratio;applyAILayout(true);e.preventDefault();}});
  $('#guideToggle').onclick=()=>{aiLayout.guideFolded=!aiLayout.guideFolded;if(aiLayout.guideFolded)aiLayout.chatFolded=false;applyAILayout(true);};
  $('#chatToggle').onclick=()=>{aiLayout.chatFolded=!aiLayout.chatFolded;if(aiLayout.chatFolded)aiLayout.guideFolded=false;applyAILayout(true);};
  $('#aireset').onclick=resetAILayout;
  window.addEventListener('resize',()=>applyAILayout());
}
// 1963人卫版《注解伤寒论》校勘夹注（赵本/医统本/玉函经），全形式清单（据语料枚举验证）：
// 注/云：“…”｜“…”作“…”｜“…”上/下有“…”N字｜(句下)?作/无/有/去(方中)?“…”N字｜无此N字｜从“…”以下皆无｜作+数量或单字｜有…方云：…｜芩、连互易
const KJZ=new RegExp('(?:“[^”]{1,4}”)?(?:赵本、?医统本|赵本|医统本|《玉函经?》)'+
  '(?:(?:注|云)：“[^”]*”'+
  '|“[^”]*”作“[^”]*”'+
  '|“[^”]*”[上下]有“[^”]*”(?:[一二三四五六七八九十]*字)?'+
  '|[并皆]?(?:句下)?(?:一作|[作无有去])(?:方中)?“[^”]*”(?:[一二三四五六七八九十]*字)?'+
  '|[并皆]?无此[一二三四五六七八九十]*字'+
  '|从“[^”]*”以下皆无。?'+
  '|[并皆]?作(?:[一二三四五六七八九十]+[两个枚升斤铢合钱]|[一-鿿])'+
  '|有[^“”，。]{2,12}方云：.*'+
  '|芩、连互易)','g');
// 编者按（三家注编者所加互参指引）：按用户裁定去「编者按」三字，条号做成可点击跳转
function edref(h){
  return h.replace(/（编者按：([^）]*)）/g,function(_,c){
    c=c.replace(/^(上条|前条|后条|首条|上文|上节|此?[二三]条|前二条|上二条)指/,'指');
    c=c.replace(/第?((?:\d{1,3})(?:[、和]\d{1,3})*)条/g,function(_,list){
      return list.split(/[、和]/).map(n=>'<span class="pref" data-num="'+n+'">第'+n+'条</span>').join('、');
    });
    return '（<span class="edref">'+c+'</span>）';
  });
}
// 原文格式化：校勘注→小字；底本分段号〔n〕已无对应注文序号，直接不显示
function fmtOrig(s){return edref(esc(s)).replace(KJZ,'<span class="kaozhu">$&</span>').replace(/〔\d+〕/g,'');}
// 纯净原文（去校勘注与分段号）：用于目录摘要、原书定位
function stripNotes(s){return (s||'').replace(KJZ,'').replace(/〔\d+〕/g,'');}
// 原书段落格式化：括号校勘（赵本/医统本/熊校记…）→小字；直解 (n) 注释引用→上标
const ONOTE=/（[^（）]{0,40}?(?:赵本|医统本|熊校记|玉函)[^（）]*）/g;
function fmtOrigBook(s){return esc(s).replace(ONOTE,'<span class="kaozhu">$&</span>').replace(/\((\d{1,3})\)/g,'<span class="noteref">($1)</span>');}
function fmtAI(t){return esc(t).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/\n/g,'<br>');}

async function init(){
  try{
    initWorkspaceLayout();
    initAILayout();
    META=await api('/api/meta'); AION=META.ai;
    (META.groups||[]).forEach(g=>g.nums.forEach(n=>{NUM2GROUP[n]=g;}));
    $('#content').addEventListener('click',e=>{const t=e.target.closest('.pref');
      if(t){const n=parseInt(t.dataset.num); if(n)openPassage(n);}});
    $('#aist').textContent=AION?'在线模型已接入':'AI 未配置';
    passages=await api('/api/passages');
    books=await api('/api/origbooks');
    if(!AION){ $('.ai-input').style.display='none'; $('#regen').style.display='none';
      $('#chat').innerHTML='<div class="ai-off">尚未配置在线模型。请在“设置与备份”填写服务地址、模型和密钥。</div>'; }
    renderSide(); if(passages.length) openPassage(passages[0].num);
  }catch(e){ $('#content').innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; }
}

function setTab(v){document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.view===v));}

function setView(v){
  VIEW=v; setTab(v); renderSide();
  if(v==='jizhu') openPassage(curNum||passages[0].num);
  else openOrig(curBook||(books[0]&&books[0].book_id));
}

function renderSide(){
  const side=$('#side'); side.innerHTML='';
  if(VIEW==='jizhu'){
    side.appendChild(el('h3',null,'篇章'));
    const all=el('div','chapline'+(curChapter===''?' on':''),'全部 · 398 条');
    all.onclick=()=>{curChapter='';renderSide();}; side.appendChild(all);
    META.chapters.forEach(ch=>{ const d=el('div','chapline'+(curChapter===ch?' on':''),ch);
      d.onclick=()=>{curChapter=ch;renderSide();}; side.appendChild(d); });
    side.appendChild(el('h3',null,'条文'));
    passages.filter(p=>!curChapter||p.chapter===curChapter).forEach(p=>{
      const on=(p.num===curNum)||(curGroup&&curGroup.nums.indexOf(p.num)>=0);
      const it=el('div','pitem'+(on?' on':''));
      it.appendChild(el('span','n',p.num));
      it.appendChild(el('span','t',stripNotes(p.text.replace(/（\d+）\s*$/,'')).slice(0,15)));
      if(NUM2GROUP[p.num]){const gm=el('span','gmark','⛓');gm.title='关联组：'+NUM2GROUP[p.num].label;it.appendChild(gm);}
      it.onclick=()=>openPassage(p.num); side.appendChild(it); });
  }else{
    side.appendChild(el('h3',null,'选择注家原书'));
    const chips=el('div','bookchips');
    books.forEach(b=>{ const c=el('div','bookchip'+(b.book_id===curBook?' on':''),b.author);
      c.title=b.book_name; c.onclick=()=>openOrig(b.book_id); chips.appendChild(c); });
    side.appendChild(chips);
    const bk=bookCache[curBook];
    if(bk){ side.appendChild(el('h3',null,bk.book_name+' · 卷次'));
      bk.chapters.forEach(ch=>{ const d=el('div','chapline',ch.title);
        d.onclick=()=>{const t=document.getElementById('ochap-'+ch.idx); if(t){$('.main').scrollTo({top:t.offsetTop-70,behavior:'smooth'});}};
        side.appendChild(d); }); }
  }
}

function renderPassageInto(c,d){
  const p=d.passage;
  c.appendChild(el('div','chapter-badge','《伤寒论》'+p.chapter+' · 第 '+p.num+' 条'));
  const pt=el('div','ptext song'); pt.innerHTML='<span class="num">'+p.num+'</span>'+fmtOrig(p.text.replace(/（\d+）\s*$/,''));
  if(d.appendix.length){ const fj=el('div','fangji');
    d.appendix.forEach(a=>{ a.split('\n').forEach(line=>{ if(!line.trim())return;
      const isHead=line.trim().length<=12&&/方$/.test(line.trim());
      fj.insertAdjacentHTML('beforeend','<div class="fpara'+(isHead?' fhead':'')+'">'+fmtOrig(line)+'</div>'); }); });
    pt.appendChild(fj); }
  c.appendChild(pt);
  const cleanText=stripNotes(p.text.replace(/（\d+）\s*$/,''));
  d.commentators.forEach(g=>{
    const st=CMT_STYLE[g.commentator]||{c:'#888',book:'',bid:null};
    const card=el('div','cmt'); card.dataset.cmt=g.commentator;
    const head=el('div','cmt-head');
    head.appendChild(el('span','dot')).style.background=st.c;
    const nm=el('span','name',g.commentator); nm.style.color=st.c; head.appendChild(nm);
    head.appendChild(el('span','book',st.book));
    if(st.bid){ const ol=el('span','origlink','📖 原书');
      ol.onclick=(e)=>{e.stopPropagation();openOrig(st.bid,cleanText);}; head.appendChild(ol); }
    if(g.flag==='review') head.appendChild(el('span','badge review','自动对齐·待审'));
    else if(g.flag==='aligned') head.appendChild(el('span','badge','自动对齐'));
    head.appendChild(el('span','arrow','▾'));
    head.onclick=()=>card.classList.toggle('collapsed'); card.appendChild(head);
    const body=el('div','cmt-body song');
    g.segments.forEach(s=>{ const seg=el('div','seg');
      s.text.split('\n').forEach(line=>{ if(!line.trim())return;
        seg.insertAdjacentHTML('beforeend','<div class="cpara">'+fmtOrig(line)+'</div>'); });
      body.appendChild(seg); });
    card.appendChild(body); c.appendChild(card);
  });
}

async function openPassage(num){
  if(num==null)return; curNum=num; curGroup=null; VIEW='jizhu'; setTab('jizhu'); renderSide();
  const c=$('#content'); c.innerHTML='<div class="empty">加载中…</div>';
  let d; try{ d=await api('/api/passage/'+num); }catch(e){ c.innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; return; }
  c.innerHTML='';
  if(d.group){ const g=d.group; const others=g.nums.filter(n=>n!==num);
    const bar=el('div','grpbar');
    bar.innerHTML='⛓ 本条与<b>第'+others.join('、')+'条</b>宜合参 · '+esc(g.label)+'｜'+esc(g.reason);
    const btn=el('button',null,'连读全组'); btn.onclick=()=>openGroup(g); bar.appendChild(btn);
    c.appendChild(bar); }
  syncCmtbar();
  renderPassageInto(c,d);
  applyCmtFilter();
  curLocateText=stripNotes(d.passage.text.replace(/（\d+）\s*$/,''));
  renderTbnote(d.textbook);
  $('.main').scrollTop=0;
  if(AION) doSummary(num);
}

// 教材解析块（选读十四五优先；无则 AI 兜底生成完整导读）
let curTb=null;
function renderTbnote(tb){
  curTb=tb||null;
  const box=$('#tbnote');
  if(!tb){ box.style.display='none'; box.innerHTML=''; if(!AION)$('#guide').style.display='none'; syncAILayout(); return; }
  let h='<div class="tbn"><div class="tbh">📘 教材解析 · '+esc(tb.source||'')+
    (tb.nums&&tb.nums.length>1?'（第'+tb.nums.join('、')+'条合释）':'')+'</div>';
  if(tb.tiyao)h+='<b>提要：</b>'+esc(tb.tiyao)+'<br>';
  if(tb.jiexi)h+='<b>解析：</b>'+esc(tb.jiexi)+'<br>';
  if(tb.bingji)h+='<b>病机：</b>'+esc(tb.bingji)+'<br>';
  if(tb.zhifa)h+='<b>治法：</b>'+esc(tb.zhifa);
  h+='</div>';
  box.innerHTML=h; box.style.display='block'; $('#guide').style.display='block'; syncAILayout();
}

// 合参连读：组内各条依次完整显示
async function openGroup(g){
  VIEW='jizhu'; setTab('jizhu'); curGroup=g; curNum=g.nums[0]; renderSide();
  const c=$('#content'); c.innerHTML='<div class="empty">加载中…</div>';
  let ds; try{ ds=await Promise.all(g.nums.map(n=>api('/api/passage/'+n))); }
  catch(e){ c.innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; return; }
  c.innerHTML='';
  const bar=el('div','grpbar');
  bar.innerHTML='⛓ 合参连读：<b>第'+g.nums.join('、')+'条</b> · '+esc(g.label)+'｜'+esc(g.reason);
  const btn=el('button',null,'退出连读'); btn.onclick=()=>openPassage(g.nums[0]); bar.appendChild(btn);
  c.appendChild(bar);
  syncCmtbar();
  ds.forEach((d,i)=>{ if(i>0)c.appendChild(el('hr','gsep')); renderPassageInto(c,d); });
  applyCmtFilter();
  curLocateText=stripNotes(ds[0].passage.text.replace(/（\d+）\s*$/,''));
  curTb=null; $('#tbnote').style.display='none';
  $('.main').scrollTop=0;
  if(AION) doGroupSummary(g);
}

async function openOrig(bid, locateText){
  if(!bid)return; curBook=bid; VIEW='orig'; setTab('orig'); syncCmtbar();
  // 不显式传定位文本时，默认记忆并定位到集注视图当前选中的条文
  pendingLocate=(locateText===undefined?curLocateText:locateText)||null;
  const c=$('#content');
  if(!bookCache[bid]){ c.innerHTML='<div class="empty">加载原书…</div>';
    try{ bookCache[bid]=await api('/api/origbook/'+bid); }catch(e){ c.innerHTML='<div class="empty">原书加载失败</div>'; return; } }
  renderSide();
  const bk=bookCache[bid]; c.innerHTML='';
  const hd=el('div','obook-head');
  hd.innerHTML='<span class="bn song">'+esc(bk.book_name)+'</span><span class="au">'+esc(bk.author)+'</span><div class="src">原书顺序阅读 · 来源：'+esc(bk.source||'')+'</div>';
  c.appendChild(hd);
  bk.chapters.forEach(ch=>{
    const ct=el('div','ochap-title song',esc(ch.title)); ct.id='ochap-'+ch.idx; c.appendChild(ct);
    ch.paras.forEach(pa=>{ const cls={h:' h',tw:' tw',f:' f',fn:' fn'}[pa.tag]||'';
      const d=el('div','opara song'+cls,fmtOrigBook(pa.text)); d.dataset.g=pa.g; c.appendChild(d); });
  });
  $('.main').scrollTop=0;
  if(pendingLocate) locateInBook(pendingLocate);
}

function locateInBook(text){
  const key=norm(text).slice(0,10);
  if(key.length<4)return;
  const paras=document.querySelectorAll('.opara');
  let hit=null;
  for(const el of paras){ if(norm(el.textContent).indexOf(key.slice(0,8))>=0){hit=el;break;} }
  if(!hit){ // 放宽到前6字
    const k6=key.slice(0,6);
    for(const el of paras){ if(norm(el.textContent).indexOf(k6)>=0){hit=el;break;} } }
  document.querySelectorAll('.opara.hit').forEach(e=>e.classList.remove('hit'));
  if(hit){ hit.classList.add('hit'); hit.scrollIntoView({block:'center'}); }
  else { $('.main').scrollTop=0; }
}

// AI 流式
async function streamAI(url,payload,onChunk){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(!r.ok){ let t='';try{t=(await r.json()).error||'';}catch(_){}; throw new Error(t||('HTTP '+r.status)); }
  const reader=r.body.getReader(),dec=new TextDecoder(); let acc='';
  while(true){ const {done,value}=await reader.read(); if(done)break; acc+=dec.decode(value,{stream:true}); if(acc.includes('[SHANGHAN_ERROR]')){await reader.cancel();throw new Error(acc.split('[SHANGHAN_ERROR]').pop());} onChunk(acc,false); }
  onChunk(acc,true);
}
// 导读按条缓存：切换条文再切回不重复生成；生成中切走再切回接续显示
const summaryCache={};
async function doSummary(num,force){
  const g=$('#guide'),b=$('#gbody'); g.style.display='block'; syncAILayout();
  const wait=curTb?'正在生成注家比较…':'正在生成本条导读…';
  const sc=summaryCache[num];
  if(!force&&sc){ b.innerHTML=sc.html||('<span style="color:#89a">'+wait+'</span>'); if(sc.loading||sc.done)return; }
  const gen=(sc?sc.gen:0)+1;
  summaryCache[num]={gen,loading:true,done:false,html:''};
  b.innerHTML='<span style="color:#89a">'+wait+'</span>';
  try{
    await streamAI('/api/ai/summary',{num},(txt,fin)=>{
      const s=summaryCache[num]; if(!s||s.gen!==gen)return;
      s.html=fmtAI(txt); if(fin){s.done=true;s.loading=false;}
      if(num===curNum&&!curGroup) b.innerHTML=s.html;
    });
  }catch(e){
    const s=summaryCache[num]; if(s&&s.gen===gen)delete summaryCache[num];
    if(num===curNum&&!curGroup) b.innerHTML='<span style="color:#a55">导读生成失败：'+esc(e.message)+'</span>';
  }
}
// 合参导读：按组缓存
async function doGroupSummary(g,force){
  const key='g'+g.nums.join('-');
  const gd=$('#guide'),b=$('#gbody'); gd.style.display='block'; syncAILayout();
  const sc=summaryCache[key];
  if(!force&&sc){ b.innerHTML=sc.html||'<span style="color:#89a">正在生成合参导读…</span>'; if(sc.loading||sc.done)return; }
  const gen=(sc?sc.gen:0)+1;
  summaryCache[key]={gen,loading:true,done:false,html:''};
  b.innerHTML='<span style="color:#89a">正在生成合参导读…</span>';
  try{
    await streamAI('/api/ai/summary',{nums:g.nums,label:g.label},(txt,fin)=>{
      const s=summaryCache[key]; if(!s||s.gen!==gen)return;
      s.html=fmtAI(txt); if(fin){s.done=true;s.loading=false;}
      if(curGroup===g) b.innerHTML=s.html;
    });
  }catch(e){
    const s=summaryCache[key]; if(s&&s.gen===gen)delete summaryCache[key];
    if(curGroup===g) b.innerHTML='<span style="color:#a55">合参导读生成失败：'+esc(e.message)+'</span>';
  }
}
async function sendChat(){
  if(busy||!AION)return; const inp=$('#qinput'),q=inp.value.trim(); if(!q)return;
  inp.value=''; busy=true; $('#sendbtn').disabled=true;
  const chat=$('#chat'); const hint=chat.querySelector('.hint'); if(hint)hint.remove();
  chat.appendChild(el('div','bubble u',esc(q)));
  const ab=el('div','bubble a','<span style="color:#89a">思考中…</span>'); chat.appendChild(ab); chat.scrollTop=chat.scrollHeight;
  try{ await streamAI('/api/ai/chat',{q,history:chatHistory,num:VIEW==='jizhu'?curNum:null},(txt)=>{ ab.innerHTML=fmtAI(txt); chat.scrollTop=chat.scrollHeight; });
    chatHistory.push({role:'user',content:q}); chatHistory.push({role:'assistant',content:ab.textContent});
    if(chatHistory.length>12)chatHistory=chatHistory.slice(-12);
  }catch(e){ ab.innerHTML='<span style="color:#a55">出错：'+esc(e.message)+'</span>'; }
  busy=false; $('#sendbtn').disabled=false;
}

// 检索
let curKind='';
async function doSearch(forceKind){
  const q=$('#q').value.trim(); if(q.length<1){alert('请输入检索词');return;}
  if(forceKind!==undefined)curKind=forceKind;
  $('#overlay').classList.add('on'); renderFilters();
  const box=$('#sresults'); box.innerHTML='<div class="empty" style="margin-top:20px">检索中…</div>';
  let d; try{ d=await api('/api/search?q='+encodeURIComponent(q)+'&kind='+curKind); }catch(e){ box.innerHTML='<div class="empty">检索出错</div>'; return; }
  box.innerHTML='';
  if(!d.results||!d.results.length){ box.innerHTML='<div class="empty" style="margin-top:30px">'+(d.note||'无匹配结果')+'</div>'; return; }
  box.appendChild(el('div',null,'<div style="font-size:12px;color:var(--ink2);margin:6px 0">共 '+d.count+' 条'+(d.truncated?'（前 '+d.results.length+' 条）':'')+'</div>'));
  d.results.forEach(r=>{
    const kn={passage:'条文',comment:'注文',zhijie:'直解'}[r.kind]||r.kind;
    const meta=r.kind==='zhijie'?('直解 · '+r.chapter):(kn+(r.commentator?' · '+r.commentator:'')+' · 第'+r.ref+'条');
    const item=el('div','sres');
    item.appendChild(el('div','meta',meta));
    item.appendChild(el('div','snip',esc(r.snip).replace(/\[\[/g,'<mark>').replace(/\]\]/g,'</mark>')));
    item.onclick=()=>{ $('#overlay').classList.remove('on');
      if(r.kind==='zhijie'){ openOrig('zhi', r.snip.replace(/\[\[|\]\]|…/g,'')); } else { openPassage(parseInt(r.ref)); } };
    box.appendChild(item);
  });
}
function renderFilters(){ const f=$('#filters'); f.innerHTML='';
  [['','全部'],['passage','条文'],['comment','注文'],['zhijie','直解']].forEach(([k,n])=>{
    const c=el('span','chip'+(curKind===k?' on':''),n); c.onclick=()=>doSearch(k); f.appendChild(c); }); }

$('#qbtn').onclick=()=>doSearch();
$('#q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
$('#sendbtn').onclick=sendChat;
$('#qinput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat();}});
$('#regen').onclick=()=>{if(curGroup)doGroupSummary(curGroup,true);else if(curNum)doSummary(curNum,true);};
$('#closex').onclick=()=>$('#overlay').classList.remove('on');
$('#overlay').onclick=e=>{if(e.target.id==='overlay')$('#overlay').classList.remove('on');};
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>setView(t.dataset.view));
init();

window.addEventListener('message',async event=>{
  if(event.source!==parent||event.data?.type!=='model-updated')return;
  META=await api('/api/meta');AION=META.ai;
  $('#aist').textContent=AION?'在线模型已接入':'AI 未配置';
  $('.ai-input').style.display=AION?'':'none';$('#regen').style.display=AION?'':'none';
  if(AION&&$('#chat .ai-off'))$('#chat').innerHTML='';
  for(const key of Object.keys(summaryCache))delete summaryCache[key];
});
