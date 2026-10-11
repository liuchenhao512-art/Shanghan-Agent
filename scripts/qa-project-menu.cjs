// 在浏览器及实际打包窗口复用项目菜单交互检查。
const assert = require('node:assert/strict');
const path = require('node:path');
module.exports = async function verifyProjectMenu(page, checks, out, screenshot) {
  const original = await page.locator('#projectList .active').getAttribute('data-project');
  async function create(title) {
    await page.locator('#newResearch').click(); await page.locator('#newTitle').fill(title);
    await page.locator('#titleConfirm').click(); await page.locator('#modal').waitFor({ state: 'hidden' });
    return page.locator('#projectList .active').getAttribute('data-project');
  }
  const a = await create('桂枝汤证·各家解释');
  const b = await create('近现代伤寒学术研究与条文比较·长名称项目菜单检查');
  const trigger = id => page.locator('[data-project-menu="' + id + '"]');
  const menu = page.locator('#projectMenu');
  async function open(id, action) {
    await trigger(id).click(); await menu.waitFor();
    if (action) {
      await page.locator('[data-project-action="' + action + '"]').click();
      await page.locator(action === 'rename' ? '#newTitle' : '#confirmProposal').waitFor();
    }
  }
  async function confirm() { await page.locator('#confirmProposal').click(); await page.locator('#modal').waitFor({ state: 'hidden' }); }
  await open(a);
  assert.equal(await page.locator('#projectList .active').getAttribute('data-project'), b);
  assert.deepEqual(await menu.locator('[role="menuitem"]').allTextContents(), ['重命名', '归档', '删除…']);
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(() => document.activeElement.dataset.projectAction), 'archive');
  await page.keyboard.press('Escape'); await menu.waitFor({ state: 'hidden' });
  assert.equal(await trigger(a).evaluate(el => el === document.activeElement), true);
  await open(b); await trigger(b).click(); await menu.waitFor({ state: 'hidden' });
  await open(a); await page.locator('#projectTitle').click(); await menu.waitFor({ state: 'hidden' });
  await open(a); await trigger(b).click(); await menu.waitFor();
  assert.equal(await trigger(a).getAttribute('aria-expanded'), 'false');
  assert.equal(await trigger(b).getAttribute('aria-expanded'), 'true');
  const box = await menu.boundingBox(), viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
  assert.ok(box && box.x >= 0 && box.y >= 0 && box.x + box.width <= viewport.width && box.y + box.height <= viewport.height);
  if (screenshot) await screenshot(path.join(out, '专题项目_更多菜单.png'));
  await page.keyboard.press('Escape');
  checks.push('项目右侧常显更多菜单，非当前项目操作、长名称、键盘与外部点击关闭正常');
  await open(a, 'rename'); await page.locator('#newTitle').fill('桂枝汤证·菜单改名<原文核对>');
  await page.locator('#titlePreview').click(); await confirm();
  assert.match(await page.locator('[data-project="' + a + '"]').innerText(), /菜单改名<原文核对>/);
  assert.equal(await page.locator('#projectList .active').getAttribute('data-project'), b);
  await open(a, 'archive'); await page.locator('#cancelProposal').click(); await page.locator('#modal').waitFor({ state: 'hidden' });
  assert.equal(await trigger(a).count(), 1);
  await open(a, 'archive'); await confirm(); await trigger(a).waitFor({ state: 'detached' });
  await page.locator('#archivedProjects').click(); await page.locator('[data-archive-restore="' + a + '"]').click();
  await page.locator('#confirmProposal').click(); await page.getByRole('heading', { name: /^已归档的/ }).waitFor();
  await page.locator('[data-archive-restore="' + a + '"]').waitFor({ state: 'hidden' }); await page.locator('#closeModal').click();
  assert.equal(await trigger(a).count(), 1);
  checks.push('菜单重命名绑定所点项目，归档取消不改变资料，归档后可恢复');
  await open(a, 'delete');
  assert.match(await page.locator('#modalContent').innerText(), /独立知识库和原始资料保留/);
  assert.match(await page.locator('#modalContent').innerText(), /删除后不能从应用中恢复/);
  await page.locator('#cancelProposal').click(); await page.locator('#modal').waitFor({ state: 'hidden' });
  assert.equal(await trigger(a).count(), 1);
  await open(a, 'delete'); await confirm(); await trigger(a).waitFor({ state: 'detached' });
  assert.equal(await page.locator('#projectList .active').getAttribute('data-project'), b);
  await open(b, 'delete'); await confirm(); await trigger(b).waitFor({ state: 'detached' });
  await page.locator('[data-project="' + original + '"]').click();
  checks.push('普通项目菜单可预览删除，取消保留项目，确认删除目标，其他专题仍可使用');
};
