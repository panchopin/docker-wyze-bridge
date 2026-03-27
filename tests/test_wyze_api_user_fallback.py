#!/usr/bin/env python3

import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from unittest.mock import patch


class DummyLogger:
    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


@dataclass
class FakeWyzeCredential:
    access_token: str | None = None
    refresh_token: str | None = None
    user_id: str | None = None
    phone_id: str | None = None


@dataclass
class FakeWyzeAccount:
    phone_id: str
    logo: str
    nickname: str
    email: str
    user_code: str
    user_center_id: str
    open_user_id: str


@dataclass
class FakeWyzeCamera:
    name_uri: str = "dog-run"


class FakeWyzeAPIError(Exception):
    pass


class FakeRateLimitError(Exception):
    pass


class FakeAccessTokenError(Exception):
    pass


class FakeConnectionError(Exception):
    pass


class FakeHTTPError(Exception):
    pass


class FakeRequestException(Exception):
    pass


def load_wyze_api_module(token_path: str):
    requests_module = types.ModuleType("requests")
    requests_module.get = lambda *args, **kwargs: None
    requests_module.post = lambda *args, **kwargs: None
    requests_module.HTTPError = FakeHTTPError

    requests_exceptions = types.ModuleType("requests.exceptions")
    requests_exceptions.ConnectionError = FakeConnectionError
    requests_exceptions.HTTPError = FakeHTTPError
    requests_exceptions.RequestException = FakeRequestException

    wyzecam_api_models = types.ModuleType("wyzecam.api_models")
    wyzecam_api_models.WyzeAccount = FakeWyzeAccount
    wyzecam_api_models.WyzeCamera = FakeWyzeCamera
    wyzecam_api_models.WyzeCredential = FakeWyzeCredential

    wyzecam_api = types.ModuleType("wyzecam.api")
    wyzecam_api.AccessTokenError = FakeAccessTokenError
    wyzecam_api.RateLimitError = FakeRateLimitError
    wyzecam_api.WyzeAPIError = FakeWyzeAPIError
    wyzecam_api._headers = lambda *args, **kwargs: {}
    wyzecam_api.get_cam_webrtc = lambda *args, **kwargs: {}
    wyzecam_api.get_camera_list = lambda *args, **kwargs: []
    wyzecam_api.get_camera_stream = lambda *args, **kwargs: None
    wyzecam_api.get_user_info = lambda *args, **kwargs: None
    wyzecam_api.login = lambda *args, **kwargs: None
    wyzecam_api.post_device = lambda *args, **kwargs: {}
    wyzecam_api.refresh_token = lambda auth: auth
    wyzecam_api.run_action = lambda *args, **kwargs: {}
    wyzecam_api.wakeup_kvs_camera = lambda *args, **kwargs: None

    wyzecam_package = types.ModuleType("wyzecam")
    wyzecam_package.api = wyzecam_api
    wyzecam_package.api_models = wyzecam_api_models

    auth_module = types.ModuleType("wyzebridge.auth")
    auth_module.get_secret = lambda name, default="": {
        "WYZE_EMAIL": "person@example.com",
        "WYZE_PASSWORD": "secret",
        "API_ID": "key-id",
        "API_KEY": "api-key",
    }.get(name, default)

    bridge_utils = types.ModuleType("wyzebridge.bridge_utils")
    bridge_utils.env_bool = lambda *args, default="", **kwargs: default
    bridge_utils.env_list = lambda *args, **kwargs: []

    config_module = types.ModuleType("wyzebridge.config")
    config_module.IMG_PATH = token_path
    config_module.MOTION = False
    config_module.TOKEN_PATH = token_path

    logging_module = types.ModuleType("wyzebridge.logging")
    logging_module.logger = DummyLogger()

    module_name = "test_wyzebridge_wyze_api"
    module_path = pathlib.Path(__file__).resolve().parent.parent / "app" / "wyzebridge" / "wyze_api.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)

    fake_modules = {
        "requests": requests_module,
        "requests.exceptions": requests_exceptions,
        "wyzecam": wyzecam_package,
        "wyzecam.api_models": wyzecam_api_models,
        "wyzecam.api": wyzecam_api,
        "wyzebridge.auth": auth_module,
        "wyzebridge.bridge_utils": bridge_utils,
        "wyzebridge.config": config_module,
        "wyzebridge.logging": logging_module,
    }
    with patch.dict(sys.modules, fake_modules):
        sys.modules.pop(module_name, None)
        assert spec and spec.loader
        spec.loader.exec_module(module)
    module.pickle_dump = lambda *args, **kwargs: None
    return module


class TestWyzeApiUserFallback(unittest.TestCase):
    def test_get_user_builds_fallback_profile_when_api_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            module = load_wyze_api_module(tmpdir + "/")
            api = module.WyzeApi()
            api.auth = FakeWyzeCredential(access_token="token", phone_id="phone-123")

            user = api.get_user()

            self.assertIsNotNone(user)
            self.assertEqual(user.email, "person@example.com")
            self.assertEqual(user.nickname, "person")
            self.assertEqual(user.phone_id, "phone-123")
            self.assertEqual(user.open_user_id, "")

    def test_get_user_builds_fallback_profile_when_api_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            module = load_wyze_api_module(tmpdir + "/")
            api = module.WyzeApi()
            api.auth = FakeWyzeCredential(access_token="token", phone_id="phone-456")

            with patch.object(
                module,
                "get_user_info",
                side_effect=module.WyzeAPIError("internal error"),
            ):
                user = api.get_user()

            self.assertIsNotNone(user)
            self.assertEqual(user.email, "person@example.com")
            self.assertEqual(user.nickname, "person")
            self.assertEqual(user.phone_id, "phone-456")


if __name__ == "__main__":
    unittest.main()
