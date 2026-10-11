'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let libraries = [], currentLibrary = null, activeTask = null, currentProposal = null, activeWorkspace = 'classic';
let pollTimer = null, toastTimer = null, modalCancel = null, taskDraftDirty = false;
const stateLabels = { running: '正在研读', stopping: '正在停止', stopped: '已停止', interrupted: '上次运行已中断', failed: '调用未完成', limited: '旧版暂停记录 · 可继续研读', awaiting_review: '已完成，可核对保存' };

function toast(message, error = false) {
  clearTimeout(toastTimer); const node = $('#toast'); node.textContent = message; node.className = error ? 'error' : ''; node.hidden = false;
  toastTimer = setTimeout(() => { node.hidden = true; }, 6000);
}
async function api(path, body, method) {
  const response = await fetch('/api/v1' + path, { method: method || (body === undefined ? 'GET' : 'POST'), headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json(); if (!response.ok) throw new Error(data.error || data.detail || '操作未完成'); return data;
}
function action(selector, callback) {
  const node = $(selector); if (!node) return;
  node.addEventListener('click', async () => { node.disabled = true; try { await callback(); } catch (error) { toast(error.message, true); } finally { node.disabled = false; } });
}
function needDesktop() { if (!window.desktop) throw new Error('请在桌面客户端中使用此功能'); return window.desktop; }
function empty(title, text) { return '<div class="empty-state"><h2>' + esc(title) + '</h2><p>' + esc(text) + '</p></div>'; }
function modal(title, content, footer = '<button id="closeModal">关闭</button>') {
  closeProjectMenu();
  modalCancel = null;
  $('#modalContent').innerHTML = '<h2>' + esc(title) + '</h2>' + content + '<div class="modal-actions">' + footer + '</div>';
  if (!$('#modal').open) $('#modal').showModal();
  if ($('#closeModal')) $('#closeModal').onclick = () => closeModal();
}
function closeModal() { const cancel = modalCancel; modalCancel = null; $('#modal').close(); if (cancel) cancel(); }
$('#modal').addEventListener('cancel', event => { event.preventDefault(); closeModal(); });

async function switchWorkspace(name) {
  closeProjectMenu();
  activeWorkspace = name;
  document.querySelectorAll('.workspace').forEach(e => e.classList.toggle('active', e.id === name));
  document.querySelectorAll('[data-workspace]').forEach(e => e.classList.toggle('active', e.dataset.workspace === name));
  if (name === 'library') await refreshLibraries();
  if (name === 'research') await refreshResearch();
  if (name === 'settings') await refreshSettings();
}
document.querySelectorAll('[data-workspace]').forEach(button => button.onclick = () => switchWorkspace(button.dataset.workspace).catch(e => toast(e.message, true)));

async function refreshLibraries() {
  closeLibraryMenu();
  currentResultFolder = null;
  libraries = await api('/libraries');
  await refreshResultFolders();
  if (!libraries.some(l => l.id === currentLibrary)) currentLibrary = libraries[0]?.id || null;
  $('#libraryList').innerHTML = libraries.map(l => '<div class="project-row library-row"><button class="sidebar-item ' + (l.id === currentLibrary ? 'active' : '') + '" data-library="' + l.id + '" title="' + esc(l.title) + '"><span class="project-name"><span class="folder-label" aria-hidden="true">▱</span>' + esc(l.title) + '</span><small>' + l.source_count + ' 份原始资料</small></button><button type="button" class="project-menu-trigger" data-library-menu="' + l.id + '" aria-label="' + esc(l.title) + '的更多操作" aria-haspopup="menu" aria-expanded="false" aria-controls="libraryMenu" title="更多操作"><span aria-hidden="true">⋯</span></button></div>').join('') || '<p class="muted">还没有知识库</p>';
  document.querySelectorAll('[data-library]').forEach(b => b.onclick = async () => { currentLibrary = b.dataset.library; await refreshLibraries(); });
  document.querySelectorAll('[data-library-menu]').forEach(button => {
    button.onclick = () => openLibraryMenu(button);
    button.onkeydown = event => { if (event.key === 'ArrowDown') { event.preventDefault(); openLibraryMenu(button); } };
  });
  const selected = libraries.find(l => l.id === currentLibrary);
  $('#libraryTitle').textContent = selected?.title || '我的知识库';
  $('#libraryHint').textContent = selected ? (selected.source_count ? '资料已可检索，在专题对话的“资料范围”中勾选本知识库即可使用。' : '导入并确认资料后，可在专题对话中选择本知识库作为检索来源。') : '建立知识库，按类别积累著作和文章。';
  ['#renameLibrary', '#archiveLibrary', '#importFiles', '#importUrl', '#librarySearch'].forEach(id => $(id).disabled = !selected);
  $('#folderContents')?.remove();
  $('#sourceList').hidden = false;
  $('#library .work-content > .toolbar').hidden = false;
  if (!selected) { $('#sourceList').innerHTML = empty('建立你的知识库', '点击左侧“＋”，例如建立“近现代伤寒专著知识库”，导入相关著作。'); return; }
  const sources = await api('/sources?library_id=' + currentLibrary);
  $('#sourceList').innerHTML = sources.map(s => '<article class="source-row"><span class="file-icon">' + esc(s.kind.toUpperCase()) + '</span><div class="source-info"><h3>' + esc(s.title) + '</h3><p>' + esc(s.author || '作者待核对') + ' · ' + (s.metadata.character_count || 0) + ' 字 · ' + esc(s.metadata.bibliography_status || '来源已记录') + '</p></div><div class="actions"><button data-read="' + s.id + '">阅读</button><button data-edit="' + s.id + '">整理</button><button data-delete="' + s.id + '" class="quiet">删除</button></div></article>').join('') || empty('知识库中还没有资料', '导入书籍或文章，预览正文与来源后确认入库。');
  document.querySelectorAll('[data-read]').forEach(b => b.onclick = () => readSource(b.dataset.read).catch(e => toast(e.message, true)));
  document.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => editSource(b.dataset.edit).catch(e => toast(e.message, true)));
  document.querySelectorAll('[data-delete]').forEach(b => b.onclick = () => propose('source_delete', { id: b.dataset.delete }).catch(e => toast(e.message, true)));

}
async function propose(kind, payload) { return previewProposal(await api('/proposals', { kind, payload })); }
const proposalNames = { library_create: '新建知识库', library_update: '重命名知识库', library_archive: '归档知识库', library_restore: '恢复知识库', library_delete: '删除知识库', project_update: '重命名研究专题', project_archive: '归档研究专题', project_restore: '恢复研究专题', project_delete: '删除研究专题', import: '资料入库', source_update: '整理资料', source_delete: '删除资料', note_save: '保存研读笔记', note_update: '更新笔记', note_delete: '删除笔记' };
function previewProposal(proposal) {
  currentProposal = proposal;
  const p = proposal.payload;
  let content = '<p class="muted">以下为将要保存的具体内容。修改后需重新预览；确认前不会改变正式知识库。</p>';
  if (p.title) content += '<div class="preview-meta"><label>标题<input id="previewTitle" value="' + esc(p.title) + '"></label>' + ('author' in p ? '<label>作者<input id="previewAuthor" value="' + esc(p.author) + '"></label>' : '') + '</div>';
  if (p.previous) content += '<p>修改前：' + esc(p.previous.title) + ('author' in p.previous ? '；' + esc(p.previous.author || '作者待核') : '') + '</p>';
  if (p.library_ids) content += '<p>目标知识库：' + p.library_ids.map(id => esc(p.library_titles?.[id] || libraries.find(l => l.id === id)?.title || id)).join('、') + '</p>';
  if (p.metadata?.tags) content += '<p>标签：' + esc(p.metadata.tags.join('、')) + '</p>';
  if (p.metadata?.publication) content += '<p>出版信息：' + esc(p.metadata.publication) + '</p>';
  for (const warning of p.metadata?.warnings || []) content += '<p class="warning">' + esc(warning) + '</p>';
  if (p.chunks) { content += '<p>共提取 ' + p.chunks.length + ' 段，' + (p.metadata?.character_count || 0) + ' 字；请核对正文样例。</p>'; content += p.chunks.slice(0, 4).map(c => '<p class="quote-location">' + esc(c.locator) + '</p><div class="quoted">' + esc(c.text.slice(0, 900)) + '</div>').join(''); }
  if (p.body) content += '<div class="quoted">' + esc(p.body) + '</div>';
  if (p.impact) {
    content += '<p class="warning">' + esc(p.impact.message) + '</p>';
    if (p.impact.sources) content += '<p>将删除 ' + p.impact.sources_deleted + ' 份资料，保留 ' + p.impact.sources_retained + ' 份资料。</p><ul>' + p.impact.sources.map(s => '<li>' + esc(s.title) + '：' + (s.retained ? '保留（' + esc(s.reason) + '）' : '删除原件与正文') + '</li>').join('') + '</ul>';
    else content += '<p>将删除 ' + p.impact.conversations + ' 轮对话及草稿、' + p.impact.notes + ' 篇笔记。</p>';
    content += '<p class="warning">删除后不能从应用中恢复，请核对后确认。</p>';
  } else if (proposal.kind.endsWith('_delete')) content += '<p class="warning">将从正式列表移除；历史引用所需内容保留。</p>';
  if (proposal.kind.endsWith('_archive')) content += '<p>归档后从正常列表收起，全部内容保留。可从左侧“已归档”入口恢复或删除。</p>';
  if (proposal.kind.endsWith('_restore')) content += '<p>恢复后重新出现在正常列表，可继续使用。</p>';
  modal(proposalNames[proposal.kind] + ' · 确认预览', content, '<button id="cancelProposal">取消</button>' + (p.title ? '<button id="reviseProposal">应用修改并重新预览</button>' : '') + '<button id="confirmProposal" class="primary">确认' + esc(proposalNames[proposal.kind]) + '</button>');
  if (p.chunks && !p.chunks.length) $('#confirmProposal').disabled = true;
  return new Promise(resolve => {
    modalCancel = () => { api('/proposals/' + proposal.id + '/cancel', {}).catch(() => {}); resolve(false); };
    $('#cancelProposal').onclick = closeModal;
    function changed() { return ($('#previewTitle') && $('#previewTitle').value !== p.title) || ($('#previewAuthor') && $('#previewAuthor').value !== p.author); }
    if ($('#reviseProposal')) action('#reviseProposal', async () => {
      const revised = await api('/proposals/' + proposal.id + '/revise', { title: $('#previewTitle').value, ...($('#previewAuthor') ? { author: $('#previewAuthor').value } : {}) });
      modalCancel = null; resolve(await previewProposal(revised));
    });
    action('#confirmProposal', async () => {
      if (changed()) throw new Error('内容已修改，请先点击“应用修改并重新预览”');
      const result = await api('/proposals/' + proposal.id + '/confirm', { hash: proposal.hash });
      modalCancel = null;
      if (proposal.kind === 'library_create') currentLibrary = result.id;
      await refreshLibraries(); await refreshScopes(); await refreshResearch();
      $('#modal').close(); toast('操作已完成。'); resolve(true);
    });
  });
}
async function titleForm(title, value, callback, direct = false) {
  const button = direct ? 'titleConfirm' : 'titlePreview';
  modal(title, '<label>名称<input id="newTitle" maxlength="120" value="' + esc(value) + '" style="width:100%;margin-top:8px" placeholder="输入名称"></label>' + (direct ? '<p class="muted">输入名称后确认创建。</p>' : ''), '<button id="closeModal">取消</button><button id="' + button + '" class="primary">' + (direct ? '确认创建' : '查看预览') + '</button>');
  action('#' + button, () => callback($('#newTitle').value));
  $('#newTitle').onkeydown = event => { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); $('#' + button).click(); } };
  $('#newTitle').focus();
}
action('#newLibrary', () => newTopic(false));
action('#renameLibrary', () => titleForm('重命名知识库', libraries.find(l => l.id === currentLibrary)?.title || '', title => propose('library_update', { id: currentLibrary, title })));
action('#archiveLibrary', () => propose('library_archive', { id: currentLibrary }));
action('#importFiles', () => { $('#fileInput').value = ''; $('#fileInput').click(); });
function fileBase64(file) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error('文件读取失败')); reader.readAsDataURL(file); }); }
$('#fileInput').onchange = async () => {
  const selectedLibrary = currentLibrary;
  for (const file of $('#fileInput').files) {
    try {
      if (file.size > 100 * 1024 * 1024) throw new Error('单份资料暂支持最大100MB');
      toast('正在提取：' + file.name);
      const proposal = await api('/import/file', { name: file.name, data: await fileBase64(file), library_ids: [selectedLibrary] });
      await previewProposal(proposal);
    } catch (error) { toast(file.name + '：' + error.message, true); }
  }
};
action('#importUrl', () => {
  modal('导入指定文章', '<p>仅读取这个链接的可访问正文，预览后再入库。</p><input id="articleUrl" placeholder="https://…" style="width:100%">', '<button id="closeModal">取消</button><button id="fetchArticle" class="primary">提取并预览</button>');
  action('#fetchArticle', async () => { const p = await api('/import/url', { url: $('#articleUrl').value, library_ids: [currentLibrary] }); await previewProposal(p); });
});
async function readSource(id, highlight) {
  const source = await api('/sources/' + encodeURIComponent(id));
  modal(source.title, '<p class="muted">' + esc(source.author || '作者待核对') + ' · ' + esc(source.origin || source.metadata.filename || '本地资料') + '</p><div class="source-reader">' + source.chunks.map(c => '<div id="chunk-' + esc(c.id) + '" class="' + (c.id === highlight ? 'highlight' : '') + '"><p class="quote-location">' + esc(c.locator) + '</p><p>' + esc(c.text) + '</p></div>').join('') + '</div>');
  if (!source.builtin && window.desktop) {
    const button = document.createElement('button'); button.textContent = '打开原始文件';
    button.onclick = () => window.desktop.openOriginal(id).catch(e => toast(e.message, true));
    $('#modalContent .modal-actions').prepend(button);
  }
  if (highlight) document.getElementById('chunk-' + highlight)?.scrollIntoView({ block: 'center' });
}
async function editSource(id) {
  const source = await api('/sources/' + id);
  modal('整理资料', '<div class="preview-meta"><label>书名或标题<input id="editTitle" value="' + esc(source.title) + '"></label><label>作者<input id="editAuthor" value="' + esc(source.author) + '"></label></div><label class="field-label">出版信息<input id="editPublication" style="width:100%" value="' + esc(source.metadata.publication || '') + '" placeholder="出版年、出版社、版本等；未知可留空"></label><label class="field-label">标签<input id="editTags" style="width:100%" value="' + esc((source.metadata.tags || []).join('，')) + '" placeholder="以逗号分隔"></label><p>所属知识库</p><div class="scope-choices">' + libraries.map(l => '<label><input type="checkbox" class="edit-membership" value="' + l.id + '" ' + (source.library_ids.includes(l.id) ? 'checked' : '') + '>' + esc(l.title) + '</label>').join('') + '</div>', '<button id="closeModal">取消</button><button id="editSourcePreview" class="primary">查看变更预览</button>');
  action('#editSourcePreview', () => propose('source_update', { id, title: $('#editTitle').value, author: $('#editAuthor').value, metadata: { ...source.metadata, publication: $('#editPublication').value, tags: $('#editTags').value.split(/[,，]/).map(x => x.trim()).filter(Boolean) }, library_ids: [...document.querySelectorAll('.edit-membership:checked')].map(x => x.value) }));
}
action('#librarySearch', async () => {
  const rows = await api('/search', { query: $('#libraryQuery').value, library_ids: [currentLibrary] });
  modal('本知识库检索结果', rows.map(r => '<button class="search-result" data-result="' + r.id + '" data-source="' + r.source_id + '"><strong>' + esc(r.title) + '</strong><small>' + esc(r.locator) + '</small><p>' + esc(r.text.slice(0, 350)) + '</p></button>').join('') || empty('未检索到', '尝试更短的词语，或补充相关资料。'));
  document.querySelectorAll('[data-result]').forEach(b => b.onclick = () => readSource(b.dataset.source, b.dataset.result).catch(e => toast(e.message, true)));
});
action('#managementButton', async () => { toast('正在生成整理方案…'); await previewProposal(await api('/management/propose', { request: $('#managementRequest').value })); });

