// 核验成品 EXE 和安装器中的实际图标，再启动独立测试资料目录检查运行界面。
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { NtExecutable, NtExecutableResource, Resource, Data } = require('resedit');
const { _electron: electron } = require('playwright');
const root = path.resolve(__dirname, '..');
const version = require('../package.json').version;
const out = path.join(root, '验证记录');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const report = { version, passed: false, checks: [], errors: [], files: [] };

function iconHashes(icons) {
  return icons.map(data => sha(Buffer.from(data.isRaw() ? data.bin : data.generate()))).sort();
}

async function main() {
  fs.mkdirSync(out, { recursive: true });
  const reference = Data.IconFile.from(fs.readFileSync(path.join(root, 'resources/icons/icon.ico')));
  const expected = iconHashes(reference.icons.map(item => item.data));
  const exe = path.join(root, 'dist/win-unpacked/伤寒论智能体.exe');
  const installer = path.join(root, `dist/Shanghan-Agent-${version}-win-x64.exe`);
  for (const file of [exe, installer]) {
    const bytes = fs.readFileSync(file);
    const resources = NtExecutableResource.from(NtExecutable.from(bytes));
    const groups = Resource.IconGroupEntry.fromEntries(resources.entries);
    assert.ok(groups.some(group => JSON.stringify(iconHashes(group.getIconItemsFromEntries(resources.entries))) === JSON.stringify(expected)), '未找到与用户选图一致的完整多尺寸图标：' + file);
    report.files.push({ file: path.relative(root, file), bytes: bytes.length, sha256: sha(bytes) });
  }
  report.checks.push('Windows应用EXE和安装器均嵌入与指定ICO一致的9种尺寸图标');
  for (const name of ['icon.ico', 'icon.png']) {
    const original = fs.readFileSync(path.join(root, 'resources/icons', name));
    const packaged = fs.readFileSync(path.join(root, 'dist/win-unpacked/resources/icons', name));
    assert.equal(sha(original), sha(packaged));
  }
  report.checks.push('打包后的窗口图标资源与源文件完全一致');
  const env = { ...process.env, SHANGHAN_TEST_DATA: path.join(root, '.test-data', 'icon-' + Date.now()) };
  delete env.ELECTRON_RUN_AS_NODE;
  let app;
  try {
    app = await electron.launch({ executablePath: exe, args: [], env, timeout: 100000 });
    const page = await app.firstWindow({ timeout: 100000 });
    page.on('pageerror', error => report.errors.push(error.message));
    await page.frameLocator('#classicFrame').locator('.ptext').first().waitFor({ timeout: 30000 });
    const originalText = await page.frameLocator('#classicFrame').locator('.ptext').first().textContent();
    assert.match(originalText, /太阳之为病/);
    const logo = await page.locator('.app-logo').evaluate(image => ({ complete: image.complete, naturalWidth: image.naturalWidth, width: image.width, height: image.height }));
    assert.deepEqual(logo, { complete: true, naturalWidth: 128, width: 44, height: 44 });
    const fetchedLogo = await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/assets/app-icon.png')).arrayBuffer())));
    assert.equal(sha(Buffer.from(fetchedLogo)), sha(fs.readFileSync(path.join(root, 'ui/app-icon.png'))));
    const appState = await app.evaluate(async ({ app, nativeImage }, paths) => {
      const image = nativeImage.createFromPath(paths.ico);
      const fileIcon = await app.getFileIcon(paths.exe, { size: 'normal' });
      return { version: app.getVersion(), packaged: app.isPackaged, windowIconSize: image.getSize(), shellIcon: fileIcon.toPNG().toString('base64') };
    }, { exe, ico: path.join(root, 'dist/win-unpacked/resources/icons/icon.ico') });
    assert.equal(appState.version, version);
    assert.equal(appState.packaged, true);
    assert.ok(appState.windowIconSize.width > 0);
    fs.writeFileSync(path.join(out, '软件图标_系统读取.png'), Buffer.from(appState.shellIcon, 'base64'));
    report.runtime = { version: appState.version, packaged: appState.packaged, windowIconSize: appState.windowIconSize };
    const screenshot = await app.evaluate(async ({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0];
      await window.capturePage(undefined, { stayHidden: true, stayAwake: true });
      const image = await window.capturePage(undefined, { stayHidden: true, stayAwake: true });
      return image.toPNG().toString('base64');
    });
    assert.ok(screenshot.length > 1000, '应用界面截图为空');
    fs.writeFileSync(path.join(out, '软件图标_应用界面.png'), Buffer.from(screenshot, 'base64'));
    report.checks.push(version+'打包程序启动、内置条文载入、窗口图标解码和界面图标加载通过');
    report.checks.push('取得系统Shell图标预览；EXE嵌入图标以资源逐项比对结果为准');
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } finally {
    if (app) await app.close();
  }
}

main().catch(error => { report.errors.push(error.stack); process.exitCode = 1; }).finally(() => {
  fs.writeFileSync(path.join(out, 'icon-qa.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
});
