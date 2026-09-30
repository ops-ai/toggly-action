"""Unit tests for toggly_action.py. No network I/O."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import toggly_action  # noqa: E402


class ResolveRidTests(unittest.TestCase):
    def test_linux_x64(self):
        rid = toggly_action.resolve_rid("Linux", "x86_64")
        self.assertEqual(rid.asset, "toggly-cli-linux-x64.tar.gz")
        self.assertEqual(rid.binary_name, "toggly-cli")
        self.assertEqual(rid.rid, "linux-x64")

    def test_linux_arm64_aarch64(self):
        rid = toggly_action.resolve_rid("Linux", "aarch64")
        self.assertEqual(rid.asset, "toggly-cli-linux-arm64.tar.gz")
        self.assertEqual(rid.rid, "linux-arm64")

    def test_linux_arm64_arm64(self):
        rid = toggly_action.resolve_rid("Linux", "arm64")
        self.assertEqual(rid.asset, "toggly-cli-linux-arm64.tar.gz")

    def test_macos_arm64(self):
        rid = toggly_action.resolve_rid("Darwin", "arm64")
        self.assertEqual(rid.asset, "toggly-cli-macos-arm64.tar.gz")
        self.assertEqual(rid.binary_name, "toggly-cli")
        self.assertEqual(rid.rid, "macos-arm64")

    def test_macos_x64(self):
        rid = toggly_action.resolve_rid("Darwin", "x86_64")
        self.assertEqual(rid.asset, "toggly-cli-macos-x64.tar.gz")
        self.assertEqual(rid.rid, "macos-x64")

    def test_windows_amd64(self):
        rid = toggly_action.resolve_rid("Windows", "AMD64")
        self.assertEqual(rid.asset, "toggly-cli-windows-x64.zip")
        self.assertEqual(rid.binary_name, "toggly-cli.exe")
        self.assertEqual(rid.rid, "windows-x64")

    def test_windows_x86_64(self):
        rid = toggly_action.resolve_rid("Windows", "x86_64")
        self.assertEqual(rid.asset, "toggly-cli-windows-x64.zip")

    def test_unknown_rid(self):
        with self.assertRaises(toggly_action.TogglyActionError) as ctx:
            toggly_action.resolve_rid("FreeBSD", "x86_64")
        self.assertIn("FreeBSD", str(ctx.exception))
        self.assertIn("x86_64", str(ctx.exception))


class ChecksumTests(unittest.TestCase):
    def test_match_passes(self):
        data = b"hello-toggly"
        digest = hashlib.sha256(data).hexdigest()
        sums = f"{digest}  toggly-cli-linux-x64.tar.gz\n"
        toggly_action.verify_checksum(data, "toggly-cli-linux-x64.tar.gz", sums)

    def test_mismatch_fails(self):
        data = b"hello-toggly"
        bad = "0" * 64
        sums = f"{bad}  toggly-cli-linux-x64.tar.gz\n"
        with self.assertRaises(toggly_action.TogglyActionError):
            toggly_action.verify_checksum(data, "toggly-cli-linux-x64.tar.gz", sums)

    def test_missing_filename_fails(self):
        data = b"hello-toggly"
        digest = hashlib.sha256(data).hexdigest()
        sums = f"{digest}  other-file.tar.gz\n"
        with self.assertRaises(toggly_action.TogglyActionError):
            toggly_action.verify_checksum(data, "toggly-cli-linux-x64.tar.gz", sums)


class SplitArgsTests(unittest.TestCase):
    def test_quoted_string_stays_one_element(self):
        args = toggly_action.split_args('--notes "hello world"')
        self.assertEqual(args, ["--notes", "hello world"])

    def test_empty_args_rejected(self):
        with self.assertRaises(toggly_action.TogglyActionError):
            toggly_action.split_args("")

    def test_whitespace_only_rejected(self):
        with self.assertRaises(toggly_action.TogglyActionError):
            toggly_action.split_args("   ")


class VersionTests(unittest.TestCase):
    def test_semver_accepted(self):
        self.assertEqual(toggly_action.validate_version("0.2.1"), "0.2.1")

    def test_reject_shell_injection(self):
        with self.assertRaises(toggly_action.TogglyActionError):
            toggly_action.validate_version("0.2.1;rm")

    def test_reject_path_traversal(self):
        with self.assertRaises(toggly_action.TogglyActionError):
            toggly_action.validate_version("../0.2.1")

    def test_reject_empty(self):
        with self.assertRaises(toggly_action.TogglyActionError):
            toggly_action.validate_version("")

    def test_reject_latest(self):
        with self.assertRaises(toggly_action.TogglyActionError):
            toggly_action.validate_version("latest")


class SecretLoggingTests(unittest.TestCase):
    def test_run_does_not_print_secret_env(self):
        """run must not write client secret (or args) to stdout/stderr."""
        fake_bin = Path(tempfile.mkdtemp()) / "toggly-cli"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)

        env = {
            "TOGGLY_ARGS": "associate-build --help",
            "TOGGLY_BIN": str(fake_bin),
            "TOGGLY_CLIENT_ID": "client-id-value",
            "TOGGLY_CLIENT_SECRET": "super-secret-value-xyz",
            "PATH": os.environ.get("PATH", ""),
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
                with mock.patch("subprocess.call", return_value=0) as call:
                    code = toggly_action.cmd_run()
        self.assertEqual(code, 0)
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("super-secret-value-xyz", combined)
        self.assertNotIn("client-id-value", combined)
        self.assertNotIn("associate-build --help", combined)
        call.assert_called_once()
        argv = call.call_args[0][0]
        self.assertEqual(argv[0], str(fake_bin))
        self.assertEqual(argv[1:], ["associate-build", "--help"])


class InstallUsesFetcherTests(unittest.TestCase):
    def test_install_uses_injected_fetcher_no_network(self):
        version = "0.2.1"
        asset = "toggly-cli-linux-x64.tar.gz"
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="toggly-cli")
            payload = b"#!/bin/sh\necho ok\n"
            info.size = len(payload)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(payload))
        archive_bytes = buf.getvalue()
        digest = hashlib.sha256(archive_bytes).hexdigest()
        sums_text = f"{digest}  {asset}\n".encode()

        fetched = {}

        def fake_fetch(url: str) -> bytes:
            fetched[url] = True
            if url.endswith("SHA256SUMS"):
                return sums_text
            if url.endswith(asset):
                return archive_bytes
            raise AssertionError(f"unexpected url {url}")

        with tempfile.TemporaryDirectory() as tmp:
            github_path = Path(tmp) / "path.txt"
            env = {
                "TOGGLY_CLI_VERSION": version,
                "TOGGLY_INSTALL_DIR": str(Path(tmp) / "install"),
                "GITHUB_PATH": str(github_path),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(toggly_action, "platform_system", return_value="Linux"):
                    with mock.patch.object(toggly_action, "platform_machine", return_value="x86_64"):
                        with mock.patch.object(toggly_action, "fetch_url", fake_fetch):
                            code = toggly_action.cmd_install()
            self.assertEqual(code, 0)
            bin_path = Path(tmp) / "install" / "linux-x64" / "toggly-cli"
            self.assertTrue(bin_path.is_file())
            self.assertIn(str(bin_path.parent), github_path.read_text())
            self.assertTrue(any("SHA256SUMS" in u for u in fetched))
            self.assertTrue(any(asset in u for u in fetched))


if __name__ == "__main__":
    unittest.main()
