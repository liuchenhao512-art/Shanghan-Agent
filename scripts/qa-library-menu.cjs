// 在真实页面验证知识库菜单，所有资料在独立测试目录中。
const assert = require('node:assert/strict');
const path = require('node:path');
module.exports = async function verifyLibraryMenu(page, checks, out, screenshot) {
  await page.getByRole('button', {name:'我的知识库',exact:true}).click();
  const original = await page.locator('#libraryList .active').count() ? await page.locator('#libraryList .active').getAttribute('data-library') : null;
  async function create(title) {
    await page.locator('#newLibrary').click();await page.locator('#newTitle').fill(title);await page.locator('#titleConfirm').click();await page.locator('#modal').waitFor({state:'hidden'});
    return page.locator('#libraryList .active').getAttribute('data-library');
  }
  const a=await create('知识库菜单验证A'),b=await create('近现代伤寒医家著作与相关研究资料·知识库长名称菜单验证B');
  const trigger=id=>page.locator('[data-library-menu="'+id+'"]');
  const menu=page.locator('#libraryMenu');
  async function open(id,action) {
    await trigger(id).click();await menu.waitFor();
    if(action) await page.locator('[data-library-action="'+action+'"]').click();
  }
  async function confirm(){await page.locator('#confirmProposal').click();await page.locator('#modal').waitFor({state:'hidden'});}
  await open(a);
  assert.equal(await page.locator('#libraryList .active').getAttribute('data-library'),b);
  assert.deepEqual(await menu.locator('[role="menuitem"]').allTextContents(),['重命名','归档','删除…']);
  await page.keyboard.press('ArrowDown');assert.equal(await page.evaluate(()=>document.activeElement.dataset.libraryAction),'archive');
  await page.keyboard.press('Escape');await menu.waitFor({state:'hidden'});
  assert.equal(await trigger(a).evaluate(el=>el===document.activeElement),true);
  await open(b);const box=await menu.boundingBox(),v=await page.evaluate(()=>({w:innerWidth,h:innerHeight}));
  assert.ok(box && box.x>=0 && box.y>=0 && box.x+box.width<=v.w && box.y+box.height<=v.h);
  if(screenshot) await screenshot(path.join(out,'知识库_更多菜单.png'));
  await page.locator('#libraryTitle').click();await menu.waitFor({state:'hidden'});
  checks.push('知识库右侧更多菜单、长名称与键盘操作正常，操作非当前库不切换选中项');
  await open(a,'rename');await page.locator('#newTitle').fill('知识库A·菜单已改名');await page.locator('#titlePreview').click();await confirm();
  assert.match(await page.locator('[data-library="'+a+'"]').innerText(),/菜单已改名/);
  assert.equal(await page.locator('#libraryList .active').getAttribute('data-library'),b);
  await open(a,'archive');await page.locator('#cancelProposal').click();await page.locator('#modal').waitFor({state:'hidden'});
  await open(a,'archive');await confirm();await trigger(a).waitFor({state:'detached'});
  await page.locator('#archivedLibraries').click();await page.locator('[data-archive-restore="'+a+'"]').click();await page.locator('#confirmProposal').click();
  await page.getByRole('heading',{name:/^已归档的/}).waitFor();await page.locator('[data-archive-restore="'+a+'"]').waitFor({state:'detached'});await page.locator('#closeModal').click();
  assert.equal(await trigger(a).count(),1);
  checks.push('知识库菜单重命名、归档取消与恢复保留库记录');
  await page.locator('#fileInput').setInputFiles({name:'知识库菜单删除样例.txt',mimeType:'text/plain',buffer:Buffer.from('独立菜单删除测试正文，不作为学术资料。')});
  await confirm();await page.locator('.source-row').first().waitFor();
  await open(b,'delete');await page.locator('#confirmProposal').waitFor();
  assert.match(await page.locator('#modalContent').innerText(),/将删除 1 份资料/);
  await page.locator('#cancelProposal').click();await page.locator('#modal').waitFor({state:'hidden'});
  assert.equal(await page.locator('.source-row').count(),1);
  await open(b,'delete');await confirm();await trigger(b).waitFor({state:'detached'});
  await open(a,'delete');await confirm();await trigger(a).waitFor({state:'detached'});
  if(original) await page.locator('[data-library="'+original+'"]').click();
  checks.push('知识库可直接预览删除，无需先归档；取消保留资料，确认删除指定库及无引用原件');
};
