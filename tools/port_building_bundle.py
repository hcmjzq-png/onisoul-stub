"""Port a verified, uncompressed Unity 3.5 PS3 building prefab to PC.

Offline, create-only. Preserves the source prefab graph, animation and bitmask;
uses original PC type metadata and decodes the original PS3 texture to RGBA32.
Requires the optional UnityPy/Pillow analysis environment, not the game server.
"""
from __future__ import annotations

import argparse
import copy
from ctypes import c_uint32
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_legacy_media import pack_pc, repack_serialized
from tools.repair_unityweb_lzma import layout


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_tree(obj) -> tuple[dict, int]:
    # UnityPy 1.10's accelerated big-endian reader misreads IEEE float fields.
    # The Python reader is also used to account for every source byte.
    from UnityPy.helpers import TypeTreeHelper
    obj.reset()
    result = TypeTreeHelper.read_value(obj.get_typetree_nodes(), obj, c_uint32(0))
    consumed = obj.Position - obj.byte_start
    tail = obj.get_raw_data()[consumed:]
    if tail and not (obj.type.name == "Mesh" and tail == b"\0" * 8):
        raise ValueError(f"unrecognized trailing {obj.type.name} data: {len(tail)} bytes")
    return result, len(tail)


def swap_words(data: bytes, width: int) -> bytes:
    if len(data) % width:
        raise ValueError("unaligned endian conversion")
    return b"".join(data[i:i + width][::-1] for i in range(0, len(data), width))


