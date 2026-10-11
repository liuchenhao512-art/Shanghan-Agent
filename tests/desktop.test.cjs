const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { safeResource, safeTitle, validNoteId } = require('../desktop/helpers.cjs');
test('资源路径不能越过 UI 目录', () => {
  const root = path.resolve('ui');
  assert.equal(safeResource(root, '/index.html'), path.join(root, 'index.html'));
  assert.throws(() => safeResource(root, '/../../secret'));
  assert.throws(() => safeResource(root, '/%2e%2e/%2e%2e/secret'));
  assert.throws(() => safeResource(root, '/%5csecret'));
});
test('导出参数受限且兼容中文文件名', () => {
  assert.equal(safeTitle('桂枝汤：比较/笔记'), '桂枝汤：比较_笔记');
  assert.ok(validNoteId('a'.repeat(32)));
  assert.ok(!validNoteId('../etc'));
});
