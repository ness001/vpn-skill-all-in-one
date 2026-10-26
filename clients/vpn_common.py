"""Small shared helpers; exceptions never include profile or subprocess output."""
from __future__ import annotations

import csv
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path.home() / ".cache" / "vpn-skill" / "runtime" / ".tools"
MAX_CONFIG_BYTES = 1024 * 1024


def default_profiles_file() -> Path:
    return Path(os.environ.get("VPN_PROFILES_FILE") or ROOT / "profiles" / "vpn-profiles.json").expanduser()


class ClientError(Exception):
    pass


class CleanupError(ClientError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_sha256(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ClientError("A complete 64-character SHA-256 digest is required.")
    return value.lower()


def limited_read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ClientError("Input file exceeds its size limit.")
    return data


def restrict_directory(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o700)
        return
    identity = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    rows = list(csv.reader(identity.stdout.strip().splitlines()))
    sid = rows[-1][-1] if rows else ""
    if not re.fullmatch(r"S-1-(?:\d+-)+\d+", sid):
        raise ClientError("Cannot determine the Windows user SID for private files.")
    # Replace the whole DACL: icacls /grant:r can leave explicit inherited-parent
    # entries for other users. Only this SID receives access; inheritance is off.
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    apply = advapi.SetFileSecurityW
    apply.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    apply.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    if not convert(f"D:P(A;OICI;FA;;;{sid})", 1, ctypes.byref(descriptor), None):
        raise ClientError("Cannot build the user-only Windows file ACL.")
    try:
        if not apply(str(path), 0x80000004, descriptor):
            raise ClientError("Cannot apply the user-only Windows file ACL.")
    finally:
        kernel.LocalFree(descriptor)


def cleanup_private_directory(directory, timeout: float = 5) -> None:
    # Windows browser/cache and antivirus handles may outlive process termination
    # briefly. Retry the same owned directory, never ignore a persistent lock.
    deadline = time.monotonic() + timeout
    while True:
        try:
            directory.cleanup()
            return
        except OSError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CleanupError("Temporary private files could not be removed because they are still locked. "
                                   "Cleanup did not complete.") from None
            time.sleep(min(0.1, remaining))


@contextmanager
def private_directory(parent: Path | None = None):
    directory = tempfile.TemporaryDirectory(prefix="vpn-client-", dir=parent)
    try:
        path = Path(directory.name)
        # Apply the ACL before writing any credential bytes.
        restrict_directory(path)
        yield path
    finally:
        cleanup_private_directory(directory)


def check_private_path(path: Path) -> None:
    # Check before resolve/open, including dangling links and Windows junctions.
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ClientError("Paths must not contain symbolic links or junctions.")
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise ClientError("Path parents must be directories.")


def private_export_path(output: Path, suffix: str, *, root: Path = ROOT) -> Path:
    path = output.expanduser().absolute()
    check_private_path(path)
    if path.suffix.lower() != suffix:
        raise ClientError("Output has an unsupported file extension.")
    if os.path.lexists(path):
        raise ClientError("Output already exists; choose a new filename.")
    path = path.resolve()
    if (path.is_relative_to(root.resolve())
            or any(os.path.lexists(parent / ".git") for parent in path.parents)
            or any((parent / "HEAD").is_file() and (parent / "objects").is_dir()
                   and (parent / "refs").is_dir() for parent in path.parents)):
        raise ClientError("Private output must be outside all Git repositories.")
    return path


def ensure_private_export_parent(path: Path) -> None:
    if not path.exists():
        path.mkdir(mode=0o700)
        restrict_directory(path)
        return
    if not path.is_dir() or path.is_symlink():
        raise ClientError("Export parent must be a dedicated private directory.")
    if os.name != "nt":
        if path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid():
            raise ClientError("Export parent must be owned by this user with mode 700.")
        return
    # Inspect only: never change permissions on an existing directory chosen by
    # the caller. A new dedicated parent is protected automatically above.
    script = (
        "$ErrorActionPreference='Stop'; "
        "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
        "$acl=[IO.Directory]::GetAccessControl($env:VPN_PRIVATE_EXPORT_PARENT); "
        "if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid) {exit 1}; "
        "$rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])); "
        "if ($rules.Count -eq 0) {exit 1}; "
        "foreach ($rule in $rules) { "
        "if ($rule.IdentityReference.Value -ne $sid) {exit 1} }; exit 0"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "VPN_PRIVATE_EXPORT_PARENT": str(path)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
    )
    if result.returncode:
        raise ClientError("Export parent is not user-only; choose a new dedicated directory outside Git.")


def private_write(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        if os.name != "nt":
            os.fchmod(stream.fileno(), stat.S_IRUSR | stat.S_IWUSR)
        stream.write(data)
