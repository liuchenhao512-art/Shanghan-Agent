"""生成供 Mac 本地构建使用的源码包，不包含密钥、个人数据或平台运行环境。"""
from pathlib import Path
import hashlib
import json
import zipfile
root=Path(__file__).resolve().parents[1]
version=json.loads((root/'package.json').read_text(encoding='utf-8'))['version']
target=root/f'dist/Shanghan-Agent-{version}-source.zip'
target.parent.mkdir(exist_ok=True)
folders=('desktop','server','ui','scripts','tests','resources','参考资料')
files=[root/n for n in ('package.json','package-lock.json','requirements.txt','requirements.lock.txt','README.md','PROJECT_PLAN.md','AGENTS.md','桌面智能体客户端第一版方案.md','启动开发版.ps1','.gitignore','验证记录/验收记录.md')]
files += [p for p in (root/'验证记录').glob('*-qa.json') if p.name != 'core-qa.json' and json.loads(p.read_text(encoding='utf-8')).get('version',version) == version]
files += list((root/'验证记录').glob('*-tests.xml'))
files += list((root/'验证记录').glob(f'release-archive-{version}.json'))
# 已被新版验收记录替代的交付文档随旧安装包收纳，不混入新版源码包。
superseded = {'专题对话改版验收_2026-10-10.md','独立知识库与归档改版验收_2026-10-10.md','专题项目菜单验收_2026-10-10.md','正常对话与RAG验收_2026-10-11.md'}
files += [p for p in (root/'验证记录').glob('*.md') if p not in files and p.name not in superseded]
for name in folders:
    files += [p for p in (root/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,'Shanghan-Agent/'+p.relative_to(root).as_posix())
manifest={'file':target.name,'files':len(files),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
(root/'dist/source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(root/f'dist/source-manifest-{version}.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False))
