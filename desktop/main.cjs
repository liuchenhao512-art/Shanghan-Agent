const { app, BrowserWindow, protocol, net, ipcMain, dialog, safeStorage, shell } = require('electron');
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const { safeResource, safeTitle, validNoteId } = require('./helpers.cjs');
app.setName('ShanghanAgent');
if (process.platform === 'win32') app.setAppUserModelId('cn.shanghan.agent');
if (process.env.SHANGHAN_TEST_DATA) {
  const profile = path.join(process.env.SHANGHAN_TEST_DATA, 'desktop-profile');
  fsSync.mkdirSync(profile, { recursive: true });
  app.setPath('userData', profile);
}
protocol.registerSchemesAsPrivileged([{ scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } }]);
let mainWindow, backend, baseURL, serviceToken, dataDirectory, modelConfig;
let quitting = false;
const restoredDirectories = new Set();
const uiRoot = path.join(app.getAppPath(), 'ui');
const iconRoot = app.isPackaged ? path.join(process.resourcesPath, 'icons') : path.join(app.getAppPath(), 'resources', 'icons');
const appIcon = path.join(iconRoot, process.platform === 'win32' ? 'icon.ico' : 'icon.png');
const configFile = () => path.join(app.getPath('userData'), 'settings.json');
const secretFile = () => path.join(app.getPath('userData'), 'credentials.bin');

