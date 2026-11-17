"""Arrange unchanged native castle renders into a labeled review figure/gallery."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def main() -> None:
    from PIL import Image, ImageDraw, ImageFont
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--font", type=Path, required=True)
    args = ap.parse_args()
    manifest = json.loads((args.release / "manifest.json").read_text(encoding="utf-8"))
    rows = manifest["files"]
    if len(rows) != 15 or manifest.get("native_verified_count") != 15:
        raise ValueError("all fifteen native renders must pass before creating the gallery")
    colors = {"human": "#dbbd70", "oni": "#dc9b87", "evil": "#adb9ea"}
    titles = {"human": "人族", "oni": "鬼族", "evil": "幻魔族"}
    font = lambda size: ImageFont.truetype(str(args.font), size)
    width, height = 2160, 1230
    figure = Image.new("RGB", (width, height), "#101a15")
    draw = ImageDraw.Draw(figure)
    draw.text((42, 24), "三族城堡 · 1—5 品原版外观", fill="#f1e9d5", font=font(38))
    draw.text((44, 81), "15 款原引擎渲染通过  ·  14 款缺失资源补齐候选  ·  1 款原有 PC 包保留", fill="#b9c6bc", font=font(22))
    left, cell_width, gap = 144, 386, 16
    for grade in range(1, 6):
        x = left + (grade - 1) * (cell_width + gap)
        draw.text((x + 10, 130), f"{grade} 品", fill="#eee4ce", font=font(27))
        draw.text((x + 98, 136), f"等级上限 {grade * 10}", fill="#93a99b", font=font(19))
    for row_index, tribe in enumerate(("human", "oni", "evil")):
        y = 184 + row_index * 338
        draw.text((32, y + 118), titles[tribe], fill=colors[tribe], font=font(30))
        for row in (r for r in rows if r["tribe"] == tribe):
            x = left + (row["grade"] - 1) * (cell_width + gap)
            with Image.open(args.release / row["preview"]) as image:
                if image.size != (680, 510):
                    raise ValueError("unexpected native preview dimensions")
                # Contact-sheet layout only; the full-size native PNG is retained.
                thumb = image.convert("RGB").resize((386, 290), Image.Resampling.LANCZOS)
            figure.paste(thumb, (x, y))
            draw.rectangle((x, y, x + 385, y + 289), outline="#344d3d", width=1)
            badge = "原有 PC 包 · 保留" if row["pc_existing"] else "原版素材 · 补齐候选"
            draw.text((x + 10, y + 298), badge, fill="#c0cbbb", font=font(18))
    draw.text((44, 1200), "同一相机比例；纯色为预览衬底。未安装到游戏资源目录，已有建筑与存档未修改。", fill="#93a99b", font=font(20))
    figure.save(args.release / "castles-1-to-5-overview.png")
    sections = []
    for tribe in ("human", "oni", "evil"):
        cards = []
        for row in (r for r in rows if r["tribe"] == tribe):
            image_path = html.escape(row["preview"], quote=True)
            badge = "原有 PC 包保留" if row["pc_existing"] else "原版素材补齐候选"
            cards.append(f'<article><a href="{image_path}" target="_blank"><img src="{image_path}" alt="{titles[tribe]}{row["grade"]}品城堡"></a>'
                         f'<div class="caption"><strong>{row["grade"]} 品</strong><span>等级上限 {row["level_cap"]}</span></div>'
                         f'<p>{badge}</p></article>')
        sections.append(f'<section id="{tribe}" style="--tribe:{colors[tribe]}"><h2>{titles[tribe]}</h2><div class="grid">' + ''.join(cards) + '</div></section>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>三族城堡 1–5 品原版预览</title><style>
*{box-sizing:border-box}body{margin:0;background:#101a15;color:#eee6d5;font:16px "Microsoft YaHei",sans-serif;padding:32px}
header,main{max-width:2000px;margin:auto}h1{font-size:30px;margin:0 0 12px}header p{color:#b9c6bc;line-height:1.7}
nav{display:flex;gap:10px;margin:20px 0 30px;flex-wrap:wrap}a{color:#dfc784}nav a{padding:8px 15px;border:1px solid #425846;border-radius:6px;text-decoration:none}
section{margin:28px 0 36px}h2{font-size:24px;color:var(--tribe);border-left:4px solid var(--tribe);padding-left:12px}
.grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:16px}article{background:#1e2b23;border:1px solid #344d3d;border-radius:8px;overflow:hidden}img{width:100%;display:block}
.caption{display:flex;justify-content:space-between;gap:8px;margin:13px 14px 8px}.caption span{font-size:14px;color:#a9bdad}article p{margin:8px 14px 15px;color:#b1c3b5;font-size:14px}
@media(max-width:1100px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:650px){body{padding:18px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style><header><h1>三族城堡 · 1—5 品</h1><p>15 款均由原版 Unity 引擎加载并渲染。14 款缺失资源已制作独立 PC 候选包，人族 1 品沿用已有 PC 原包。<br>
按同一相机比例展示；点击任意图片查看 680×510 原图。纯色仅为预览衬底，当前未安装到游戏资源目录。</p>
<nav><a href="#human">人族</a><a href="#oni">鬼族</a><a href="#evil">幻魔族</a><a href="castles-1-to-5-overview.png" target="_blank">完整对照图</a></nav></header><main>'''
    (args.release / "gallery.html").write_text(page + ''.join(sections) + '</main></html>', encoding="utf-8")
    print(args.release / "castles-1-to-5-overview.png")
    print(args.release / "gallery.html")


if __name__ == "__main__":
    main()
