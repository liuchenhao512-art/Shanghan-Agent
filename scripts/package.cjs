const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname, '..');
const cache = path.join(root, 'build', 'tool-cache');
fs.mkdirSync(cache, { recursive: true });
const cli = require.resolve('electron-builder/out/cli/cli.js');
const args = process.argv.slice(2);
const localElectron = path.join(root, 'node_modules/electron/dist');
// 使用已安装的同版本 Windows 运行时，避免跨盘下载缓存的临时重命名失败。
if (process.platform === 'win32' && process.arch === 'x64' && args.includes('--win') && args.includes('--x64') && fs.existsSync(path.join(localElectron, 'electron.exe'))) {
  args.push('--config.electronDist=' + localElectron);
}
const result = spawnSync(process.execPath, [cli, ...args], {
  cwd: root, stdio: 'inherit', windowsHide: true,
  env: { ...process.env, ELECTRON_BUILDER_CACHE: cache }
});
process.exit(result.status || 0);
