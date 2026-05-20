#!/usr/bin/env python3

import io
import pathlib
import sys
import tempfile
import unittest

try:
    from PIL import Image
except ImportError:
    Image = None

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from wyzebridge.preview_validation import (  # noqa: E402
    preview_bytes_are_image,
    preview_bytes_are_valid_image,
    preview_content_hash,
    preview_file_is_image,
    preview_payload_matches_existing,
    read_snapshot_hash_registry,
    record_preview_hash,
)


def jpeg_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def coherent_preview() -> bytes:
    assert Image is not None
    image = Image.new("RGB", (320, 180))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = ((x * 3 + y) % 256, (x + y * 2) % 256, (x * 2 + y * 3) % 256)
    return jpeg_bytes(image)


def smeared_preview() -> bytes:
    assert Image is not None
    image = Image.new("RGB", (320, 180))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if y < 70:
                pixels[x, y] = ((x * 4 + y * 3) % 256, (x + y * 5) % 256, (x * 2 + y) % 256)
            else:
                value = (x * 9) % 256
                pixels[x, y] = (value, 255 - value, (value * 3) % 256)
    return jpeg_bytes(image)


def bottom_band_smeared_preview() -> bytes:
    assert Image is not None
    image = Image.new("RGB", (320, 180))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if y < 120:
                pixels[x, y] = ((x * 2 + y * 4) % 256, (x * 3 + y) % 256, (x + y * 2) % 256)
            else:
                value = (x * 7) % 256
                pixels[x, y] = (value, 255 - value, value // 2)
    return jpeg_bytes(image)


class TestPreviewValidation(unittest.TestCase):
    def test_header_check_still_accepts_jpeg_signature(self):
        self.assertTrue(preview_bytes_are_image(b"\xff\xd8\xff\xe0" + b"0" * 32))

    @unittest.skipUnless(Image is not None, "Pillow is required for synthetic JPEG generation")
    def test_valid_image_accepts_coherent_preview(self):
        self.assertTrue(preview_bytes_are_valid_image(coherent_preview()))

    @unittest.skipUnless(Image is not None, "Pillow is required for synthetic JPEG generation")
    def test_valid_image_rejects_lower_frame_vertical_smear(self):
        self.assertFalse(preview_bytes_are_valid_image(smeared_preview()))

    @unittest.skipUnless(Image is not None, "Pillow is required for synthetic JPEG generation")
    def test_valid_image_rejects_bottom_band_vertical_smear(self):
        self.assertFalse(preview_bytes_are_valid_image(bottom_band_smeared_preview()))

    @unittest.skipUnless(Image is not None, "Pillow is required for synthetic JPEG generation")
    def test_file_validation_rejects_lower_frame_vertical_smear(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "smeared.jpg"
            path.write_bytes(smeared_preview())
            self.assertFalse(preview_file_is_image(path))

    @unittest.skipUnless(Image is not None, "Pillow is required for synthetic JPEG generation")
    def test_snapshot_hash_registry_tracks_camera_content(self):
        payload = coherent_preview()

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "garage.jpg"
            path.write_bytes(payload)

            digest = record_preview_hash(path, payload, camera="garage", source="test")
            registry = read_snapshot_hash_registry(tmp)

            self.assertEqual(digest, preview_content_hash(payload))
            self.assertTrue(preview_payload_matches_existing(path, payload))
            self.assertEqual(registry["garage"]["sha256"], digest)
            self.assertEqual(registry["garage"]["source"], "test")


if __name__ == "__main__":
    unittest.main()
