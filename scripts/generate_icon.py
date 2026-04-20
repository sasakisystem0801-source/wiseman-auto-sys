"""Wiseman PDF Tool のデスクトップアイコンを生成する。

文字ベースの簡易アイコン（白背景に "W" 文字）。
256/128/64/48/32/16 px のマルチサイズ .ico を作成、Windows の
エクスプローラー / タスクバー / ショートカットで表示される。

実行:
    uv run python scripts/generate_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_PATH = Path("assets/icon.ico")
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

BG_COLOR = (0, 102, 204, 255)  # 青系（医療・信頼感）
FG_COLOR = (255, 255, 255, 255)  # 白文字


def _find_bold_font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """OSごとに存在する太字フォントを探す。見つからなければデフォルト。"""
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, int(px * 0.7))
            except OSError:
                continue
    return ImageFont.load_default()


def _render_square(size: int) -> Image.Image:
    """1 サイズ分の Image を生成する（角丸青背景 + 白 "W"）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = max(2, size // 8)
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=BG_COLOR)

    text = "W"
    font = _find_bold_font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2 - bbox[0]
    y = (size - text_h) // 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=FG_COLOR)

    return img


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    base = _render_square(256)
    base.save(OUT_PATH, format="ICO", sizes=SIZES)
    print(f"Generated: {OUT_PATH} ({', '.join(f'{w}x{h}' for w, h in SIZES)})")


if __name__ == "__main__":
    main()
