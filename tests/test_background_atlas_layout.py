import unittest
try:
    from PIL import Image
except ImportError:
    Image = None
from tools.background_atlas_layout import continuous_distant, preserve_grass_bc3, preserve_grass_pixels, join_error, GRASS_BOX


@unittest.skipUnless(Image is not None, 'Pillow optional media dependency is required')
class AtlasLayoutTest(unittest.TestCase):
    def test_cyclic_panels_and_repeating_sky_share_edge_pixels(self):
        image = Image.new('RGBA', (1024, 1024))
        image.putdata([(x % 256, y % 256, (x + y) % 256, 255) for y in range(1024) for x in range(1024)])
        output = continuous_distant(image)
        self.assertEqual(join_error(output), [[0.0] * 4] * 3)
        for y in range(859, 1024):
            self.assertEqual(output.getpixel((0, y)), output.getpixel((1023, y)))

    def test_original_grass_and_compressed_blocks_are_preserved(self):
        image = Image.new('RGBA', (1024, 1024), (1, 2, 3, 255))
        reference = Image.new('RGBA', image.size, (60, 80, 10, 255))
        output = preserve_grass_pixels(image, reference)
        self.assertEqual(output.crop(GRASS_BOX).tobytes(), reference.crop(GRASS_BOX).tobytes())
        self.assertEqual(output.getpixel((600, 200)), image.getpixel((600, 200)))
        data = preserve_grass_bc3(bytes([1]) * 1048576, bytes([2]) * 1048576)
        self.assertEqual(data.count(2), 36 * 144 * 16)
        self.assertEqual(data[:16], bytes([1]) * 16)
        self.assertEqual(data[220 * 4096:220 * 4096 + 16], bytes([2]) * 16)

    def test_invalid_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            preserve_grass_bc3(b'bad', b'bad')
