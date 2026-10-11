"""一次性复制原项目的可运行基线；不读取密钥，不改动来源目录。"""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r'D:\工作\数智赋能中医药人才培养和文化传播\伤寒论知识库')

def main():
    mapping = {'app/main.py': 'server/legacy.py',
               'app/static/index.html': 'ui/classic.html',
               'data/db/kb.sqlite': 'resources/builtin/kb.sqlite'}
    mapping.update({str(p.relative_to(SOURCE)).replace('\\', '/'): 'resources/builtin/parsed/' + p.name
                    for p in (SOURCE / 'data/parsed').glob('*.json')})
    manifest = {'source': str(SOURCE), 'date': '2026-10-08', 'files': []}
    for src, dest in mapping.items():
        target = ROOT / dest
        if target.exists():
            raise RuntimeError(f'目标已存在，拒绝覆盖: {target}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / src, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest['files'].append({'source': src, 'target': dest, 'sha256': digest, 'bytes': target.stat().st_size})
    (ROOT / 'resources/builtin/migration-manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'已迁移 {len(mapping)} 个文件，来源目录未改动。')

if __name__ == '__main__':
    main()
