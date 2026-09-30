#!/usr/bin/env python3
"""Install a pinned toggly-cli release and run caller-supplied arguments.

Never logs TOGGLY_CLIENT_ID, TOGGLY_CLIENT_SECRET, or TOGGLY_ARGS.
Never interpolates args into a shell.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
RELEASE_BASE = (
    "https://github.com/ops-ai/Toggly.FeatureManagement/releases/download"
)
FETCH_TIMEOUT_SECONDS = 60


class TogglyActionError(Exception):
    """User-facing failure (invalid input, checksum, unsupported RID)."""


@dataclass(frozen=True)
class RidInfo:
    rid: str
    asset: str
    binary_name: str


def platform_system() -> str:
    return platform.system()


def platform_machine() -> str:
    return platform.machine()


def validate_version(version: str) -> str:
    if not version or not VERSION_RE.fullmatch(version):
        raise TogglyActionError(
            f"version must be MAJOR.MINOR.PATCH (got {version!r})"
        )
    return version


def resolve_rid(system: str, machine: str) -> RidInfo:
    sys_norm = (system or "").strip()
    mach_norm = (machine or "").strip()
    mach_lower = mach_norm.lower()

    if sys_norm == "Linux":
        if mach_lower in ("x86_64", "amd64"):
            return RidInfo("linux-x64", "toggly-cli-linux-x64.tar.gz", "toggly-cli")
        if mach_lower in ("aarch64", "arm64"):
            return RidInfo(
                "linux-arm64", "toggly-cli-linux-arm64.tar.gz", "toggly-cli"
            )
    elif sys_norm == "Darwin":
        if mach_lower in ("x86_64", "amd64"):
            return RidInfo("macos-x64", "toggly-cli-macos-x64.tar.gz", "toggly-cli")
        if mach_lower == "arm64":
            return RidInfo(
                "macos-arm64", "toggly-cli-macos-arm64.tar.gz", "toggly-cli"
            )
    elif sys_norm.lower().startswith("windows") or sys_norm == "Windows":
        if mach_lower in ("amd64", "x86_64", "x64"):
            return RidInfo(
                "windows-x64", "toggly-cli-windows-x64.zip", "toggly-cli.exe"
            )

    raise TogglyActionError(
        f"unsupported runner RID: system={sys_norm!r} machine={mach_norm!r}"
    )


def verify_checksum(data: bytes, filename: str, sums_text: str) -> None:
    expected = None
    for line in sums_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Format from CLI release workflow: "<hex>  <basename>" (two spaces)
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        if name.strip() == filename:
            expected = digest.lower()
            break
    if expected is None:
        raise TogglyActionError(f"SHA256SUMS has no entry for {filename}")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise TogglyActionError(
            f"checksum mismatch for {filename}: expected {expected}, got {actual}"
        )


def split_args(args: str) -> list[str]:
    if args is None or not str(args).strip():
        raise TogglyActionError("TOGGLY_ARGS is required and must not be empty")
    return shlex.split(str(args), posix=True)


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "toggly-action"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        raise TogglyActionError(f"download failed: {url}") from exc


def _extract_archive(archive_path: Path, dest: Path, asset: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if asset.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest)
    else:
        with tarfile.open(archive_path, "r:*") as tf:
            # Python 3.12+ supports filter=; older runtimes ignore via try
            try:
                tf.extractall(dest, filter="data")
            except TypeError:
                tf.extractall(dest)


def _find_binary(dest: Path, binary_name: str) -> Path:
    direct = dest / binary_name
    if direct.is_file():
        return direct
    matches = list(dest.rglob(binary_name))
    if not matches:
        raise TogglyActionError(f"extracted archive missing {binary_name}")
    return matches[0]


def _append_github_path(directory: Path) -> None:
    github_path = os.environ.get("GITHUB_PATH")
    if not github_path:
        return
    with open(github_path, "a", encoding="utf-8") as fh:
        fh.write(str(directory) + "\n")


def cmd_install(fetch: Callable[[str], bytes] | None = None) -> int:
    fetch = fetch or fetch_url
    version = validate_version(os.environ.get("TOGGLY_CLI_VERSION", ""))
    rid = resolve_rid(platform_system(), platform_machine())

    install_root = Path(
        os.environ.get(
            "TOGGLY_INSTALL_DIR",
            str(Path.home() / ".cache" / "toggly-cli" / version),
        )
    )
    install_dir = install_root / rid.rid
    binary_path = install_dir / rid.binary_name

    if binary_path.is_file() and os.access(binary_path, os.X_OK):
        _append_github_path(binary_path.parent)
        return 0

    tag = f"cli-v{version}"
    base = f"{RELEASE_BASE}/{tag}"
    sums_url = f"{base}/SHA256SUMS"
    asset_url = f"{base}/{rid.asset}"

    sums_bytes = fetch(sums_url)
    asset_bytes = fetch(asset_url)
    verify_checksum(asset_bytes, rid.asset, sums_bytes.decode("utf-8"))

    install_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / rid.asset
        archive_path.write_bytes(asset_bytes)
        extract_dir = Path(tmp) / "extract"
        _extract_archive(archive_path, extract_dir, rid.asset)
        found = _find_binary(extract_dir, rid.binary_name)
        target = install_dir / rid.binary_name
        if target.exists():
            target.unlink()
        shutil.copy2(found, target)
        target.chmod(target.stat().st_mode | 0o111)

    _append_github_path(install_dir)
    return 0


def _resolve_binary() -> str:
    explicit = os.environ.get("TOGGLY_BIN")
    if explicit:
        return explicit
    for name in ("toggly-cli", "toggly-cli.exe", "toggly"):
        found = shutil.which(name)
        if found:
            return found
    raise TogglyActionError("toggly-cli not found on PATH; run install first")


def cmd_run() -> int:
    args = split_args(os.environ.get("TOGGLY_ARGS", ""))
    binary = _resolve_binary()
    return subprocess.call([binary, *args])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("install", "run"):
        # Do not print env or secrets; keep usage minimal.
        sys.stderr.write("usage: toggly_action.py install|run\n")
        return 1
    try:
        if argv[0] == "install":
            return cmd_install()
        return cmd_run()
    except TogglyActionError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
