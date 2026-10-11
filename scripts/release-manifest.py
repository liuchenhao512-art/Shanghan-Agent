"""核对交付文件及源码包，保存可与测试报告对应的发布清单。"""
from pathlib import Path
import hashlib
import json
import time
import zipfile

root = Path(__file__).resolve().parents[1]
dist = root/'dist'
version = json.loads((root/'package.json').read_text(encoding='utf-8'))['version']

def file_record(path):
    return {'file':path.relative_to(root).as_posix(), 'bytes':path.stat().st_size,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

archive = dist/f'Shanghan-Agent-{version}-source.zip'
with zipfile.ZipFile(archive) as zipped:
    assert zipped.testzip() is None, '源码包校验失败'
    for name in zipped.namelist():
        parts = Path(name).parts
        assert not any(p in {'.venv','node_modules','.test-data','.dev-data','.env','credentials.bin'} for p in parts), name
    assert 'Shanghan-Agent/验证记录/验收记录.md' in zipped.namelist()
    for icon in ('source.png', 'icon.ico', 'icon.icns', 'icon.png', 'manifest.json'):
        assert f'Shanghan-Agent/resources/icons/{icon}' in zipped.namelist()
qa = json.loads((root/'验证记录/packaged-qa.json').read_text(encoding='utf-8'))
assert qa['passed'] and not qa['errors'], '打包程序验收未通过'
assert qa['version'] == version, '功能验收报告不是当前版本'
backend_qa = json.loads((root/'验证记录/backend-qa.json').read_text(encoding='utf-8'))
browser_qa = json.loads((root/'验证记录/browser-qa.json').read_text(encoding='utf-8'))
for report in (backend_qa,browser_qa):
    assert report['version'] == version and report['passed'], '后端或浏览器验收报告未通过或版本不符'
icon_qa = json.loads((root/'验证记录/icon-qa.json').read_text(encoding='utf-8'))
assert icon_qa['version'] == version and icon_qa['passed'] and not icon_qa['errors'], '当前版本图标验收未通过'
for record in icon_qa['files']:
    assert file_record(root/record['file'])['sha256'] == record['sha256'], '验证后的文件发生变化'
manifest = {
    'version':version, 'created':time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'status':'Windows trial; full cross-platform acceptance pending',
    'artifacts':[file_record(dist/f'Shanghan-Agent-{version}-win-x64.exe'),file_record(archive)],
    'checks':{'current_icon_and_runtime_groups':len(icon_qa['checks']),
              'backend_tests':backend_qa['tests'],'browser_groups':len(browser_qa['checks']),
              'functional_baseline':{'version':version,'packaged_desktop_groups':len(qa['checks']), 'model':'deterministic local service'},
              'reports':[file_record(p) for p in sorted((root/'验证记录').glob('*-qa.json'))
                         if p.name != 'core-qa.json' and json.loads(p.read_text(encoding='utf-8')).get('version',version) == version]},
    'platforms':{'windows_x64':{'built':True,'packaged_runtime_verified':True,'clean_install_verified':False,'signed':False},
                 'macos_arm64':{'built':False,'runtime_verified':False},
                 'macos_x64':{'built':False,'runtime_verified':False}},
}
for filename in ('release-manifest.json', f'release-manifest-{version}.json'):
    (dist/filename).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
