import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = ROOT / "home_assistant"


class TestHomeAssistantAddonPackaging(unittest.TestCase):
    def test_runtime_overlay_build_matches_checked_in_artifacts(self):
        result = subprocess.run(
            [str(ROOT / "scripts" / "build.sh"), "--check"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("home_assistant: matches canonical app + overlay", result.stdout)
        self.assertIn("ha_live_addon: matches canonical app + overlay", result.stdout)

    def test_runtime_overlays_only_override_runtime_specific_app_files(self):
        allowed_app_overlays = {
            Path(".env"),
            Path("build.env"),
        }

        for overlay_name in ("home_assistant", "ha_live_addon"):
            app_overlay = ROOT / "runtime_overlays" / overlay_name / "app"
            overlay_files = {
                path.relative_to(app_overlay)
                for path in app_overlay.rglob("*")
                if path.is_file()
            }
            with self.subTest(overlay=overlay_name):
                self.assertEqual(
                    overlay_files,
                    allowed_app_overlays,
                    "runtime overlays should not carry independent Python, template, or static source copies",
                )

    def test_runtime_overlays_do_not_override_canonical_whep_proxy(self):
        for overlay_name in ("home_assistant", "ha_live_addon"):
            whep_overlay = ROOT / "runtime_overlays" / overlay_name / "whep_proxy"
            overlay_files = (
                {
                    path.relative_to(whep_overlay)
                    for path in whep_overlay.rglob("*")
                    if path.is_file()
                }
                if whep_overlay.exists()
                else set()
            )
            with self.subTest(overlay=overlay_name):
                self.assertEqual(
                    overlay_files,
                    set(),
                    "WHEP proxy should be canonical at repo-root whep_proxy/ so the master go test command exercises the same code that HA packages",
                )

    def test_release_hygiene_excludes_local_agent_and_secret_artifacts(self):
        required_patterns = {
            "tmp/",
            ".build/",
            ".pi-lens/",
            "data/",
            "AGENTS.md",
            "lessons.md",
            ".goal-master.md",
            "**/options_payload*.json",
            "**/*options-payload*.json",
            "scripts/.ha_ssh.env",
        }
        ignore_files = [
            ROOT / ".gitignore",
            ROOT / ".dockerignore",
            ROOT / "runtime_overlays" / "home_assistant" / ".dockerignore",
            ROOT / "runtime_overlays" / "ha_live_addon" / ".dockerignore",
        ]

        for ignore_file in ignore_files:
            patterns = set(ignore_file.read_text().splitlines())
            with self.subTest(ignore_file=str(ignore_file.relative_to(ROOT))):
                self.assertTrue(
                    required_patterns.issubset(patterns),
                    "release packaging should keep local notes, scratch files, option payloads, and SSH env files out of public artifacts",
                )

    def test_packaged_env_files_do_not_ship_private_sdk_key(self):
        allowed_sdk_values = {
            "",
            "SDK_KEY_REPLACED_ROTATE_YOUR_KEY",
        }
        env_files = [
            ROOT / "app" / ".env",
            ROOT / "app" / "build.env",
            ROOT / "home_assistant" / "app" / ".env",
            ROOT / "home_assistant" / "app" / "build.env",
            ROOT / ".ha_live_addon" / "app" / ".env",
            ROOT / ".ha_live_addon" / "app" / "build.env",
            ROOT / "runtime_overlays" / "home_assistant" / "app" / ".env",
            ROOT / "runtime_overlays" / "home_assistant" / "app" / "build.env",
            ROOT / "runtime_overlays" / "ha_live_addon" / "app" / ".env",
            ROOT / "runtime_overlays" / "ha_live_addon" / "app" / "build.env",
        ]

        for env_file in env_files:
            env_text = env_file.read_text()
            sdk_match = re.search(r"^SDK_KEY=(.*)$", env_text, re.MULTILINE)
            with self.subTest(env_file=str(env_file.relative_to(ROOT))):
                if sdk_match is None:
                    continue
                self.assertIn(
                    sdk_match.group(1).strip(),
                    allowed_sdk_values,
                    f"{env_file.relative_to(ROOT)} should use the public SDK_KEY placeholder for release packaging",
                )

    def test_master_whep_proxy_go_test_command_runs_from_repo_root(self):
        result = subprocess.run(
            ["go", "test", "./whep_proxy/...", "-v", "-count=1"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PASS", result.stdout)

    def test_prod_patch_deploy_uses_canonical_whep_proxy(self):
        deploy_script = (ROOT / "scripts" / "deploy_ha_local_addon.sh").read_text()

        self.assertIn('copy_file "whep_proxy/main.go"', deploy_script)
        self.assertNotIn('copy_file ".ha_live_addon/whep_proxy/main.go"', deploy_script)

    def test_all_runtime_entrypoints_source_go2rtc_helper(self):
        run_files = [
            ROOT / "app" / "run",
            ROOT / "home_assistant" / "app" / "run",
            ROOT / ".ha_live_addon" / "app" / "run",
        ]
        helper_files = [
            ROOT / "app" / "go2rtc_sidecar.sh",
            ROOT / "home_assistant" / "app" / "go2rtc_sidecar.sh",
            ROOT / ".ha_live_addon" / "app" / "go2rtc_sidecar.sh",
        ]

        for helper_path in helper_files:
            with self.subTest(helper=str(helper_path.relative_to(ROOT))):
                self.assertTrue(helper_path.exists())

        for run_path in run_files:
            run_text = run_path.read_text()
            with self.subTest(run=str(run_path.relative_to(ROOT))):
                self.assertIn(". /app/go2rtc_sidecar.sh", run_text)
                self.assertIn("start_go2rtc_sidecar", run_text)

    def test_all_runtime_entrypoints_export_app_pythonpath(self):
        run_files = [
            ROOT / "app" / "run",
            ROOT / "home_assistant" / "app" / "run",
            ROOT / ".ha_live_addon" / "app" / "run",
        ]

        expected_line = 'export PYTHONPATH="/app${PYTHONPATH:+:$PYTHONPATH}"'

        for run_path in run_files:
            run_text = run_path.read_text()
            with self.subTest(run=str(run_path.relative_to(ROOT))):
                self.assertIn(
                    expected_line,
                    run_text,
                    "runtime entrypoints should export /app on PYTHONPATH so flask can import wyzebridge from the add-on workdir",
                )

    def test_all_runtime_entrypoints_reuse_existing_whep_listener(self):
        run_files = [
            ROOT / "app" / "run",
            ROOT / "home_assistant" / "app" / "run",
            ROOT / ".ha_live_addon" / "app" / "run",
        ]

        for run_path in run_files:
            run_text = run_path.read_text()
            with self.subTest(run=str(run_path.relative_to(ROOT))):
                self.assertIn('whep_port="${WHEP_PROXY_PORT:-8080}"', run_text)
                self.assertIn("whep_port_is_open() {", run_text)
                self.assertIn('sock.connect(("127.0.0.1", port))', run_text)
                self.assertNotIn("/status/__startup_probe__", run_text)
                self.assertIn("not starting a duplicate", run_text)

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

    def test_prod_addon_exposes_native_go2rtc_rtsp_port(self):
        config_text = (ADDON_DIR / "config.yml").read_text()
        self.assertIn("  19554/tcp: 19554", config_text)
        self.assertIn("  19554/tcp: go2rtc RTSP rtsp://localhost:19554/camera-name", config_text)

    def test_prod_addon_exposes_go2rtc_lan_ip_overrides(self):
        config_text = (ADDON_DIR / "config.yml").read_text()
        translation_text = (ADDON_DIR / "translations" / "en.yml").read_text()

        self.assertIn('  GO2RTC_LAN_IP_OVERRIDES: ""', config_text)
        self.assertIn("  GO2RTC_LAN_IP_OVERRIDES: str?", config_text)
        self.assertIn("GO2RTC_LAN_IP_OVERRIDES:", translation_text)

    def test_prod_addon_downloads_go2rtc_binary(self):
        dockerfile_text = (ADDON_DIR / "Dockerfile").read_text()
        self.assertIn("go2rtc_linux_${GO2RTC_ARCH}", dockerfile_text)
        self.assertIn("usr/local/bin/go2rtc", dockerfile_text)

    def test_go2rtc_sidecar_disables_default_webrtc_listener(self):
        helper_files = [
            ROOT / "app" / "go2rtc_sidecar.sh",
            ROOT / "home_assistant" / "app" / "go2rtc_sidecar.sh",
            ROOT / ".ha_live_addon" / "app" / "go2rtc_sidecar.sh",
        ]

        expected_lines = [
            '        "webrtc:",',
            "        '  listen: \"127.0.0.1:0\"',",
        ]

        for helper_path in helper_files:
            helper_text = helper_path.read_text()
            with self.subTest(helper=str(helper_path.relative_to(ROOT))):
                for expected in expected_lines:
                    self.assertIn(
                        expected,
                        helper_text,
                        "go2rtc sidecar config should explicitly override the default 8555 WebRTC listener",
                    )

    def test_go2rtc_sidecar_normalizes_preserved_config_listeners(self):
        helper_files = [
            ROOT / "app" / "go2rtc_sidecar.sh",
            ROOT / "home_assistant" / "app" / "go2rtc_sidecar.sh",
            ROOT / ".ha_live_addon" / "app" / "go2rtc_sidecar.sh",
        ]

        expected_lines = [
            "normalize_go2rtc_config() {",
            'managed = {"api", "rtsp", "webrtc"}',
            "normalize_go2rtc_config",
        ]

        for helper_path in helper_files:
            helper_text = helper_path.read_text()
            with self.subTest(helper=str(helper_path.relative_to(ROOT))):
                for expected in expected_lines:
                    self.assertIn(
                        expected,
                        helper_text,
                        "go2rtc sidecar should rewrite preserved configs so old listener blocks cannot keep host port 8555",
                    )

    def test_go2rtc_sidecar_refreshes_preserved_wyze_aliases(self):
        helper_files = [
            ROOT / "app" / "go2rtc_sidecar.sh",
            ROOT / "home_assistant" / "app" / "go2rtc_sidecar.sh",
            ROOT / ".ha_live_addon" / "app" / "go2rtc_sidecar.sh",
        ]

        stale_return = '    if [ "${GO2RTC_HAS_PERSISTED_STREAMS}" = "1" ]; then\n        return\n    fi\n'

        for helper_path in helper_files:
            helper_text = helper_path.read_text()
            with self.subTest(helper=str(helper_path.relative_to(ROOT))):
                self.assertNotIn(
                    stale_return,
                    helper_text,
                    "go2rtc sidecar should not skip the /api/wyze refresh just because persisted aliases already exist",
                )
                self.assertIn(
                    "Camera list received, refreshing native Wyze aliases...",
                    helper_text,
                    "go2rtc sidecar should refresh preserved Wyze aliases after fetching the current helper URLs",
                )

    def test_go2rtc_sidecar_preloads_native_aliases_after_refresh(self):
        helper_files = [
            ROOT / "app" / "go2rtc_sidecar.sh",
            ROOT / "home_assistant" / "app" / "go2rtc_sidecar.sh",
            ROOT / ".ha_live_addon" / "app" / "go2rtc_sidecar.sh",
        ]

        expected_snippets = [
            "preload_go2rtc_aliases()",
            "curl -sf -X PUT \"${GO2RTC_API_BASE}/api/preload?src=${alias}\"",
            "Native preload readiness attempt ${attempt}/5",
            "sleep 60",
            "start_go2rtc_preload_refresh_loop",
        ]

        for helper_path in helper_files:
            helper_text = helper_path.read_text()
            with self.subTest(helper=str(helper_path.relative_to(ROOT))):
                for expected in expected_snippets:
                    self.assertIn(
                        expected,
                        helper_text,
                        "go2rtc sidecar should aggressively warm native aliases and keep refreshing preload state",
                    )

    def test_go2rtc_sidecar_can_skip_helper_disabled_or_unsupported_feeds(self):
        helper_files = [
            ROOT / "app" / "go2rtc_sidecar.sh",
            ROOT / "home_assistant" / "app" / "go2rtc_sidecar.sh",
            ROOT / ".ha_live_addon" / "app" / "go2rtc_sidecar.sh",
        ]

        expected_snippets = [
            'WB_APP_API_BASE=""',
            'BRIDGE_API_TOKEN=$(WYZE_EMAIL="${WYZE_EMAIL}" python3 - <<\'PY\'',
            'candidate="http://127.0.0.1:${WB_APP_PORT}"',
            'curl -sf -H "api: ${BRIDGE_API_TOKEN}" "${candidate}/api"',
            'payload = json.loads(os.environ.get("BRIDGE_API_PAYLOAD", ""))',
            'Bridge catalog ready after ${retry}x2s',
            'WB_APP_API_BASE="${candidate}"',
            "keeping stale alias fallback",
            'def bridge_published_entries(cam_uri: str):',
            'def bridge_camera_state(cam_uri: str) -> dict:',
            'state["published"] = bool(enabled_entries)',
            'state["hd"] = any(',
            'state["sd"] = any(',
            'fetch_json(f"{base_url}/api/{cam_path}/stream-config", api_token=api_token)',
            'bridge_catalog_empty = isinstance(catalog, dict) and not catalog',
            'if bridge_catalog_empty:',
            'published = None',
            'if published is None or feed.get("path") == "native":',
            'if "enabled" not in state:',
            'state["enabled"] = bool(state.get("hd") or state.get("sd"))',
            'for key, value in bridge_state.items():',
            'cam.setdefault(key, value)',
            'published = helper_flag(cam, "published")',
            'if published is False and helper_flag(cam, "hd") is False and helper_flag(cam, "sd") is False:',
            'Skipping camera not published by bridge',
            'enabled = helper_flag(cam, "enabled")',
            'if enabled is False:',
            'hd_supported = helper_flag(cam, "hd_supported")',
            'sd_supported = helper_flag(cam, "sd_supported")',
            'if hd_supported is None and model == "HL_BC":',
            'aliases.append((f"{uri}-sd", "sd"))',
            'Skipping camera with no enabled native feeds',
        ]

        for helper_path in helper_files:
            helper_text = helper_path.read_text()
            with self.subTest(helper=str(helper_path.relative_to(ROOT))):
                for expected in expected_snippets:
                    self.assertIn(
                        expected,
                        helper_text,
                        "go2rtc sidecar should honor explicit helper feed flags and avoid fake native aliases for unsupported feeds",
                    )
                self.assertNotIn(
                    "api={api_token}",
                    helper_text,
                    "bridge API filtering should use the api header so keys are not logged in request URLs",
                )
                self.assertNotIn(
                    "api=${BRIDGE_API_TOKEN}",
                    helper_text,
                    "sidecar readiness checks should use the api header so keys are not logged in request URLs",
                )

    def test_public_go2rtc_sidecars_use_configured_lan_ip_overrides(self):
        helper_files = [
            ROOT / "app" / "go2rtc_sidecar.sh",
            ROOT / "home_assistant" / "app" / "go2rtc_sidecar.sh",
        ]

        for helper_path in helper_files:
            helper_text = helper_path.read_text()
            with self.subTest(helper=str(helper_path.relative_to(ROOT))):
                self.assertIn("GO2RTC_LAN_IP_OVERRIDES", helper_text)
                self.assertIn("GO2RTC_FORCE_LAN_IP_OVERRIDES", helper_text)
                self.assertIn('/data/options.json", encoding="utf-8"', helper_text)
                self.assertIn("def normalize_mac(value: str) -> str:", helper_text)
                self.assertIn("def camera_mac(cam: dict) -> str:", helper_text)
                self.assertIn("urllib.parse.parse_qs(parsed.query)", helper_text)
                self.assertNotIn("80482C31C9E7", helper_text)
                self.assertNotIn("192.168.1.177", helper_text)

    def test_go2rtc_sidecar_does_not_override_private_helper_hosts_by_default(self):
        helper_files = [
            ROOT / "app" / "go2rtc_sidecar.sh",
            ROOT / "home_assistant" / "app" / "go2rtc_sidecar.sh",
            ROOT / ".ha_live_addon" / "app" / "go2rtc_sidecar.sh",
        ]

        expected_snippets = [
            "def is_private_lan_host(host: str) -> bool:",
            'if is_private_lan_host(parsed.hostname or "") and not force_lan_ip_overrides():',
            "keeping helper LAN host",
            "GO2RTC_FORCE_LAN_IP_OVERRIDES",
        ]

        for helper_path in helper_files:
            helper_text = helper_path.read_text()
            with self.subTest(helper=str(helper_path.relative_to(ROOT))):
                for expected in expected_snippets:
                    self.assertIn(
                        expected,
                        helper_text,
                        "go2rtc sidecar should not let a stale override replace a current private helper IP unless explicitly forced",
                    )

    def test_root_dockerfiles_download_go2rtc_binary(self):
        dockerfiles = [
            ROOT / "docker" / "Dockerfile",
            ROOT / "docker" / "Dockerfile.multiarch",
            ROOT / "docker" / "Dockerfile.hwaccel",
        ]
        for dockerfile_path in dockerfiles:
            dockerfile_text = dockerfile_path.read_text()
            with self.subTest(dockerfile=str(dockerfile_path.relative_to(ROOT))):
                self.assertIn("usr/local/bin/go2rtc", dockerfile_text)
                self.assertIn("go2rtc_linux_", dockerfile_text)

    def test_runtime_dockerfiles_include_curl_for_go2rtc_refresh(self):
        dockerfiles = [
            ROOT / "home_assistant" / "Dockerfile",
            ROOT / "docker" / "Dockerfile",
            ROOT / "docker" / "Dockerfile.multiarch",
            ROOT / "docker" / "Dockerfile.hwaccel",
        ]

        for dockerfile_path in dockerfiles:
            dockerfile_text = dockerfile_path.read_text()
            with self.subTest(dockerfile=str(dockerfile_path.relative_to(ROOT))):
                self.assertRegex(
                    dockerfile_text,
                    r"apt-get install -y --no-install-recommends [^\n]*\bcurl\b",
                    "runtime image should include curl because go2rtc_sidecar.sh refreshes preserved aliases via curl at startup",
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
        self.assertRegex(dev_version.group(1).strip(), r"^4\.\d+\.\d+-dev$")

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
            "SD_ONLY": "  SD_ONLY: false",
        }
        expected_schema = {
            "WYZE_EMAIL": "  WYZE_EMAIL: email",
            "WYZE_PASSWORD": "  WYZE_PASSWORD: password",
            "API_ID": "  API_ID: match([a-fA-F0-9-]{36})",
            "API_KEY": "  API_KEY: match([a-zA-Z0-9]{60})",
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

    def test_addon_schema_prioritizes_common_setup_fields(self):
        addon_configs = {
            "prod": (ADDON_DIR / "config.yml").read_text(),
            "dev": (ROOT / ".ha_live_addon" / "config.yml").read_text(),
        }

        ordered_fields = [
            "  WYZE_EMAIL: email",
            "  WYZE_PASSWORD: password",
            "  API_ID: match([a-fA-F0-9-]{36})",
            "  API_KEY: match([a-zA-Z0-9]{60})",
            "  TOTP_KEY: str?",
            "  ON_DEMAND: bool?",
            "  SD_ONLY: bool?",
            "  ENABLE_AUDIO: bool?",
            "  SUBSTREAM: bool?",
            "  NET_MODE: list(LAN|P2P|ANY)?",
            "  FORCE_FPS: int?",
            "  CAM_OPTIONS:",
        ]

        for addon_name, config_text in addon_configs.items():
            with self.subTest(addon=addon_name):
                schema_text = config_text.split("schema:\n", 1)[1]
                indexes = [schema_text.index(field) for field in ordered_fields]
                self.assertEqual(indexes, sorted(indexes))

    def test_camera_options_expose_granular_feed_controls(self):
        addon_configs = {
            "prod": (ADDON_DIR / "config.yml").read_text(),
            "dev": (ROOT / ".ha_live_addon" / "config.yml").read_text(),
        }

        for addon_name, config_text in addon_configs.items():
            with self.subTest(addon=addon_name):
                self.assertIn("      STREAM: list(main|both|sub)?", config_text)
                self.assertIn("      HD: bool?", config_text)
                self.assertIn("      SD: bool?", config_text)
                self.assertNotIn("      HD_KBPS: int?", config_text)
                self.assertNotIn("      SD_KBPS: int?", config_text)
                self.assertNotIn("      QUALITY: str?", config_text)
                self.assertNotIn("      SUB_QUALITY: str?", config_text)

    def test_camera_options_have_nested_translations(self):
        addon_translations = {
            "prod": (ADDON_DIR / "translations" / "en.yml").read_text(),
            "dev": (ROOT / ".ha_live_addon" / "translations" / "en.yml").read_text(),
        }

        expected_snippets = [
            "  SD_ONLY:\n",
            "    name: SD-only mode\n",
            "  CAM_OPTIONS:\n",
            "    fields:\n",
            "      CAM_NAME:\n",
            "        name: Camera name\n",
            "      HD:\n",
            "        name: Enable HD feed\n",
            "      STREAM:\n",
            "        name: Legacy stream mode\n",
        ]

        for addon_name, translation_text in addon_translations.items():
            with self.subTest(addon=addon_name):
                for snippet in expected_snippets:
                    self.assertIn(snippet, translation_text)

    def test_niche_power_user_fields_are_not_exposed_in_ha_form(self):
        addon_configs = {
            "prod": (ADDON_DIR / "config.yml").read_text(),
            "dev": (ROOT / ".ha_live_addon" / "config.yml").read_text(),
        }

        removed_schema_fields = [
            "  REFRESH_TOKEN: str?",
            "  ACCESS_TOKEN: str?",
            "  AUDIO_FILTER: str?",
            "  FFMPEG_FLAGS: str?",
            "  FFMPEG_CMD: str?",
            "  BOA_ENABLED: bool?",
            "  FORCE_V4_PARALLEL: bool?",
            "  MEDIAMTX:\n",
            "  WB_HLS_URL: url?",
            "  WB_RTMP_URL: url?",
            "  WB_RTSP_URL: url?",
            "  WB_WEBRTC_URL: url?",
            "  LATITUDE: float?",
            "  LONGITUDE: float?",
        ]

        for addon_name, config_text in addon_configs.items():
            with self.subTest(addon=addon_name):
                for field in removed_schema_fields:
                    self.assertNotIn(field, config_text)

    def test_ha_env_files_define_fixed_mediatx_ports(self):
        env_files = {
            "prod": ADDON_DIR / "app" / ".env",
            "dev": ROOT / ".ha_live_addon" / "app" / ".env",
        }

        expected_lines = {
            "prod": [
                "MTX_API=true",
                "MTX_RTSPADDRESS=:58554",
                "MTX_HLSADDRESS=:39888",
                "MTX_WEBRTCADDRESS=:58889",
                "MTX_APIADDRESS=:59997",
            ],
            "dev": [
                "WHEP_PROXY_PORT=18080",
                "KVS_CONFIG_PORT=55000",
                "MTX_API=true",
                "MTX_RTSPADDRESS=:28554",
                "MTX_RTPADDRESS=:28000",
                "MTX_RTCPADDRESS=:28001",
                "MTX_HLSADDRESS=:28888",
                "MTX_WEBRTCADDRESS=:28889",
                "MTX_APIADDRESS=:29997",
            ],
        }

        for addon_name, env_path in env_files.items():
            env_text = env_path.read_text()
            with self.subTest(addon=addon_name):
                for expected in expected_lines[addon_name]:
                    self.assertIn(expected, env_text)

    def test_prod_hidden_ha_env_is_explicitly_unignored(self):
        gitignore_text = (ROOT / ".gitignore").read_text()
        self.assertIn(
            "!home_assistant/app/.env",
            gitignore_text,
            "the production Home Assistant .env must be explicitly unignored so Supervisor GitHub builds receive the fixed MediaMTX port settings",
        )


if __name__ == "__main__":
    unittest.main()
