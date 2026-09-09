import contextlib
import getpass
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

import configure_local as cli
from astra_web import local_setup as setup


PLACEHOLDER = "sk-placeholder-for-tests-not-a-real-api-key"


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.addCleanup(self.folder.cleanup)

    @staticmethod
    def transport(status=200, body=None):
        return httpx.MockTransport(lambda request: httpx.Response(
            status, json=body if body is not None else {"id": "gpt-6-astra"}))

    def write_config(self, codex_bin="reviewed-codex.exe"):
        var = self.root / "var"
        var.mkdir(parents=True, exist_ok=True)
        (var / "local-config.json").write_text(json.dumps(
            {"version": 1, "player": "codex", "codex_bin": codex_bin}), encoding="utf-8")

    def test_validation_uses_fixed_endpoint_no_proxy_no_redirect_and_timeout(self):
        requests = []

        def handle(request):
            requests.append(request)
            self.assertEqual(str(request.url), setup.MODEL_URL)
            self.assertEqual(request.headers["Authorization"], "Bearer " + PLACEHOLDER)
            return httpx.Response(200, json={"id": setup.MODEL_ID})

        original_client = httpx.Client
        with patch.object(setup.httpx, "Client", wraps=original_client) as factory:
            result = setup.validate_api_key(PLACEHOLDER, transport=httpx.MockTransport(handle))
        self.assertEqual(result, "validated")
        self.assertEqual(len(requests), 1)
        self.assertEqual(factory.call_args.kwargs["timeout"], 25)
        self.assertIs(factory.call_args.kwargs["trust_env"], False)
        self.assertIs(factory.call_args.kwargs["follow_redirects"], False)

    def test_validation_returns_only_safe_classifications(self):
        cases = {401: "invalid_key", 403: "access_denied", 404: "model_unavailable",
                 429: "rate_limited", 500: "service_unavailable", 503: "service_unavailable", 418: "unexpected_response"}
        for status, expected in cases.items():
            with self.subTest(status=status):
                result = setup.validate_api_key(PLACEHOLDER, transport=self.transport(status, {"error": {"message": PLACEHOLDER}}))
                self.assertEqual(result, expected)
                self.assertNotIn(PLACEHOLDER, setup.MESSAGES[result])
        self.assertEqual(setup.validate_api_key(PLACEHOLDER, transport=self.transport(200, {"id": "another-model"})), "unexpected_response")
        self.assertEqual(setup.validate_api_key(PLACEHOLDER, transport=self.transport(200, [PLACEHOLDER])), "unexpected_response")

        def timeout(request):
            raise httpx.ReadTimeout(PLACEHOLDER)

        self.assertEqual(setup.validate_api_key(PLACEHOLDER, transport=httpx.MockTransport(timeout)), "connection_failed")

    def test_redirect_never_receives_credential_and_invalid_input_does_not_send(self):
        requests = []

        def redirect(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "https://untrusted.invalid/"})

        result = setup.validate_api_key(PLACEHOLDER, transport=httpx.MockTransport(redirect))
        self.assertEqual(result, "unexpected_response")
        self.assertEqual(len(requests), 1)
        for bad in ("", "short", "invalid\nheader-key"):
            self.assertEqual(setup.validate_api_key(bad, transport=httpx.MockTransport(redirect)), "invalid_key")
        self.assertEqual(len(requests), 1)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI round trip")
    def test_current_user_dpapi_round_trip_and_corruption_rejection(self):
        plaintext = PLACEHOLDER.encode("utf-8")
        encrypted = setup._dpapi(plaintext)
        self.assertNotEqual(encrypted, plaintext)
        self.assertNotIn(plaintext, encrypted)
        self.assertEqual(setup._dpapi(encrypted, decrypt=True), plaintext)
        with self.assertRaises(setup.LocalSetupError) as raised:
            setup._dpapi(b"invalid DPAPI blob", decrypt=True)
        self.assertEqual(raised.exception.code, "credential_unreadable")

    @unittest.skipUnless(os.name == "nt", "Windows encrypted persistence")
    def test_success_stores_ciphertext_and_failure_preserves_existing_files(self):
        binary = self.root / "reviewed-codex.exe"
        binary.write_bytes(b"test fixture; never executed")
        self.assertEqual(setup.configure_local(self.root, PLACEHOLDER, str(binary), transport=self.transport()), "saved")
        config_path = self.root / "var" / "local-config.json"
        key_path = self.root / "var" / "secrets" / "openai-key.dpapi"
        before = {path: path.read_bytes() for path in (config_path, key_path)}
        self.assertEqual(set(before), {config_path, key_path})
        for content in before.values():
            self.assertNotIn(PLACEHOLDER.encode(), content)
        config = json.loads(before[config_path])
        self.assertEqual(config, {"version": 1, "player": "codex", "codex_bin": str(binary.resolve())})
        status = setup.configure_local(self.root, "sk-another-test-placeholder", str(binary), transport=self.transport(401))
        self.assertEqual(status, "invalid_key")
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        # Replacing the Python mapping avoids inspecting/copying any real host key.
        with patch.object(setup.os, "environ", {}):
            setup.load_local_environment(self.root)
            self.assertEqual(setup.os.environ["OPENAI_API_KEY"], PLACEHOLDER)
            self.assertEqual(setup.os.environ["ASTRA_CODEX_BIN"], str(binary.resolve()))
            self.assertEqual(setup.os.environ["ASTRA_PLAYER"], "codex")
            self.assertNotIn("CODEX_HOME", setup.os.environ)

    def test_environment_overrides_skip_decryption_even_on_nonwindows(self):
        self.write_config()
        explicit = {"OPENAI_API_KEY": "environment-placeholder-value", "ASTRA_CODEX_BIN": "explicit-codex",
                    "ASTRA_PLAYER": "disabled", "CODEX_HOME": "operator-chosen-home"}
        with patch.object(setup.os, "environ", explicit.copy()), patch.object(setup, "_is_windows", return_value=False), patch.object(setup, "_dpapi", side_effect=AssertionError("Do not decrypt")):
            setup.load_local_environment(self.root)
            self.assertEqual(setup.os.environ, explicit)

    def test_nonwindows_requires_environment_without_reading_ciphertext(self):
        self.write_config()
        with patch.object(setup.os, "environ", {}), patch.object(setup, "_is_windows", return_value=False):
            with self.assertRaises(setup.LocalSetupError) as raised:
                setup.load_local_environment(self.root)
            self.assertEqual(raised.exception.code, "windows_only")
            self.assertIn("OPENAI_API_KEY", str(raised.exception))
            self.assertEqual(setup.os.environ, {})
            self.assertEqual(setup.configure_local(self.root, PLACEHOLDER, transport=self.transport()), "windows_only")

    def test_absent_configuration_is_optional_and_invalid_configuration_is_controlled(self):
        with patch.object(setup.os, "environ", {}):
            setup.load_local_environment(self.root)
            self.assertEqual(setup.os.environ, {})
        self.write_config()
        (self.root / "var" / "local-config.json").write_text(PLACEHOLDER, encoding="utf-8")
        with self.assertRaises(setup.LocalSetupError) as raised:
            setup.load_local_environment(self.root)
        self.assertEqual(raised.exception.code, "configuration_invalid")
        self.assertNotIn(PLACEHOLDER, str(raised.exception))

    def test_cli_hides_input_and_outputs_no_exception_or_key(self):
        captured = io.StringIO()
        with patch.object(cli, "_is_windows", return_value=True), patch.object(cli.getpass, "getpass", return_value=PLACEHOLDER), patch.object(cli, "configure_local", side_effect=RuntimeError(PLACEHOLDER)), contextlib.redirect_stdout(captured):
            result = cli.main(["--codex-bin", "reviewed-codex.exe"])
        self.assertEqual(result, 1)
        self.assertEqual(captured.getvalue().strip(), setup.MESSAGES["save_failed"])
        self.assertNotIn(PLACEHOLDER, captured.getvalue())
        with patch.object(cli, "_is_windows", return_value=True), patch.object(cli.getpass, "getpass", side_effect=getpass.GetPassWarning()), patch.object(cli, "configure_local") as configure, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 1)
            configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
