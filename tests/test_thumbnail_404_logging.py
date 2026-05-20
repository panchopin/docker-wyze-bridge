#!/usr/bin/env python3

import io
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
from requests.exceptions import HTTPError

try:
    from PIL import Image
except ImportError:
    Image = None

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

import wyzebridge.wyze_api as wyze_api_module
from wyzebridge.wyze_api import WyzeApi


def valid_jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    assert Image is not None
    image = Image.new("RGB", (48, 32), color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class TestThumbnail404Logging(unittest.TestCase):
    def test_thumbnail_404_logs_warning_not_error(self):
        api = WyzeApi()
        response = Mock(status_code=404)
        error = HTTPError("404 Client Error")
        error.response = response

        with (
            patch.object(
                WyzeApi,
                "get_thumbnail",
                return_value="https://example.test/thumb.jpg?X-Amz-Date=1",
            ),
            patch.object(wyze_api_module, "get", side_effect=error),
            patch.object(wyze_api_module.logger, "warning") as warning,
            patch.object(wyze_api_module.logger, "error") as err,
        ):
            result = api.save_thumbnail("hamster", "")

        self.assertFalse(result)
        warning.assert_called_once()
        err.assert_not_called()
        warning_message = warning.call_args.args[0]
        self.assertIn("Thumbnail unavailable for hamster", warning_message)
        self.assertIn("https://example.test/thumb.jpg", warning_message)
        self.assertNotIn("X-Amz-Date=1", warning_message)
        self.assertNotIn("404 Client Error", warning_message)

    def test_thumbnail_non_image_response_does_not_overwrite_valid_cache(self):
        api = WyzeApi()
        valid_image = valid_jpeg_bytes((24, 96, 180))
        response = Mock(headers={"Content-Type": "text/html"}, content=b"<!doctype html><html>login</html>")
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = pathlib.Path(temp_dir) / "hamster.jpg"
            save_path.write_bytes(valid_image)

            with (
                patch.object(WyzeApi, "get_thumbnail", return_value="https://example.test/thumb.jpg"),
                patch.object(wyze_api_module, "IMG_PATH", temp_dir + "/"),
                patch.object(wyze_api_module, "url_timestamp", return_value=0),
                patch.object(wyze_api_module, "get", return_value=response),
            ):
                result = api.save_thumbnail("hamster", "")

            self.assertFalse(result)
            self.assertEqual(save_path.read_bytes(), valid_image)

    def test_thumbnail_image_header_with_html_payload_does_not_overwrite_valid_cache(self):
        api = WyzeApi()
        valid_image = valid_jpeg_bytes((24, 96, 180))
        response = Mock(headers={"Content-Type": "image/jpeg"}, content=b"<!doctype html><html>redirect</html>")
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = pathlib.Path(temp_dir) / "garage.jpg"
            save_path.write_bytes(valid_image)

            with (
                patch.object(WyzeApi, "get_thumbnail", return_value="https://example.test/thumb.jpg"),
                patch.object(wyze_api_module, "IMG_PATH", temp_dir + "/"),
                patch.object(wyze_api_module, "url_timestamp", return_value=0),
                patch.object(wyze_api_module, "get", return_value=response),
            ):
                result = api.save_thumbnail("garage", "")

            self.assertFalse(result)
            self.assertEqual(save_path.read_bytes(), valid_image)

    def test_thumbnail_invalid_cached_file_is_replaced_with_valid_image(self):
        api = WyzeApi()
        replacement = valid_jpeg_bytes((180, 72, 24))
        response = Mock(headers={"Content-Type": "image/jpeg"}, content=replacement)
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = pathlib.Path(temp_dir) / "hamster.jpg"
            save_path.write_text("<!doctype html><html>stale login</html>", encoding="utf-8")

            with (
                patch.object(WyzeApi, "get_thumbnail", return_value="https://example.test/thumb.jpg"),
                patch.object(wyze_api_module, "IMG_PATH", temp_dir + "/"),
                patch.object(wyze_api_module, "url_timestamp", return_value=0),
                patch.object(wyze_api_module, "get", return_value=response),
            ):
                result = api.save_thumbnail("hamster", "")

            self.assertTrue(result)
            self.assertEqual(save_path.read_bytes(), replacement)

    def test_old_cloud_thumbnail_is_not_a_fresh_refresh(self):
        api = WyzeApi()
        existing_preview = valid_jpeg_bytes((40, 140, 90))

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = pathlib.Path(temp_dir) / "garage.jpg"
            save_path.write_bytes(existing_preview)

            with (
                patch.object(WyzeApi, "get_thumbnail", return_value="https://example.test/thumb_1000.jpg"),
                patch.object(wyze_api_module, "IMG_PATH", temp_dir + "/"),
                patch.object(wyze_api_module, "url_timestamp", return_value=1000),
                patch.object(wyze_api_module, "time", return_value=1400),
                patch.object(wyze_api_module, "get") as get,
            ):
                result = api.save_thumbnail("garage", "")

            self.assertFalse(result)
            get.assert_not_called()
            self.assertEqual(save_path.read_bytes(), existing_preview)

    def test_unchanged_cached_thumbnail_is_not_a_fresh_refresh(self):
        api = WyzeApi()
        valid_image = valid_jpeg_bytes((90, 50, 140))
        response = Mock(headers={"Content-Type": "image/jpeg"}, content=valid_image)
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = pathlib.Path(temp_dir) / "hamster.jpg"
            save_path.write_bytes(valid_image)

            with (
                patch.object(WyzeApi, "get_thumbnail", return_value="https://example.test/thumb_1000.jpg"),
                patch.object(wyze_api_module, "IMG_PATH", temp_dir + "/"),
                patch.object(wyze_api_module, "url_timestamp", return_value=1000),
                patch.object(wyze_api_module, "time", return_value=1200),
                patch.object(wyze_api_module, "get", return_value=response) as get,
            ):
                result = api.save_thumbnail("hamster", "")

            self.assertFalse(result)
            get.assert_called_once()
            self.assertEqual(save_path.read_bytes(), valid_image)

    def test_recent_unchanged_cached_thumbnail_is_not_a_fresh_refresh(self):
        api = WyzeApi()
        valid_image = valid_jpeg_bytes((140, 60, 90))
        response = Mock(headers={"Content-Type": "image/jpeg"}, content=valid_image)
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = pathlib.Path(temp_dir) / "hamster.jpg"
            save_path.write_bytes(valid_image)

            with (
                patch.object(WyzeApi, "get_thumbnail", return_value="https://example.test/thumb_1000.jpg"),
                patch.object(wyze_api_module, "IMG_PATH", temp_dir + "/"),
                patch.object(wyze_api_module, "url_timestamp", return_value=1000),
                patch.object(wyze_api_module, "time", return_value=1200),
                patch.object(wyze_api_module, "get", return_value=response) as get,
            ):
                result = api.save_thumbnail("hamster", "")

            self.assertFalse(result)
            get.assert_called_once()
            self.assertEqual(save_path.read_bytes(), valid_image)


if __name__ == "__main__":
    unittest.main()
