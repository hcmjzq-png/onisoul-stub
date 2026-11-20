"""Stage local PvE card art and labelled test textures for missing skill bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_navigator_compat import rebuild
from tools.setup_local_pve_roster import ROSTER


def bundle_name(logical: str) -> str:
    return hashlib.md5(logical.encode("utf-16le")).hexdigest() + ".unity3d"


def plate(size: tuple[int, int], title: str, label: str, font_path: Path):
    from PIL import Image, ImageDraw, ImageFont

    width, height = size
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    left, top = width // 32, height // 6
    bottom = height - top
    draw.rounded_rectangle((left, top, width - left, bottom), radius=min(width, height) // 10,
                           fill="#153a48", outline="#76d6dc", width=max(1, height // 64))
    title_size = min(height // 3, width * 7 // (8 * len(title)))
    title_font = ImageFont.truetype(str(font_path), title_size)
    label_font = ImageFont.truetype(str(font_path), max(10, min(width, height) // 7))
    draw.text((width // 2, height * 4 // 9), title, font=title_font, anchor="mm", fill="#f0fcfd")
    draw.text((width // 2, height * 2 // 3), label, font=label_font, anchor="mm", fill="#9be4e8")
    return image


def card_texture(art, size: tuple[int, int]):
    from PIL import Image, ImageOps

    if size == art.size:
        return art
    # The viewer's title sits along the top of its 1024-pixel battle canvas.
    # Use the existing illustration for the smaller card views as well.
    subject = art.crop((0, 48, art.width, art.height))
    subject = subject.crop(subject.getchannel("A").getbbox())
    resized = ImageOps.contain(subject, size, Image.Resampling.LANCZOS)
    result = Image.new("RGBA", size)
    result.alpha_composite(resized, ((size[0] - resized.width) // 2, size[1] - resized.height))
    return result


def main() -> None:
    import UnityPy
    from PIL import Image

    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("bundles", "tables", "font", "out"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--art", type=Path, help="Local 1024 × 1024 RGBA PNG files named by base card ID")
    args = parser.parse_args()

    def table(name: str) -> dict:
        value = json.loads((args.tables / (name + ".json")).read_text(encoding="utf-8-sig"))
        return next(iter(value.values()))

    def stage(category: str, prefix: str, template: str, title: str, label: str, art_path=None) -> None:
        relative = Path(category) / bundle_name(prefix)
        has_art = art_path is not None and art_path.is_file()
        if (args.bundles / relative).exists() and not has_art:
            return
        data = (args.bundles / category / bundle_name(template)).read_bytes()
        art = None
        if has_art:
            with Image.open(art_path) as image:
                if image.size != (1024, 1024) or image.mode != "RGBA" or not image.getbbox():
                    raise ValueError(f"expected a nonempty 1024 × 1024 RGBA image for {prefix}")
                art = image.copy()
        name_map, textures = {}, {}
        for obj in UnityPy.load(data).objects:
            if obj.type.name == "Texture2D":
                tex = obj.read()
                name = prefix + tex.m_Name.removeprefix(template)
                name_map[tex.m_Name] = name
                size = (tex.m_Width, tex.m_Height)
                textures[name] = card_texture(art, size) if art else plate(size, title, label, args.font)
        blob, _ = rebuild(data, textures, name_map=name_map)
        if set(UnityPy.load(blob).container) != {name.lower() for name in textures}:
            raise ValueError(f"incorrect PC bindings for {prefix}")
        target = args.out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(blob)
        manifest[relative.as_posix()] = {"logical": prefix, "members": list(textures),
                                       "sha256": hashlib.sha256(blob).hexdigest()}
        if art is not None:
            manifest[relative.as_posix()]["art_sha256"] = hashlib.sha256(art_path.read_bytes()).hexdigest()

    args.out.mkdir(parents=True)
    skills, messages = table("skill"), table("skillMessage")
    characters = table("character")
    item_names = table("item01Message")
    names = {}
    for item in table("item01").values():
        value = item_names.get(item.get("nameId"), {})
        name = value.get("tw") or value.get("jp")
        if name and item.get("parameterId"):
            names.setdefault(item["parameterId"], name)
    manifest = {}
    for base_id, skill_ids in ROSTER:
        name = names[base_id]
        prefix = f"{characters[base_id]['images']}_{len(skill_ids) * 2:02d}"
        art_path = args.art / (base_id + ".png") if args.art else None
        stage("chara", prefix, "chara1_01072_01", name, "临时卡图", art_path)
        for skill_id in skill_ids:
            row = skills[skill_id]
            stage("skillplate", row["images"], "skill1_04011_01",
                  messages[row["name"]]["tw"], "本地测试")
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Staged {len(manifest)} local-only test bundles.")


if __name__ == "__main__":
    main()
