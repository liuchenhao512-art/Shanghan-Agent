'use strict';
let projects = [], activeProject = null, projectData = null, scopeDirty = false, sending = false;
let sendRequest = null, chatSignatures = new Map();
let currentResultFolder = null;
const inputDrafts = new Map();
const newRequestId = () => crypto.randomUUID().replaceAll('-', '');

// 菜单置于页面顶层，避免被可滚动的项目列表裁切；操作绑定点击的项目。
let projectMenuTrigger = null;
const projectMenu = document.createElement('div');
projectMenu.id = 'projectMenu'; projectMenu.className = 'project-menu'; projectMenu.hidden = true;
projectMenu.setAttribute('role', 'menu'); projectMenu.setAttribute('aria-label', '研究专题操作');
projectMenu.innerHTML = '<p class="project-menu-title"></p><button role="menuitem" data-project-action="rename">重命名</button><button role="menuitem" data-project-action="archive">归档</button><div class="project-menu-divider" role="separator"></div><button role="menuitem" data-project-action="delete" class="danger">删除…</button>';
document.body.append(projectMenu);
function closeProjectMenu(returnFocus = false) {
  const trigger = projectMenuTrigger;
  projectMenu.hidden = true; projectMenuTrigger = null;
  if (trigger) { trigger.setAttribute('aria-expanded', 'false'); trigger.closest('.project-row')?.classList.remove('menu-open'); }
  if (returnFocus && trigger?.isConnected) trigger.focus();
}
function openProjectMenu(trigger) {
  if (trigger === projectMenuTrigger) { closeProjectMenu(true); return; }
  closeProjectMenu();
  const project = projects.find(p => p.id === trigger.dataset.projectMenu);
  if (!project) return;
  projectMenuTrigger = trigger;
  trigger.setAttribute('aria-expanded', 'true'); trigger.closest('.project-row').classList.add('menu-open');
  projectMenu.querySelector('.project-menu-title').textContent = project.title;
  projectMenu.hidden = false;
  const rect = trigger.getBoundingClientRect();
  projectMenu.style.left = Math.max(8, Math.min(rect.left, innerWidth - projectMenu.offsetWidth - 8)) + 'px';
  const top = rect.bottom + 5;
  projectMenu.style.top = Math.max(8, top + projectMenu.offsetHeight <= innerHeight - 8 ? top : rect.top - projectMenu.offsetHeight - 5) + 'px';
  projectMenu.querySelector('[role="menuitem"]').focus();
}
function renameResearchProject(id, title) {
  return titleForm('重命名研究专题', title, value => propose('project_update', { id, title: value }));
}
projectMenu.addEventListener('click', async event => {
  const button = event.target.closest('[data-project-action]');
  if (!button || !projectMenuTrigger) return;
  const id = projectMenuTrigger.dataset.projectMenu, project = projects.find(p => p.id === id);
  closeProjectMenu(true);
  if (!project) return;
  try {
    if (button.dataset.projectAction === 'rename') await renameResearchProject(id, project.title);
    else await propose('project_' + button.dataset.projectAction, { id });
  } catch (error) { toast(error.message, true); }
});
projectMenu.addEventListener('keydown', event => {
  const items = [...projectMenu.querySelectorAll('[role="menuitem"]')];
  const index = items.indexOf(document.activeElement);
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next].focus();
  } else if (event.key === 'Escape') { event.preventDefault(); closeProjectMenu(true); }
  else if (event.key === 'Tab') closeProjectMenu(true);
});
document.addEventListener('pointerdown', event => {
  if (!projectMenu.hidden && !projectMenu.contains(event.target) && !projectMenuTrigger?.contains(event.target)) closeProjectMenu();
});
document.addEventListener('scroll', event => { if (!projectMenu.contains(event.target)) closeProjectMenu(); }, true);
window.addEventListener('resize', () => closeProjectMenu());