async function readJSON(filename, fallback) { try { return JSON.parse(await fs.readFile(filename, 'utf8')); } catch { return fallback; } }
async function atomicFile(filename, bytes) {
  const temporary = filename + '.tmp';
  await fs.mkdir(path.dirname(filename), { recursive: true });
  await fs.writeFile(temporary, bytes);
  await fs.rename(temporary, filename);
}
async function service(endpoint, body, method = 'POST') {
  const response = await fetch(baseURL + endpoint, { method, headers: { 'Content-Type': 'application/json', 'X-Shanghan-Token': serviceToken }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '本地服务操作失败');
  return data;
}
async function loadSettings() {
  const config = await readJSON(configFile(), {});
  dataDirectory = process.env.SHANGHAN_TEST_DATA || config.data_directory || path.join(app.getPath('userData'), 'library');
  modelConfig = { base_url: config.base_url || 'https://api.deepseek.com/v1', model: config.model || 'deepseek-chat', api_key: '' };
  if (fsSync.existsSync(secretFile())) {
    try { modelConfig.api_key = safeStorage.decryptString(await fs.readFile(secretFile())); }
    catch { modelConfig.api_key = ''; }
  }
}
async function launchBackend() {
  const root = app.getAppPath();
  const executable = app.isPackaged ? path.join(process.resourcesPath, 'backend', process.platform === 'win32' ? 'shanghan-server.exe' : 'shanghan-server')
    : path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const args = app.isPackaged ? ['--bootstrap'] : ['-X', 'utf8', '-m', 'server.entry', '--bootstrap'];
  serviceToken = crypto.randomBytes(32).toString('hex');
  backend = spawn(executable, args, { cwd: app.isPackaged ? process.resourcesPath : root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, PYTHONUTF8: '1' } });
  // 冻结后的 Windows Python 可能采用系统代码页；ASCII JSON 避免中文路径损坏。
  const bootstrap = JSON.stringify({ data_dir: dataDirectory, builtin_dir: app.isPackaged ? path.join(process.resourcesPath, 'builtin') : path.join(root, 'resources/builtin'), ui_dir: uiRoot, token: serviceToken, model: modelConfig });
  backend.stdin.write(bootstrap.replace(/[^\x00-\x7f]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')) + '\n');
  await new Promise((resolve, reject) => {
    let pending = '', errors = '', resolved = false;
    const timeout = setTimeout(() => { if (!resolved) { backend.kill(); reject(new Error('本地资料服务启动超时')); } }, 90000);
    backend.stderr.on('data', chunk => { errors = (errors + chunk.toString()).slice(-3000); });
    backend.stdout.on('data', chunk => {
      pending += chunk.toString();
      let newline;
      while ((newline = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, newline); pending = pending.slice(newline + 1);
        try { const message = JSON.parse(line); if (message.event === 'ready') { baseURL = 'http://127.0.0.1:' + message.port; resolved = true; clearTimeout(timeout); resolve(); } } catch {}
      }
    });
    backend.on('error', error => { clearTimeout(timeout); reject(error); });
    backend.on('exit', () => {
      clearTimeout(timeout);
      if (!resolved) reject(new Error('本地服务未能启动：' + errors));
      else if (!quitting) {
        if (process.env.SHANGHAN_TEST_DATA) console.error('资料服务已停止');
        else dialog.showErrorBox('资料服务已停止', '已有数据已保留，请重新启动应用。');
      }
    });
  });
  for (let attempt = 0; attempt < 80; attempt++) {
    try { await service('/api/v1/status', undefined, 'GET'); return; } catch { await new Promise(resolve => setTimeout(resolve, 100)); }
  }
  throw new Error('本地服务未就绪');
}

function registerProtocol() {
  protocol.handle('app', async request => {
    const url = new URL(request.url);
    if (url.host !== 'shanghan') return new Response('Forbidden', { status: 403 });
    if (url.pathname.startsWith('/internal/')) return new Response('Forbidden', { status: 403 });
    try {
      if (url.pathname.startsWith('/api/')) {
        const headers = new Headers(request.headers);
        headers.set('X-Shanghan-Token', serviceToken);
        headers.delete('origin');
        const body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer();
        return await net.fetch(baseURL + url.pathname + url.search, { method: request.method, headers, body });
      }
      const resource = url.pathname === '/' ? '/index.html' : url.pathname === '/classic' ? '/classic.html' : url.pathname.replace(/^\/assets\//, '/');
      const target = safeResource(uiRoot, resource);
      const response = await net.fetch(pathToFileURL(target).href);
      const headers = new Headers(response.headers);
      headers.set('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'");
      return new Response(response.body, { status: response.status, headers });
    } catch { return new Response('本地资源加载失败', { status: 404 }); }
  });
}

function handle(channel, callback) {
  ipcMain.handle(channel, async (event, ...args) => {
    if (event.senderFrame !== mainWindow.webContents.mainFrame || !event.senderFrame.url.startsWith('app://shanghan/')) throw new Error('不允许的调用来源');
    return callback(...args);
  });
}
function registerActions() {
  handle('settings:get', async () => ({ base_url: modelConfig.base_url, model: modelConfig.model, configured: !!modelConfig.api_key, data_directory: dataDirectory }));
  handle('settings:save', async values => {
    const next = { base_url: String(values.base_url || ''), model: String(values.model || ''), api_key: values.clear_key ? '' : (values.api_key || modelConfig.api_key) };
    if (next.api_key && !safeStorage.isEncryptionAvailable()) throw new Error('系统密钥存储暂不可用，本次设置未保存');
    const result = await service('/internal/model', next);
    try {
      if (next.api_key) await atomicFile(secretFile(), safeStorage.encryptString(next.api_key));
      else await fs.rm(secretFile(), { force: true });
      await atomicFile(configFile(), JSON.stringify({ base_url: result.base_url, model: result.model, data_directory: dataDirectory }, null, 2));
    } catch (error) { await service('/internal/model', modelConfig); throw error; }
    modelConfig = { ...next, base_url: result.base_url };
    return result;
  });
  handle('note:export', async ({ id, format }) => {
    if (!validNoteId(id) || !['md', 'pdf'].includes(format)) throw new Error('无效导出参数');
    const note = await service('/api/v1/notes/' + id + '/export', undefined, 'GET');
    const destination = await dialog.showSaveDialog(mainWindow, { defaultPath: safeTitle(note.title) + '.' + format, filters: [{ name: format.toUpperCase(), extensions: [format] }] });
    if (destination.canceled) return null;
    if (format === 'md') {
      const bundle = await service('/internal/notes/' + id + '/markdown-bundle', {});
      const attachments = path.join(path.dirname(destination.filePath), bundle.attachments_name);
      await fs.cp(bundle.attachments_path, attachments, { recursive: true, force: false, errorOnExist: true });
      await fs.copyFile(bundle.markdown_path, destination.filePath);
    }
    else {
      const printWindow = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
      try {
        await printWindow.loadURL('app://shanghan/api/v1/notes/' + id + '/export?format=html');
        await printWindow.webContents.executeJavaScript('document.fonts.ready.then(() => true)');
        await fs.writeFile(destination.filePath, await printWindow.webContents.printToPDF({ printBackground: true, preferCSSPageSize: true }));
      } finally { printWindow.destroy(); }
    }
    return { path: destination.filePath };
  });
  handle('library:backup', async () => {
    const selected = await dialog.showSaveDialog(mainWindow, { defaultPath: '伤寒论知识库备份.shanghan.zip', filters: [{ name: '知识库备份', extensions: ['zip'] }] });
    if (selected.canceled) return null;
    const result = await service('/internal/backup', {});
    await fs.copyFile(result.path, selected.filePath);
    return { path: selected.filePath, bytes: result.bytes };
  });
  handle('library:restore-preview', async () => {
    const selected = await dialog.showOpenDialog(mainWindow, { properties: ['openFile'], filters: [{ name: '知识库备份', extensions: ['zip'] }] });
    if (selected.canceled) return null;
    return service('/internal/restore-preview', { path: selected.filePaths[0] });
  });
  handle('library:restore', async preview => {
    const result = await service('/internal/restore', { id: preview.id, hash: preview.hash });
    restoredDirectories.add(result.directory);
    return result;
  });
  async function useDirectory(directory) {
    const config = await readJSON(configFile(), {});
    await atomicFile(configFile(), JSON.stringify({ ...config, data_directory: directory }, null, 2));
    app.relaunch(); app.quit(); return true;
  }
  handle('library:activate-restored', async directory => {
    if (!restoredDirectories.has(directory)) throw new Error('请先校验并恢复备份');
    return useDirectory(directory);
  });
  handle('library:choose', async () => {
    const selected = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory', 'createDirectory'] });
    if (selected.canceled) return null;
    const directory = selected.filePaths[0];
    const entries = await fs.readdir(directory);
    if (entries.length && !entries.includes('personal.sqlite')) throw new Error('请选择空目录或已有伤寒论知识库目录');
    return useDirectory(directory);
  });
  handle('library:reveal', () => shell.openPath(dataDirectory));
  handle('source:open', async id => {
    if (!validNoteId(id)) throw new Error('此来源没有独立原始文件');
    const source = await service('/api/v1/sources/' + id, undefined, 'GET');
    const originals = path.resolve(dataDirectory, 'originals');
    const target = path.resolve(dataDirectory, source.original);
    const relative = path.relative(originals, target);
    if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('原始文件路径无效');
    const error = await shell.openPath(target);
    if (error) throw new Error('无法打开原始文件，请检查系统是否安装对应阅读软件');
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({ width: 1440, height: 1000, minWidth: 960, minHeight: 680, title: '伤寒论智能体', backgroundColor: '#f6f3ed', show: false,
    icon: appIcon,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false } });
  mainWindow.removeMenu();
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event, url) => { if (!url.startsWith('app://shanghan/')) event.preventDefault(); });
  mainWindow.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  mainWindow.on('ready-to-show', () => { if (!process.env.SHANGHAN_TEST_DATA) mainWindow.show(); });
  await mainWindow.loadURL('app://shanghan/');
}
if (!app.requestSingleInstanceLock() && !process.env.SHANGHAN_TEST_DATA) app.quit();
else {
  app.on('second-instance', () => { if (mainWindow) { mainWindow.restore(); mainWindow.focus(); } });
  app.whenReady().then(async () => {
    await loadSettings(); await launchBackend(); registerProtocol(); registerActions(); await createWindow();
  }).catch(error => { if (process.env.SHANGHAN_TEST_DATA) console.error('启动失败', error.message); else dialog.showErrorBox('启动失败', error.message); app.quit(); });
}
app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
  if (!quitting && backend?.pid && backend.exitCode === null && !backend.killed) {
    event.preventDefault(); quitting = true;
    backend.stdin.write('shutdown\n'); backend.stdin.end();
    const timer = setTimeout(() => { backend.kill(); app.exit(0); }, 5000);
    backend.once('exit', () => { clearTimeout(timer); app.exit(0); });
  }
});
