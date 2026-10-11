const path = require('node:path');
function safeResource(root, pathname) {
  let decoded;
  try { decoded = decodeURIComponent(pathname); } catch { throw new Error('无效资源地址'); }
  if (decoded.includes('\\') || decoded.includes('\0')) throw new Error('无效资源地址');
  const target = path.resolve(root, '.' + decoded);
  const rel = path.relative(root, target);
  if (rel.startsWith('..') || path.isAbsolute(rel)) throw new Error('不允许访问资源目录之外的文件');
  return target;
}
function safeTitle(title) { return String(title).replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 90) || '专题笔记'; }
function validNoteId(id) { return typeof id === 'string' && /^[a-f0-9]{32}$/.test(id); }
module.exports = { safeResource, safeTitle, validNoteId };
