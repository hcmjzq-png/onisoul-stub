"""Guards for the observed legacy PS3 building vertex layout."""
import copy
import struct
import unittest

from tools.port_building_bundle import mesh_to_pc


def mesh():
    values = (256.0, -128.0, 0.0, 0.0, 0.0, 1.0, 0.25, 0.75, -1.0, 0.0, 0.0, -1.0)
    vertex = {"m_CurrentChannels": 43, "m_VertexCount": 1,
              "m_DataSize": struct.pack(">12f", *values)}
    for index in range(4):
        vertex[f"m_Streams[{index}]"] = {"channelMask": 43 if index == 0 else 0,
                                        "offset": 0, "stride": 48 if index == 0 else 0}
    return {"m_MeshCompression": 0, "m_Skin": [], "m_BindPose": [],
            "m_VertexData": vertex, "m_IndexBuffer": list(struct.pack(">H", 0)),
            "m_CompressedMesh": {"m_Vertices": {"m_NumItems": 0}}}, values


class BuildingMeshPortTests(unittest.TestCase):
    def test_pc_vertices_preserve_coordinates_uvs_normals_and_tangents(self):
        tree, expected = mesh()
        mesh_to_pc(tree)
        self.assertEqual(struct.unpack("<12f", tree["m_VertexData"]["m_DataSize"]), expected)
        self.assertEqual(struct.unpack("<H", bytes(tree["m_IndexBuffer"])), (0,))

    def test_rejects_out_of_range_indices(self):
        tree, _ = mesh()
        tree["m_IndexBuffer"] = list(struct.pack(">H", 1))
        with self.assertRaisesRegex(ValueError, "index exceeds"):
            mesh_to_pc(tree)

    def test_rejects_other_vertex_formats_and_packed_geometry(self):
        original, _ = mesh()
        for change in ("stride", "compression", "packed"):
            with self.subTest(change=change):
                tree = copy.deepcopy(original)
                if change == "stride":
                    tree["m_VertexData"]["m_Streams[0]"]["stride"] = 52
                elif change == "compression":
                    tree["m_MeshCompression"] = 1
                else:
                    tree["m_CompressedMesh"]["m_Vertices"]["m_NumItems"] = 3
                with self.assertRaises(ValueError):
                    mesh_to_pc(tree)


if __name__ == "__main__":
    unittest.main()