def mesh_to_pc(tree: dict) -> None:
    vertex = tree["m_VertexData"]
    if tree["m_MeshCompression"] != 0 or tree["m_Skin"] or tree["m_BindPose"]:
        raise ValueError("only the observed uncompressed static building mesh is supported")
    streams = [vertex[f"m_Streams[{i}]"] for i in range(4)]
    if vertex["m_CurrentChannels"] != 43 or streams[0]["channelMask"] != 43 or streams[0]["stride"] != 48:
        raise ValueError("unverified vertex channel/stride layout")
    if streams[0]["offset"] or any(s["channelMask"] or s["stride"] or s["offset"] for s in streams[1:]):
        raise ValueError("unverified vertex stream layout")
    if len(vertex["m_DataSize"]) != vertex["m_VertexCount"] * 48:
        raise ValueError("vertex buffer length mismatch")
    if any(v["m_NumItems"] for v in tree["m_CompressedMesh"].values()):
        raise ValueError("packed mesh data is not supported")
    raw = bytes(tree["m_IndexBuffer"])
    indices = struct.unpack(">" + "H" * (len(raw) // 2), raw)
    if indices and max(indices) >= vertex["m_VertexCount"]:
        raise ValueError("mesh index exceeds vertex count")
    tree["m_IndexBuffer"] = list(swap_words(raw, 2))
    vertex["m_DataSize"] = swap_words(bytes(vertex["m_DataSize"]), 4)


def external_signature(sf) -> list:
    return [(x.path, bytes(x.guid).hex(), x.type) for x in sf.externals]


def convert(source: Path, template: Path, logical: str) -> tuple[bytes, dict]:
    import UnityPy
    from UnityPy.streams import EndianBinaryWriter
    from PIL import Image

    source_blob, template_blob = source.read_bytes(), template.read_bytes()
    env = UnityPy.load(source_blob)
    original = list(env.objects)
    target_objects = list(UnityPy.load(template_blob).objects)
    if not original or not target_objects:
        raise ValueError("empty source/template")
    sf, target_sf = original[0].assets_file, target_objects[0].assets_file
    if sf.header.version != 9 or sf.header.endian != ">" or int(sf.target_platform) != 10:
        raise ValueError("Unity 3.5 big-endian PS3 source required")
    if target_sf.header.version != 9 or target_sf.header.endian != "<" or int(target_sf.target_platform) != 7:
        raise ValueError("Unity 3.5 little-endian PC template required")
    if sf.version[:2] != (3, 5) or target_sf.version[:2] != (3, 5):
        raise ValueError("only verified Unity 3.5 layouts are supported")
    if len({id(o.assets_file) for o in original}) != 1 or sf.script_types:
        raise ValueError("single serialized file without managed scripts required")
    source_external_pc = [(x.path, swap_words(bytes(x.guid), 4).hex(), x.type) for x in sf.externals]
    if source_external_pc != external_signature(target_sf):
        raise ValueError("source external resources differ from the PC template")
    schemas = {o.class_id: o for o in target_objects}
    if not {o.class_id for o in original} <= schemas.keys():
        raise ValueError("source contains a class absent from the PC template")
    if {o.path_id: o.class_id for o in original} != {o.path_id: o.class_id for o in target_objects}:
        raise ValueError("sample converter requires matching object identities/classes in the PC template")

    source_version = str(sf.unity_version)
    expected, mesh_proofs, texture_proofs = {}, [], []
    prefabs, collision = [], []
    for obj in original:
        if obj.type_id != obj.class_id:
            raise ValueError("unexpected legacy object type mapping")
        tree, trailer = read_tree(obj)
        if obj.type.name == "Mesh":
            mesh_to_pc(tree)
            mesh_proofs.append({"path_id": obj.path_id, "name": tree["m_Name"],
                                "vertices": tree["m_VertexData"]["m_VertexCount"],
                                "triangles": sum(s["triangleCount"] for s in tree["m_SubMeshes"]),
                                "zero_platform_trailer_removed": trailer})
        elif obj.type.name == "Texture2D":
            image = obj.read().image.convert("RGBA")
            pixels = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
            tree.update(m_Width=image.width, m_Height=image.height,
                        m_CompleteImageSize=len(pixels), m_TextureFormat=4, m_MipMap=False)
            tree["image data"] = pixels
            texture_proofs.append({"path_id": obj.path_id, "name": tree["m_Name"],
                                   "size": list(image.size), "pixel_sha256": sha(image.tobytes())})
        elif obj.type.name == "AnimationClip":
            if tree["m_Compressed"] or tree["m_CompressedRotationCurves"]:
                raise ValueError("compressed animation is not supported")
        elif obj.type.name == "GameObject":
            prefabs.append(tree["m_Name"])
        elif obj.type.name == "TextAsset":
            script = tree["m_Script"].encode("utf-8", "surrogateescape")
            width, height = struct.unpack_from("<II", script)
            if not width or not height or width * height % 8 or len(script) != 8 + width * height // 8:
                raise ValueError("unrecognized building collision bitmask")
            collision.append({"name": tree["m_Name"], "size": [width, height], "sha256": sha(script)})
        expected[obj.path_id] = copy.deepcopy(tree)
        target = schemas[obj.class_id]
        obj.save_typetree(tree, nodes=target.get_typetree_nodes(), writer=EndianBinaryWriter(endian="<"))
        obj.serialized_type = target.serialized_type
    if not collision or not any(name.startswith("building200_") for name in prefabs):
        raise ValueError("source is not a complete normal building prefab")
    if not any(p["name"] == logical + ".bin" for p in collision):
        raise ValueError("logical group does not match source collision data")

    # Keep the original PC v9 metadata. UnityPy's v9 metadata writer is not
    # suitable here; only verified object offsets, sizes and file length change.
    header_length, _compressed, _size = layout(template_blob)
    header = template_blob[:header_length]
    if target_sf.reader.Length != target_sf.header.file_size:
        raise ValueError("PC serialized-file bounds differ from its header")
    target_sf.reader.Position = 0
    template_node = target_sf.reader.read_bytes(target_sf.header.file_size)
    node = repack_serialized(template_node, target_sf,
                            {obj.path_id: obj.data for obj in original})
    archive = "CustomAssetBundle-" + hashlib.md5(node).hexdigest()
    result = pack_pc(header, archive, node)
    checked = list(UnityPy.load(result).objects)
    if {o.path_id for o in checked} != set(expected):
        raise ValueError("converted object identities changed")
    for obj in checked:
        actual, trailer = read_tree(obj)
        if trailer or actual != expected[obj.path_id]:
            raise ValueError(f"serialized roundtrip mismatch: {obj.type.name}:{obj.path_id}")
        if obj.type.name == "Texture2D":
            proof = next(p for p in texture_proofs if p["path_id"] == obj.path_id)
            if sha(obj.read().image.convert("RGBA").tobytes()) != proof["pixel_sha256"]:
                raise ValueError("converted texture pixels or orientation changed")
    proof = {"logical": logical, "source": str(source.resolve()), "source_sha256": sha(source_blob),
             "source_version": source_version, "template": str(template.resolve()),
             "template_sha256": sha(template_blob), "output_sha256": sha(result),
             "bytes": len(result), "pc_platform": 7, "pc_version": str(target_sf.unity_version),
             "archive": archive, "object_count": len(checked), "prefabs": prefabs,
             "meshes": mesh_proofs, "textures": texture_proofs, "collision_masks": collision,
             "all_objects_roundtrip_verified": True, "native_verified": False,
             "provenance": "original_ps3_building_with_pc_serialization_and_decoded_original_texture"}
    return result, proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--logical", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    name = hashlib.md5(args.logical.encode("utf-16le")).hexdigest() + ".unity3d"
    destination = args.out / name
    if destination.exists():
        parser.error("output exists; choose a fresh sample directory")
    result, proof = convert(args.source, args.template, args.logical)
    with destination.open("xb") as stream:
        stream.write(result)
    proof["output"] = str(destination.resolve())
    destination.with_suffix(".json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(destination), "bytes": len(result), "objects": proof["object_count"]}))


if __name__ == "__main__":
    main()