async function refreshSettings() {
  const controls = ['#modelBase','#modelName','#modelKey','#clearKey','#saveModel','#testModel'];
  controls.forEach(id => $(id).disabled = true);
  try {
    const status = await api('/status');
    const config = window.desktop ? await window.desktop.getSettings() : { ...status.model, data_directory: status.data_directory };
    $('#modelBase').value = config.base_url; $('#modelName').value = config.model; $('#modelKey').value = ''; $('#clearKey').checked = false;
    $('#modelState').textContent = config.configured ? '密钥已由系统加密保存。测试连接会发起一次小额模型调用。' : '尚未配置模型。阅读、检索和资料导入仍可使用。';
    $('#dataDirectory').textContent = config.data_directory;
  } finally { controls.forEach(id => $(id).disabled = false); }
}
action('#saveModel', async () => {
  const result = await needDesktop().saveSettings({ base_url: $('#modelBase').value, model: $('#modelName').value, api_key: $('#modelKey').value, clear_key: $('#clearKey').checked });
  $('#classicFrame').contentWindow.postMessage({ type: 'model-updated' }, '*'); await refreshSettings(); toast(result.configured ? '模型设置已保存' : '模型设置已保存，当前未配置密钥');
});
action('#testModel', async () => { const result = await api('/model/test', {}); toast('服务响应：' + result.response); });
action('#revealData', () => needDesktop().revealData());
action('#chooseData', () => {
  modal('切换本地数据目录', '<p>接下来选择空目录或已有知识库目录。应用将重新启动，当前目录中的资料会保留。</p><p>将当前资料搬到另一台电脑，请使用“导出备份包”。</p>', '<button id="closeModal">取消</button><button id="chooseDataConfirm" class="primary">选择目录并切换</button>');
  action('#chooseDataConfirm', () => needDesktop().chooseLibrary());
});
action('#backupLibrary', async () => { const result = await needDesktop().backup(); if (result) toast('备份已保存：' + result.path); });
action('#restoreLibrary', async () => {
  const preview = await needDesktop().previewRestore(); if (!preview) return;
  const contents = [['知识库', preview.contents.libraries], ['研究专题', preview.contents.projects || []], ['已归档知识库', preview.contents.archived_libraries || []], ['已归档研究专题', preview.contents.archived_projects || []], ['个人资料', preview.contents.sources], ['笔记', preview.contents.notes]].map(([label, titles]) => '<h3>' + label + ' · ' + titles.length + '</h3><p>' + (titles.map(esc).join('、') || '暂无') + '</p>').join('');
  modal('恢复备份 · 确认预览', '<p>' + esc(preview.description) + '</p><p>备份时间：' + esc(preview.created) + '</p><p>' + preview.file_count + ' 个文件 · ' + (preview.bytes / 1024 / 1024).toFixed(1) + ' MB</p>' + contents + '<p>文件校验已通过。</p>', '<button id="closeModal">取消</button><button id="restoreConfirm" class="primary">确认恢复到独立目录</button>');
  action('#restoreConfirm', async () => {
    const result = await needDesktop().restore(preview);
    modal('备份已恢复', '<p>资料与数据库校验已通过。</p><p class="path-text">' + esc(result.directory) + '</p><p>现在切换将重新启动应用。</p>', '<button id="closeModal">稍后切换</button><button id="activateRestore" class="primary">切换到恢复的知识库</button>');
    action('#activateRestore', () => needDesktop().activateRestored(result.directory));
  });
});
document.addEventListener('DOMContentLoaded', () => refreshLibraries().then(() => refreshScopes()).catch(e => toast(e.message, true)));
