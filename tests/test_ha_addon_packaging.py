import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = ROOT / "home_assistant"


class TestHomeAssistantAddonPackaging(unittest.TestCase):
    def test_all_ha_dockerfiles_avoid_hidden_env_dependency(self):
        dockerfiles = [
            ADDON_DIR / "Dockerfile",
            ADDON_DIR / "docker/Dockerfile",
            ADDON_DIR / "docker/Dockerfile.multiarch",
            ADDON_DIR / "docker/Dockerfile.hwaccel",
        ]
        for dockerfile_path in dockerfiles:
            with self.subTest(dockerfile=str(dockerfile_path.relative_to(ROOT))):
                dockerfile = dockerfile_path.read_text()
                self.assertNotIn(
                    ". app/.env",
                    dockerfile,
                    f"{dockerfile_path.relative_to(ROOT)} should not depend on a hidden .env file that HA strips from build context",
                )

    def test_addon_dockerfile_avoids_buildkit_only_mount_syntax(self):
        dockerfile = (ADDON_DIR / "Dockerfile").read_text()
        self.assertNotIn(
            "--mount=type=cache",
            dockerfile,
            "home_assistant/Dockerfile should avoid BuildKit-only cache mounts so HA can build the add-on locally",
        )

    def test_addon_build_env_version_matches_public_addon_version(self):
        config_text = (ADDON_DIR / "config.yml").read_text()
        env_text = (ADDON_DIR / "app/build.env").read_text()

        config_version = re.search(r"^version:\s*(.+)$", config_text, re.MULTILINE)
        env_version = re.search(r"^VERSION=(.+)$", env_text, re.MULTILINE)

        self.assertIsNotNone(config_version)
        self.assertIsNotNone(env_version)
        assert config_version is not None
        assert env_version is not None
        self.assertEqual(
            config_version.group(1).strip(),
            env_version.group(1).strip(),
            "home_assistant/app/build.env VERSION should match home_assistant/config.yml version for source-built add-ons",
        )

    def test_local_dev_addon_has_distinct_identity(self):
        prod_config = (ADDON_DIR / "config.yml").read_text()
        dev_config = (ROOT / ".ha_live_addon" / "config.yml").read_text()

        prod_slug = re.search(r"^slug:\s*(.+)$", prod_config, re.MULTILINE)
        dev_slug = re.search(r"^slug:\s*(.+)$", dev_config, re.MULTILINE)
        dev_name = re.search(r"^name:\s*(.+)$", dev_config, re.MULTILINE)
        dev_version = re.search(r"^version:\s*(.+)$", dev_config, re.MULTILINE)

        self.assertIsNotNone(prod_slug)
        self.assertIsNotNone(dev_slug)
        self.assertIsNotNone(dev_name)
        self.assertIsNotNone(dev_version)
        assert prod_slug is not None
        assert dev_slug is not None
        assert dev_name is not None
        assert dev_version is not None

        self.assertNotEqual(
            prod_slug.group(1).strip(),
            dev_slug.group(1).strip(),
            "the local HA dev add-on should use a distinct slug from production",
        )
        self.assertEqual(dev_slug.group(1).strip(), "docker_wyze_bridge_dev")
        self.assertEqual(dev_name.group(1).strip(), "Docker Wyze Bridge (Dev Build)")
        self.assertEqual(dev_version.group(1).strip(), "4.0.2")

    def test_local_dev_addon_yaml_and_yml_manifests_match(self):
        dev_yml = (ROOT / ".ha_live_addon" / "config.yml").read_text()
        dev_yaml = (ROOT / ".ha_live_addon" / "config.yaml").read_text()

        self.assertEqual(
            dev_yml,
            dev_yaml,
            ".ha_live_addon/config.yaml should mirror .ha_live_addon/config.yml so Home Assistant local add-on discovery works on systems expecting either filename",
        )

    def test_ha_login_fields_are_visible_by_default(self):
        addon_configs = {
            "prod": (ADDON_DIR / "config.yml").read_text(),
            "dev": (ROOT / ".ha_live_addon" / "config.yml").read_text(),
        }

        expected_defaults = {
            "WYZE_EMAIL": '  WYZE_EMAIL: ""',
            "WYZE_PASSWORD": '  WYZE_PASSWORD: ""',
            "API_ID": '  API_ID: ""',
            "API_KEY": '  API_KEY: ""',
        }
        expected_schema = {
            "WYZE_EMAIL": "  WYZE_EMAIL: email",
            "WYZE_PASSWORD": "  WYZE_PASSWORD: password",
            "API_ID": "  API_ID: match(\\s*[a-fA-F0-9-]{36}\\s*)",
            "API_KEY": "  API_KEY: match(\\s*[a-zA-Z0-9]{60}\\s*)",
        }

        for addon_name, config_text in addon_configs.items():
            with self.subTest(addon=addon_name):
                for field_name, default_line in expected_defaults.items():
                    self.assertIn(
                        default_line,
                        config_text,
                        f"{addon_name} add-on should include {field_name} in options so it is visible by default in Home Assistant",
                    )
                for field_name, schema_line in expected_schema.items():
                    self.assertIn(
                        schema_line,
                        config_text,
                        f"{addon_name} add-on should treat {field_name} as part of the standard visible login path",
                    )


if __name__ == "__main__":
    unittest.main()
