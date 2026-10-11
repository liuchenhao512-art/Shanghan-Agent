'use strict';
// 菜单挂在页面顶层，避免被知识库导航栏裁切；始终绑定点击的知识库。
let libraryMenuTrigger = null;
const libraryMenu = document.createElement('div');
libraryMenu.id = 'libraryMenu'; libraryMenu.className = 'project-menu'; libraryMenu.hidden = true;
libraryMenu.setAttribute('role', 'menu'); libraryMenu.setAttribute('aria-label', '知识库操作');
libraryMenu.innerHTML = '<p class="project-menu-title"></p><button role="menuitem" data-library-action="rename">重命名</button><button role="menuitem" data-library-action="archive">归档</button><div class="project-menu-divider" role="separator"></div><button role="menuitem" data-library-action="delete" class="danger">删除…</button>';
document.body.append(libraryMenu);
function closeLibraryMenu(returnFocus = false) {
  const trigger = libraryMenuTrigger;
  libraryMenu.hidden = true; libraryMenuTrigger = null;
  if (trigger) { trigger.setAttribute('aria-expanded', 'false'); trigger.closest('.library-row')?.classList.remove('menu-open'); }
  if (returnFocus && trigger?.isConnected) trigger.focus();
}
function openLibraryMenu(trigger) {
  if (trigger === libraryMenuTrigger) { closeLibraryMenu(true); return; }
  closeLibraryMenu(); closeProjectMenu();
  const library = libraries.find(l => l.id === trigger.dataset.libraryMenu);
  if (!library) return;
  libraryMenuTrigger = trigger;
  trigger.setAttribute('aria-expanded', 'true'); trigger.closest('.library-row').classList.add('menu-open');
  libraryMenu.querySelector('.project-menu-title').textContent = library.title;
  libraryMenu.hidden = false;
  const rect = trigger.getBoundingClientRect();
  libraryMenu.style.left = Math.max(8, Math.min(rect.left, innerWidth - libraryMenu.offsetWidth - 8)) + 'px';
  const top = rect.bottom + 5;
  libraryMenu.style.top = Math.max(8, top + libraryMenu.offsetHeight <= innerHeight - 8 ? top : rect.top - libraryMenu.offsetHeight - 5) + 'px';
  libraryMenu.querySelector('[role="menuitem"]').focus();
}
libraryMenu.addEventListener('click', async event => {
  const button = event.target.closest('[data-library-action]');
  if (!button || !libraryMenuTrigger) return;
  const id = libraryMenuTrigger.dataset.libraryMenu, library = libraries.find(l => l.id === id);
  closeLibraryMenu(true);
  if (!library) return;
  try {
    if (button.dataset.libraryAction === 'rename') await titleForm('重命名知识库', library.title, title => propose('library_update', { id, title }));
    else await propose('library_' + button.dataset.libraryAction, { id });
  } catch (error) { toast(error.message, true); }
});
libraryMenu.addEventListener('keydown', event => {
  const items = [...libraryMenu.querySelectorAll('[role="menuitem"]')];
  const index = items.indexOf(document.activeElement);
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next].focus();
  } else if (event.key === 'Escape') { event.preventDefault(); closeLibraryMenu(true); }
  else if (event.key === 'Tab') closeLibraryMenu(true);
});
document.addEventListener('pointerdown', event => {
  if (!libraryMenu.hidden && !libraryMenu.contains(event.target) && !libraryMenuTrigger?.contains(event.target)) closeLibraryMenu();
});
document.addEventListener('scroll', event => { if (!libraryMenu.contains(event.target)) closeLibraryMenu(); }, true);
window.addEventListener('resize', () => closeLibraryMenu());
