"""将已确认的原图编码为透明圆角平台图标，保留图案与字体。需要 Pillow。"""
from pathlib import Path
import hashlib
import json
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'resources' / 'icons'
SOURCE = DIRECTORY / 'source.png'
ICO_SIZES = [(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
CORNER_RADIUS_RATIO = 0.16


def main():
    image = Image.open(SOURCE).convert('RGBA')
    if image.width != image.height:
        raise ValueError('请使用已确认的正方形图标原图，避免拉伸或裁切。')
    # 用户确认使用圆角外轮廓；原图保持不变，仅为导出图标添加透明圆角。
    scale = 3
    mask = Image.new('L', (image.width * scale, image.height * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1),
                                          radius=image.width * CORNER_RADIUS_RATIO * scale, fill=255)
    mask = mask.resize(image.size, Image.Resampling.LANCZOS)
    image.putalpha(ImageChops.multiply(image.getchannel('A'), mask))
    image.resize((512, 512), Image.Resampling.LANCZOS).save(DIRECTORY / 'icon.png')
    image.save(DIRECTORY / 'icon.ico', sizes=ICO_SIZES)
    image.resize((1024, 1024), Image.Resampling.LANCZOS).save(DIRECTORY / 'icon.icns')
    image.resize((128, 128), Image.Resampling.LANCZOS).save(ROOT / 'ui' / 'app-icon.png')
    ico = Image.open(DIRECTORY / 'icon.ico')
    assert ico.ico.sizes() == set(ICO_SIZES)
    icns = Image.open(DIRECTORY / 'icon.icns')
    assert icns.size == (1024, 1024)
    for filename in (DIRECTORY / 'icon.png', DIRECTORY / 'icon.ico', DIRECTORY / 'icon.icns', ROOT / 'ui' / 'app-icon.png'):
        exported = Image.open(filename).convert('RGBA')
        assert exported.getpixel((0, 0))[3] == 0
        assert exported.getpixel((exported.width // 2, exported.height // 2))[3] == 255
    records = []
    for filename in (SOURCE, DIRECTORY / 'icon.png', DIRECTORY / 'icon.ico', DIRECTORY / 'icon.icns', ROOT / 'ui' / 'app-icon.png'):
        records.append({'file': filename.relative_to(ROOT).as_posix(), 'bytes': filename.stat().st_size,
                        'sha256': hashlib.sha256(filename.read_bytes()).hexdigest()})
    manifest = {'selection_date': '2026-10-09', 'source': '用户最终上传确认的蓝底繁体伤寒论图标',
                'corner_radius_ratio': CORNER_RADIUS_RATIO, 'transparent_corners': True,
                'source_dimensions': [image.width, image.height], 'ico_sizes': sorted(ico.ico.sizes()),
                'macos_runtime_verified': False, 'artifacts': records}
    (DIRECTORY / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