async function newTopic(openChat = true) {
  const requestId = newRequestId();
  await titleForm(openChat ? '新建研究专题' : '新建知识库', '', async title => {
    const project = await api(openChat ? '/projects' : '/libraries', { title, request_id: requestId });
    if (!openChat) currentLibrary = project.id;
    await refreshLibraries();
    if (openChat) { await selectProject(project.id); await switchWorkspace('research'); }
    closeModal();
    toast((openChat ? '已创建研究专题：' : '已创建知识库：') + project.title);
  }, true);
}
action('#newResearch', () => newTopic(true));

async function refreshResultFolders() {
  const folders = await api('/projects');
  $('#resultFolderList').innerHTML = folders.map(p => '<button class="sidebar-item" data-result-folder="' + p.id + '"><span class="folder-label">▱</span>' + esc(p.title) + '<small>' + p.conversation_count + ' 轮对话 · ' + p.note_count + ' 篇笔记</small></button>').join('') || '<p class="aside-note">研究专题的成果会保存在这里。</p>';
  document.querySelectorAll('[data-result-folder]').forEach(b => b.onclick = () => refreshLibraryContents(b.dataset.resultFolder).catch(e => toast(e.message, true)));
}

async function showArchived(type) {
  const isLibrary = type === 'library';
  const items = await api(isLibrary ? '/libraries?archived=true' : '/projects?archived=true');
  modal(isLibrary ? '已归档的知识库' : '已归档的研究专题', '<p class="muted">归档内容完整保留，不会自动清空。恢复后可继续使用；删除前会列出影响范围。</p>' + (items.map(item => '<div class="folder-item"><div><p>' + esc(item.title) + '</p><small>' + (isLibrary ? item.source_count + ' 份资料' : item.conversation_count + ' 轮对话 · ' + item.note_count + ' 篇笔记') + '</small></div><div class="actions"><button data-archive-view="' + item.id + '">查看</button><button data-archive-restore="' + item.id + '">恢复</button><button data-archive-delete="' + item.id + '" class="quiet">删除</button></div></div>').join('') || empty('暂无归档内容', '在正常列表中选择项目，点击“归档”即可收起。')));
  for (const actionName of ['restore','delete']) document.querySelectorAll('[data-archive-' + actionName + ']').forEach(button => {
    button.onclick = async () => {
      try { const id = button.getAttribute('data-archive-' + actionName); await propose(type + '_' + actionName, { id }); await showArchived(type); }
      catch (error) { toast(error.message, true); }
    };
  });
  document.querySelectorAll('[data-archive-view]').forEach(button => button.onclick = async () => {
    try {
      const id = button.dataset.archiveView;
      if (!isLibrary) { closeModal(); await switchWorkspace('research'); await selectProject(id); return; }
      const sources = await api('/sources?library_id=' + id);
      modal('已归档 · ' + items.find(i => i.id === id).title, sources.map(s => '<button class="search-result" data-archived-source="' + esc(s.id) + '">' + esc(s.title) + '</button>').join('') || '<p>此知识库尚未导入资料。</p>');
      document.querySelectorAll('[data-archived-source]').forEach(b => b.onclick = () => readSource(b.dataset.archivedSource).catch(e => toast(e.message,true)));
    } catch (error) { toast(error.message,true); }
  });
}
action('#archivedLibraries', () => showArchived('library'));
action('#archivedProjects', () => showArchived('project'));

