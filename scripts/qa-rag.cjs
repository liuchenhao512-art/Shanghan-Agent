const assert = require('node:assert/strict');
const path = require('node:path');
function modelReply(p) {
  if (!p.question?.includes('程序验证·RAG')) return null;
  if (p.question.includes('普通对话')) return {queries:[],read_ids:[],finish:true,general_answer:'你好，可以直接交流[E001]，也可以围绕专题讨论研究思路[E404]。这是普通对话程序验证。'};
  if (p.question.includes('连续追问')) {
    assert.ok(p.conversation.some(m => m.content.includes('普通对话')));
    return {queries:[],read_ids:[],finish:true,general_answer:'承接刚才的话题，可以从研究对象、研究问题和验证方法三方面梳理。这是连续对话程序验证。'};
  }
  if (p.question.includes('未命中')) return 'evidence' in p ? {general_answer:'目前没有检索到对应原文，可以先讨论一般研究方法。这是未命中时继续回答的程序验证。'} : {queries:['程序测试专用无匹配字符串NOMATCH6320'],read_ids:[],finish:true};
  if (p.question.includes('书目')) return 'evidence' in p ? {catalogue_ids:p.catalogue.map(b=>b.id)} : {queries:[],read_ids:[],show_catalogue:true,finish:true};
  if (p.question.includes('个人库')) {
    if (!('evidence' in p)) return {queries:['桔梗资料标记'],finish:true};
    assert.equal(p.evidence.length,p.question.includes('联合')?2:1);
    return {answer:p.evidence.map(e=>({text:'程序验证：检索到'+e.text,citations:[{evidence_id:e.evidence_id,quote:e.text}]}))};
  }
  if (p.question.includes('多家')) {
    if (!('evidence' in p)) return {queries:['桂枝汤 注家 阐释'],read_ids:[],finish:true};
    assert.equal(new Set(p.evidence.map(e=>e.author).filter(Boolean)).size,9);
    return {general_answer:'可以先按证候、病机与方药解释划分比较维度。这是模型知识与原文并用的程序验证。',comparison:p.evidence.filter(e=>e.author).map(e=>({text:'程序验证：已取得'+e.author+'的原文窗口，学术含义需另行核对。',citations:[{evidence_id:e.evidence_id,quote:e.text.slice(0,28)}]}))};
  }
  throw Error('未实现的RAG测试问题');
}
async function verify(page, checks, out, screenshot) {
  const original = await page.locator('#projectList .active').getAttribute('data-project');
  await page.locator('#newResearch').click(); await page.locator('#newTitle').fill('正常对话与RAG程序验证');
  await page.locator('#titleConfirm').click(); await page.locator('#modal').waitFor({state:'hidden'});
  const id = await page.locator('#projectList .active').getAttribute('data-project');
  async function scope(builtin) {
    await page.locator('#scopeDetails').evaluate(el=>el.open=true);
    for (const box of await page.locator('.research-scope').all()) await box.setChecked(builtin && await box.getAttribute('value') === 'builtin');
    await page.locator('#scopeDetails').evaluate(el=>el.open=false);
  }
  async function send(question) {
    const count = await page.locator('.chat-turn').count();
    await page.locator('#researchQuestion').fill(question); await page.locator('#startResearch').click();
    const turn=page.locator('.chat-turn').nth(count);
    await turn.locator('[data-save-turn]').waitFor({timeout:60000});
    assert.equal(await turn.locator('.warning').count(),0);
    return turn;
  }
  await scope(false);
  let turn=await send('你好，请介绍一下能如何帮助我。（程序验证·RAG普通对话）');
  assert.match(await turn.locator('.chat-answer').innerText(),/可以直接交流/);
  assert.match(await turn.innerText(),/仅模型对话/);
  assert.match(await turn.locator('.reference-empty').innerText(),/本次未引用知识库资料/);
  assert.doesNotMatch(await turn.innerText(),/未核验引用|未经本库原文核验|\[E404\]/);
  assert.equal(await turn.locator('[data-evidence]').count(),0);
  turn=await send('接着刚才的话题，如何梳理思路？（程序验证·RAG连续追问）');
  assert.match(await turn.locator('.chat-answer').innerText(),/承接刚才/);
  if(screenshot) await screenshot(path.join(out,'正常对话_RAG.png'));
  checks.push('正常对话与追问保留上下文，无重复引用占位或开头说明，底部展示未引用状态');
  await scope(true);
  turn=await send('谈谈没有收录的研究内容。（程序验证·RAG未命中）');
  assert.match(await turn.locator('.chat-answer').innerText(),/先讨论一般研究方法/);
  assert.doesNotMatch(await turn.innerText(),/尚未获得可核对的原文证据，请补充资料或调整检索问题/);
  assert.equal(await turn.locator('[data-evidence]').count(),0);
  checks.push('知识库检索未命中仍正常回答，说明证据边界，不返回固定阻断提示');
  turn=await send('内置经典知识库包含哪些内容？（程序验证·RAG书目）');
  assert.match(await turn.locator('.chat-answer').innerText(),/伤寒论基准条文/);
  assert.match(await turn.locator('.chat-answer').innerText(),/教材解析汇编/);
  assert.equal(await turn.locator('.chat-answer tbody tr').count(),20);
  checks.push('书目问题使用真实目录回答，展示20个内置资料来源');
  turn=await send('各位注家如何解释桂枝汤？（程序验证·RAG多家）');
  assert.doesNotMatch(await turn.locator('.chat-answer').innerText(),/未核验引用|未经本库原文核验|基于本轮知识库原文的分析/);
  assert.match(await turn.locator('.reference-heading').innerText(),/参考资料/);
  assert.ok(await turn.locator('[data-evidence]').count()>=9);
  await turn.locator('[data-evidence]').first().click(); await page.locator('.source-reader .highlight').waitFor(); await page.locator('#closeModal').click();
  if(screenshot) await screenshot(path.join(out,'多注家检索_RAG.png'));
  checks.push('真实内置语料组合词检索覆盖9家注家，底部参考资料可打开，无固定开头提示');
  const libraryIds=[];
  await page.getByRole('button',{name:'我的知识库',exact:true}).click();
  for (const label of ['甲','乙']) {
    await page.locator('#newLibrary').click();await page.locator('#newTitle').fill(label+'库·RAG流程验证');await page.locator('#titleConfirm').click();await page.locator('#modal').waitFor({state:'hidden'});
    libraryIds.push(await page.locator('#libraryList .active').getAttribute('data-library'));
    await page.locator('#fileInput').setInputFiles({name:label+'库资料.txt',mimeType:'text/plain',buffer:Buffer.from('桔梗资料标记：'+label+'库独有内容，仅为程序验证。')});
    await page.locator('#confirmProposal').click();await page.locator('#modal').waitFor({state:'hidden'});await page.locator('.source-row').first().waitFor();
    assert.match(await page.locator('#libraryHint').innerText(),/资料已可检索/);
  }
  await page.getByRole('button',{name:'专题研究',exact:true}).click();
  async function chooseLibraries(ids) {
    await page.locator('#scopeDetails').evaluate(el=>el.open=true);
    for (const box of await page.locator('.research-scope').all()) await box.setChecked(ids.includes(await box.getAttribute('value')));
    await page.locator('#scopeDetails').evaluate(el=>el.open=false);
  }
  await chooseLibraries([libraryIds[0]]);
  turn=await send('只检索甲库资料。（程序验证·RAG个人库）');
  assert.match(await turn.locator('.chat-answer').innerText(),/甲库独有内容/);
  assert.doesNotMatch(await turn.locator('.chat-answer').innerText(),/乙库独有内容/);
  assert.equal(await turn.locator('[data-evidence]').count(),1);
  await chooseLibraries(libraryIds);
  turn=await send('联合检索甲乙两库。（程序验证·RAG个人库联合）');
  assert.match(await turn.locator('.chat-answer').innerText(),/甲库独有内容/);
  assert.match(await turn.locator('.chat-answer').innerText(),/乙库独有内容/);
  assert.equal(await turn.locator('[data-evidence]').count(),2);
  await turn.locator('[data-evidence]').last().click();await page.locator('.source-reader .highlight').waitFor();await page.locator('#closeModal').click();
  if(screenshot) await screenshot(path.join(out,'个人知识库_RAG.png'));
  checks.push('新建两个知识库并导入后可立即在对话选用，单库检索不越界，联合检索可取得两库原文');
  await page.getByRole('button',{name:'我的知识库',exact:true}).click();
  for (const lid of libraryIds) {
    await page.locator('[data-library-menu="'+lid+'"]').click();await page.locator('[data-library-action="delete"]').click();
    await page.locator('#confirmProposal').waitFor();assert.match(await page.locator('#modalContent').innerText(),/保留 1 份资料/);
    await page.locator('#confirmProposal').click();await page.locator('#modal').waitFor({state:'hidden'});
  }
  await page.getByRole('button',{name:'专题研究',exact:true}).click();
  await page.locator('.chat-turn').last().locator('[data-evidence]').first().click();await page.locator('.source-reader .highlight').waitFor();await page.locator('#closeModal').click();
  await page.locator('[data-project-menu="'+id+'"]').click();await page.locator('[data-project-action="delete"]').click();
  await page.locator('#confirmProposal').click();await page.locator('#modal').waitFor({state:'hidden'});
  await page.locator('[data-project="'+original+'"]').click();
}
module.exports={modelReply,verify};