function updateScopeSummary() {
  const choices = [...document.querySelectorAll('.research-scope:checked')];
  $('#scopeSummary').textContent = choices.map(n => n.closest('label').textContent.trim()).join('、') || '仅模型对话';
}
async function refreshScopes(scope) {
  const prior = new Set([...document.querySelectorAll('.research-scope:checked')].map(x => x.value));
  libraries = await api('/libraries');
  const setting = scope || projectData?.scope || { library_ids: [], builtin: true };
  const selected = scopeDirty && !scope ? prior : new Set([...setting.library_ids, ...(setting.builtin ? ['builtin'] : [])]);
  $('#researchScopes').innerHTML = '<label><input class="research-scope" type="checkbox" value="builtin" ' + (selected.has('builtin') ? 'checked' : '') + '>内置经典知识库</label>' + libraries.map(l => '<label><input class="research-scope" type="checkbox" value="' + l.id + '" ' + (selected.has(l.id) ? 'checked' : '') + '>' + esc(l.title) + '</label>').join('');
  document.querySelectorAll('.research-scope').forEach(box => box.onchange = () => { scopeDirty = true; updateScopeSummary(); });
  updateScopeSummary();
}
function renderProjectList() {
  closeProjectMenu();
  $('#projectList').innerHTML = projects.map(p => '<div class="project-row"><button class="sidebar-item ' + (p.id === activeProject ? 'active' : '') + '" data-project="' + p.id + '" title="' + esc(p.title) + '"><span class="project-name"><span class="folder-label" aria-hidden="true">▱</span>' + esc(p.title) + '</span><small>' + p.conversation_count + ' 轮对话 · ' + p.note_count + ' 篇笔记</small></button><button type="button" class="project-menu-trigger" data-project-menu="' + p.id + '" aria-label="' + esc(p.title) + '的更多操作" aria-haspopup="menu" aria-expanded="false" aria-controls="projectMenu" title="更多操作"><span aria-hidden="true">⋯</span></button></div>').join('') || '<p class="aside-note">新建一个专题，开始与经典对话。</p>';
  document.querySelectorAll('#projectList [data-project]').forEach(b => b.onclick = () => selectProject(b.dataset.project).catch(e => toast(e.message, true)));
  document.querySelectorAll('[data-project-menu]').forEach(button => {
    button.onclick = () => openProjectMenu(button);
    button.onkeydown = event => { if (event.key === 'ArrowDown') { event.preventDefault(); openProjectMenu(button); } };
  });
}
async function refreshResearch() {
  projects = await api('/projects'); renderProjectList();
  if (!projects.some(p => p.id === activeProject)) {
    const last = localStorage.getItem('research-project');
    const next = projects.find(p => p.id === last) || projects[0];
    if (next) await selectProject(next.id);
    else { activeProject = null; projectData = null; renderChat(null, true); }
  } else if (activeWorkspace === 'research') {
    await renderProject(); startPolling();
  }
}
async function selectProject(id) {
  closeProjectMenu();
  if (activeProject) inputDrafts.set(activeProject, $('#researchQuestion').value);
  clearInterval(pollTimer); activeProject = id; activeTask = null; scopeDirty = false; sendRequest = null;
  const project = await api('/projects/' + id);
  if (activeProject !== id) return;
  projectData = project;
  localStorage.setItem('research-project', id);
  $('#researchQuestion').value = inputDrafts.get(id) || '';
  await refreshScopes(projectData.scope); renderProjectList(); renderChat(projectData, true); startPolling();
}
function startPolling() {
  clearInterval(pollTimer);
  if (!activeTask) return;
  pollTimer = setInterval(() => { if (activeProject && activeWorkspace === 'research') renderProject().catch(error => { clearInterval(pollTimer); toast(error.message, true); }); }, 1500);
}
async function renderProject() {
  const id = activeProject; if (!id) return;
  const project = await api('/projects/' + id); if (id !== activeProject) return;
  projectData = project; renderChat(project);
  if (!activeTask) clearInterval(pollTimer);
}
function renderChat(project, force = false) {
  $('#projectTitle').textContent = project?.title || '专题研究';
  $('#projectSubtitle').textContent = project ? (project.archived ? '已归档 · 恢复后可继续对话' : '正常对话 · 按需查阅知识库 · 内容自动保存') : '从一个问题开始，逐步读懂经典。';
  $('#projectLibrary').disabled = !project; $('#projectNotes').disabled = !project;
  $('#renameProject').disabled = !project || !!project.archived; $('#archiveProject').disabled = !project || !!project.archived;
  $('#researchQuestion').disabled = !project || !!project.archived;
  const running = project?.turns.find(t => ['running', 'stopping'].includes(t.status));
  activeTask = running?.id || null;
  $('#startResearch').hidden = !!running; $('#stopResearch').hidden = !running;
  $('#startResearch').disabled = !project || !!project.archived || sending;
  const signature = JSON.stringify(project?.turns.map(t => [t.id,t.updated,t.status,t.round,t.draft.body,t.activity.at(-1)?.seq,t.error])) + JSON.stringify(project?.notes.map(n => [n.id,n.revision])) + project?.archived;
  if (!force && chatSignatures.get(project?.id) === signature && $('#chatMessages').dataset.loadedProject === project?.id) return;
  chatSignatures.set(project?.id, signature);
  const node = $('#chatMessages'), nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 130, oldScroll = node.scrollTop;
  node.dataset.loadedProject = project?.id || '';
  if (!project?.turns.length) {
    node.innerHTML = '<div class="chat-welcome"><img src="/assets/app-icon.png" alt=""><h2>' + (project ? '今天想探讨什么？' : '与经典对话，积累自己的研究') + '</h2><p>' + (project ? '围绕“' + esc(project.title) + '”直接交流，需要出处时会查阅所选知识库。' : '新建一个研究专题，对话与成果会保存到对应专题文件夹。') + '</p>' + (project ? '<div class="suggestion-grid"><button data-suggestion="比较所选资料对桂枝汤证的不同解释">比较不同解释</button><button data-suggestion="围绕本专题，梳理目前资料能回答的问题和仍需补充的证据">梳理研究线索</button></div>' : '<button id="welcomeNewProject" class="primary">＋ 新建研究专题</button>') + '</div>';
    action('#welcomeNewProject', () => newTopic(true));
    document.querySelectorAll('[data-suggestion]').forEach(b => b.onclick = () => { $('#researchQuestion').value = b.dataset.suggestion; $('#researchQuestion').focus(); });
    return;
  }
  node.innerHTML = project.turns.map(turn => {
    const busy = ['running','stopping'].includes(turn.status);
    const answerLabel = ({model:'模型回答',sources:'知识库原文分析',mixed:'模型知识与原文分析',catalogue:'本地书目信息'})[turn.draft.basis] || 'AI综合研读';
    const note = project.notes.find(n => n.task_id === turn.id);
    // 参考资料只展示回答实际引用的原文，不把仅检索或阅读过的段落充作引用。
    const evidence = turn.draft.evidence || [];
    const references = busy ? '' : evidence.length ? '<section class="chat-references"><p class="reference-heading">参考资料（' + evidence.length + '）</p><div class="evidence-list">' + evidence.map(e => '<button data-evidence="' + esc(e.id) + '" data-source="' + esc(e.source_id) + '">' + esc((e.evidence_id || '原文') + ' · ' + e.title + ' · ' + e.locator) + '</button>').join('') + '</div><p class="muted">引用编号对应原文，其余内容为AI分析。</p></section>' : '<p class="reference-empty muted">' + (turn.draft.catalogue?.length ? '本次仅查看书目，未引用正文。' : '本次未引用知识库资料。') + '</p>';
    const steps = turn.activity.filter(e => e.event !== 'usage').map(e => e.data.message || (e.event === 'search' ? '检索“' + e.data.query + '”：' + e.data.count + '项' : e.event === 'read' ? '阅读：' + e.data.title + ' · ' + e.data.locator : '')).filter(Boolean);
    return '<article class="chat-turn" data-turn="' + turn.id + '"><div class="chat-user"><p>' + esc(turn.question) + '</p></div><div class="chat-assistant"><img src="/assets/app-icon.png" class="assistant-avatar" alt=""><div class="assistant-content"><p class="assistant-label">对话助手 · ' + (busy ? '正在回答…' : answerLabel) + '</p><p class="muted">本轮检索范围：' + ((turn.scope.titles || []).map(esc).join('、') || '仅模型对话') + '</p><details class="chat-progress"><summary>' + (busy ? esc(steps.at(-1) || '正在查阅所选资料…') : '查看本轮过程 · ' + turn.round + '步 · ' + turn.evidence.length + '段原文') + '</summary><ol>' + steps.map(s => '<li>' + esc(s) + '</li>').join('') + '</ol></details>' + (turn.error ? '<p class="warning">' + esc(turn.error) + '</p>' : '') + '<div class="chat-answer">' + (turn.html || '<p class="muted">' + (busy ? '正在组织回答，请稍候。' : '本轮尚未生成回答，可继续研读。') + '</p>') + '</div>' + references + (!busy && !project.archived ? '<div class="chat-message-tools">' + (note ? '<button data-note="' + note.id + '">打开已保存笔记</button>' : '<button data-save-turn="' + turn.id + '">保存为正式笔记</button>') + '<button data-resume-turn="' + turn.id + '">继续研读这一轮</button><span class="muted">' + (turn.status === 'awaiting_review' ? '回答已自动保存 · 待核对' : esc(stateLabels[turn.status])) + '</span></div>' : '') + '</div></div></article>';
  }).join('');
  document.querySelectorAll('[data-evidence]').forEach(b => b.onclick = () => readSource(b.dataset.source, b.dataset.evidence).catch(e => toast(e.message, true)));
  document.querySelectorAll('[data-save-turn]').forEach(b => b.onclick = () => api('/tasks/' + b.dataset.saveTurn + '/save-preview', {}).then(previewProposal).catch(e => toast(e.message, true)));
  document.querySelectorAll('[data-resume-turn]').forEach(b => b.onclick = async () => { b.disabled = true; try { await api('/tasks/' + b.dataset.resumeTurn + '/resume', {}); await renderProject(); startPolling(); } catch (e) { toast(e.message, true); b.disabled = false; } });
  document.querySelectorAll('#chatMessages [data-note]').forEach(b => b.onclick = () => showNote(project.notes.find(n => n.id === b.dataset.note)));
  node.scrollTop = force || nearBottom ? node.scrollHeight : oldScroll;
}
$('#chatForm').addEventListener('submit', async event => {
  event.preventDefault(); if (sending || activeTask || !activeProject) return;
  const message = $('#researchQuestion').value.trim(); if (!message) { $('#researchQuestion').focus(); return; }
  const pid = activeProject;
  const selected = [...document.querySelectorAll('.research-scope:checked')].map(x => x.value);
  if (!sendRequest || sendRequest.message !== message || sendRequest.pid !== pid) sendRequest = { pid, message, id: newRequestId() };
  sending = true; $('#startResearch').disabled = true;
  try {
    await api('/projects/' + pid + '/messages', { message, request_id: sendRequest.id, scope: { library_ids: selected.filter(x => x !== 'builtin'), builtin: selected.includes('builtin') } });
    inputDrafts.delete(pid); sendRequest = null;
    if (activeProject === pid) { $('#researchQuestion').value = ''; scopeDirty = false; await renderProject(); startPolling(); }
    projects = await api('/projects'); renderProjectList();
  } catch (error) { toast(error.message, true); }
  finally { sending = false; $('#startResearch').disabled = !activeProject; }
});
$('#researchQuestion').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('#chatForm').requestSubmit(); }
});
action('#stopResearch', async () => { if (activeTask) { await api('/tasks/' + activeTask + '/stop', {}); await renderProject(); } });
action('#projectLibrary', async () => { const id = activeProject; await switchWorkspace('library'); await refreshLibraryContents(id); });
action('#renameProject', () => renameResearchProject(activeProject, projectData?.title || ''));
action('#archiveProject', () => propose('project_archive', { id: activeProject }));
action('#projectNotes', async () => {
  const project = await api('/projects/' + activeProject);
  modal('专题成果 · ' + project.title, '<p class="muted">本专题共保留' + project.turns.length + '轮对话与草稿，正式笔记如下。</p>' + (project.notes.map(n => '<div class="folder-item"><p>' + esc(n.title) + '</p><button data-open-note="' + n.id + '">打开笔记</button></div>').join('') || '<p>还没有正式笔记。每条回复下可核对并保存，对话草稿已经自动保存。</p>'));
  document.querySelectorAll('[data-open-note]').forEach(b => b.onclick = () => showNote(project.notes.find(n => n.id === b.dataset.openNote)));
});
async function refreshLibraryContents(id) {
  const project = await api('/projects/' + id);
  currentResultFolder = id; $('#folderContents')?.remove();
  $('#libraryTitle').textContent = project.title; $('#libraryHint').textContent = '专题成果文件夹 · 原始著作在独立知识库中管理';
  $('#sourceList').hidden = true; $('#library .work-content > .toolbar').hidden = true;
  $('#renameLibrary').disabled = true; $('#archiveLibrary').disabled = true;
  document.querySelectorAll('[data-library]').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('[data-result-folder]').forEach(n => n.classList.toggle('active', n.dataset.resultFolder === id));
  const node = document.createElement('section'); node.id = 'folderContents'; node.className = 'folder-contents';
  node.innerHTML = '<h2>对话与研读成果</h2><div class="folder-item"><div><p>专题对话 · ' + project.turns.length + '轮</p><small>对话与草稿自动保存于本专题文件夹</small></div><button id="openFolderChat">进入对话</button></div>' + project.turns.map(t => '<div class="folder-item"><div><p>' + esc(t.question) + '</p><small>研读草稿 · ' + esc(stateLabels[t.status]) + '</small></div><button data-folder-turn="' + t.id + '">查看对话</button></div>').join('') + project.notes.map(n => '<div class="folder-item"><div><p>' + esc(n.title) + '</p><small>正式笔记 · AI辅助研读</small></div><button data-folder-note="' + n.id + '">编辑与导出</button></div>').join('');
  $('#sourceList').after(node);
  const openChat = async tid => { await switchWorkspace('research'); await selectProject(id); if (tid) document.querySelector('[data-turn="' + tid + '"]')?.scrollIntoView({ block: 'start' }); };
  action('#openFolderChat', () => openChat());
  document.querySelectorAll('[data-folder-turn]').forEach(b => b.onclick = () => openChat(b.dataset.folderTurn).catch(e => toast(e.message, true)));
  document.querySelectorAll('[data-folder-note]').forEach(b => b.onclick = () => showNote(project.notes.find(n => n.id === b.dataset.folderNote)));
}
function showNote(note) {
  modal('正式笔记 · ' + note.title, '<div class="toolbar"><button id="exportMd">导出 Markdown</button><button id="exportPdf">导出 PDF</button><button id="updateNote">预览修改</button><button id="deleteNote" class="quiet">删除笔记</button></div><input id="noteTitle" aria-label="笔记标题" style="width:100%;margin-bottom:14px" value="' + esc(note.title) + '"><textarea id="noteBody" class="draft-editor">' + esc(note.body) + '</textarea><p class="muted">对话仍保留原始回答。笔记编辑后确认保存，原始证据记录继续保留。</p><div class="evidence-list">' + note.evidence.map(e => '<button data-note-evidence="' + esc(e.id) + '" data-source="' + esc(e.source_id) + '">' + esc(e.title + ' · ' + e.locator) + '</button>').join('') + '</div>');
  for (const format of ['md','pdf']) action(format === 'md' ? '#exportMd' : '#exportPdf', async () => {
    if ($('#noteBody').value !== note.body || $('#noteTitle').value !== note.title) throw new Error('请先预览确认修改，再导出已保存版本');
    const result = await needDesktop().exportNote(note.id, format); if (result) toast('已导出：' + result.path);
  });
  action('#updateNote', () => propose('note_update', { id: note.id, title: $('#noteTitle').value, body: $('#noteBody').value }));
  action('#deleteNote', () => propose('note_delete', { id: note.id }));
  document.querySelectorAll('[data-note-evidence]').forEach(b => b.onclick = () => readSource(b.dataset.source, b.dataset.noteEvidence).catch(e => toast(e.message, true)));
}
