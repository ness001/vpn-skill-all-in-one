#!/usr/bin/env python3
"""Show official desktop installer links or explicitly download verified packages."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import uuid

from gui_profiles import export_gui_profiles
from vpn_common import ClientError, ROOT, default_profiles_file
from core_install import download, validate_download_url

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024
MAX_PART_BYTES = 100 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
PLATFORMS = {f"{system}-{arch}" for system in ("windows", "darwin", "linux") for arch in ("amd64", "arm64")}


def platform_id() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    result = f"{system}-{arch}"
    if result not in PLATFORMS:
        raise ClientError("No listed GUI installer supports this operating system/CPU.")
    return result


def _component(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+ -]{0,179}", value):
        raise ClientError("GUI manifest contains an unsafe filename or identifier.")
    if value.endswith((".", " ")) or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ClientError("GUI manifest contains an unsafe filename or identifier.")
    return value


def _text(value) -> None:
    if not isinstance(value, str) or not value or len(value) > 500 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ClientError("GUI manifest contains invalid display metadata.")


def _source(value) -> None:
    _text(value)
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError
    except ValueError:
        raise ClientError("GUI manifest requires public HTTPS source URLs.") from None


def _file_metadata(entry, limit: int) -> None:
    if not isinstance(entry, dict) or type(entry.get("size")) is not int or not 0 < entry["size"] <= limit:
        raise ClientError("GUI manifest contains an invalid file size.")
    if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", entry["sha256"]):
        raise ClientError("GUI manifest requires complete SHA-256 checksums.")


def _part_path(value) -> PurePosixPath:
    if not isinstance(value, str) or len(value) > 1024 or "\\" in value:
        raise ClientError("GUI manifest contains an unsafe bundle path.")
    pieces = value.split("/")
    if len(pieces) < 3 or pieces[:2] != ["vendor", "gui"]:
        raise ClientError("GUI bundle parts must remain under vendor/gui.")
    for piece in pieces:
        _component(piece)
    return PurePosixPath(value)


def _validate_package(package, *, companion: bool = False) -> None:
    _file_metadata(package, MAX_PACKAGE_BYTES)
    _component(package.get("filename"))
    if not isinstance(package.get("platform"), str) or package["platform"] not in PLATFORMS:
        raise ClientError("GUI manifest contains an unsupported platform.")
    _source(package.get("sourceUrl"))
    requirements = package.get("requirements", [])
    if not isinstance(requirements, list) or len(requirements) > 32:
        raise ClientError("GUI manifest requires a bounded list of package requirements.")
    for requirement in requirements:
        _text(requirement)
    parts = package.get("parts", [])
    if "parts" not in package:
        validate_download_url(package["sourceUrl"])
    if not isinstance(parts, list) or ("parts" in package and not 1 <= len(parts) <= 256):
        raise ClientError("GUI manifest requires a bounded list of bundle parts.")
    paths = set()
    for part in parts:
        _file_metadata(part, MAX_PART_BYTES)
        path = _part_path(part.get("path"))
        if path in paths:
            raise ClientError("GUI manifest repeats a bundle part.")
        paths.add(path)
    if parts and sum(part["size"] for part in parts) != package["size"]:
        raise ClientError("GUI bundle part sizes do not match the package size.")
    if companion and "companions" in package:
        raise ClientError("GUI companion packages must not contain nested companions.")
    companions = package.get("companions", [])
    if not isinstance(companions, list) or len(companions) > 4:
        raise ClientError("GUI manifest requires at most four companion packages.")
    filenames = {package["filename"].casefold()}
    for item in companions:
        if not isinstance(item, dict):
            raise ClientError("GUI manifest contains invalid companion metadata.")
        inherited = {"platform": package["platform"], **item}
        _validate_package(inherited, companion=True)
        if inherited["platform"] != package["platform"]:
            raise ClientError("GUI companion platform must match its installer.")
        if inherited["filename"].casefold() in filenames:
            raise ClientError("GUI companion filenames must be unique and differ from the installer.")
        filenames.add(inherited["filename"].casefold())
        if type(item.get("installOrder")) is not int or not 1 <= item["installOrder"] <= 4:
            raise ClientError("GUI companion install order must be an integer from 1 to 4.")
        _text(item.get("description"))


def _validate_app(app) -> None:
    if not isinstance(app, dict):
        raise ClientError("GUI manifest contains invalid application metadata.")
    _component(app.get("id"))
    _component(app.get("version"))
    _text(app.get("name"))
    _text(app.get("license"))
    _source(app.get("sourceUrl"))


def _is_link(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _check_path(path: Path, *, outside_git: bool = False) -> None:
    # lstat catches dangling links and Windows junctions before any file opens.
    for current in reversed((path, *path.parents)):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if _is_link(info):
            raise ClientError("GUI paths must not contain symbolic links or junctions.")
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise ClientError("GUI path parent is not a directory.")
        if outside_git and stat.S_ISDIR(info.st_mode) and os.path.lexists(current / ".git"):
            raise ClientError("Choose an installer output directory outside Git repositories.")


def _regular_size(path: Path, expected: int | None = None) -> int:
    _check_path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ClientError("GUI bundle and output files must be regular files.")
    if expected is not None and info.st_size != expected:
        raise ClientError("GUI file size does not match the manifest.")
    return info.st_size


def load_manifest(root: Path = ROOT) -> dict:
    path = root.resolve() / "vendor" / "gui" / "manifest.json"
    try:
        if _regular_size(path) > MAX_MANIFEST_BYTES:
            raise ClientError("GUI manifest exceeds its size limit.")
        with path.open("rb") as stream:
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise ClientError("GUI manifest exceeds its size limit.")
        manifest = json.loads(data)
    except (OSError, ValueError, RecursionError):
        raise ClientError("Cannot read the GUI link manifest; obtain a complete repository clone/ZIP.") from None
    if not isinstance(manifest, dict) or type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != 1:
        raise ClientError("Unsupported GUI manifest schema.")
    apps = manifest.get("apps")
    if not isinstance(apps, list) or not 1 <= len(apps) <= 16:
        raise ClientError("GUI manifest requires a bounded list of applications.")
    identifiers = set()
    for app in apps:
        _validate_app(app)
        if app["id"].casefold() in identifiers:
            raise ClientError("GUI manifest repeats an application.")
        identifiers.add(app["id"].casefold())
        packages = app.get("packages")
        if not isinstance(packages, list) or not 1 <= len(packages) <= 16:
            raise ClientError("GUI manifest requires a bounded list of packages.")
        platforms = set()
        for package in packages:
            _validate_package(package)
            if package["platform"] in platforms:
                raise ClientError("GUI manifest repeats an application platform.")
            platforms.add(package["platform"])
    return manifest


def _copy_checked(path: Path, entry: dict, output=None, combined=None) -> None:
    _regular_size(path, entry["size"])
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(min(CHUNK_BYTES, entry["size"] - size + 1)):
            size += len(chunk)
            if size > entry["size"]:
                raise ClientError("GUI file exceeds its expected size.")
            digest.update(chunk)
            if combined is not None:
                combined.update(chunk)
            if output is not None:
                output.write(chunk)
    if size != entry["size"] or digest.hexdigest() != entry["sha256"].lower():
        raise ClientError("GUI checksum verification failed; restore an intact bundle.")


def restore_package(app: dict, package: dict, output_dir: Path | None = None, *, root: Path = ROOT, allow_download: bool = False) -> Path:
    _validate_app(app)
    _validate_package(package)
    for companion in sorted(package.get("companions", []), key=lambda item: item["installOrder"]):
        options = {"allow_download": True} if allow_download else {}
        restore_package(app, {"platform": package["platform"], **companion}, output_dir, root=root, **options)
    root = root.resolve()
    base = Path(output_dir) if output_dir is not None else Path.home() / "Downloads" / "VPN-GUIs"
    # Do not resolve first: that would conceal a caller-supplied symlink.
    base = base.expanduser().absolute()
    _check_path(base, outside_git=True)
    if base.resolve().is_relative_to(root):
        raise ClientError("Choose an installer output directory outside the repository.")
    target = base / app["id"] / app["version"] / package["platform"] / package["filename"]
    _check_path(target, outside_git=True)
    if os.path.lexists(target):
        try:
            _copy_checked(target, package)
        except (ClientError, OSError):
            raise ClientError("An existing installer differs from the bundle; it will not be overwritten. Choose another output directory.") from None
        return target
    if "parts" not in package and not allow_download:
        raise ClientError("No cached installer. Use --download to authorize the pinned official download.")
    sources = [(root.joinpath(*_part_path(part["path"]).parts), part) for part in package.get("parts", [])]
    for source, part in sources:
        _regular_size(source, part["size"])
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_path(target.parent, outside_git=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".vpn-gui-", suffix=".partial", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        if "parts" not in package:
            os.close(descriptor)
            temporary.unlink(missing_ok=True)
            download(package["sourceUrl"], temporary, package["size"])
            _copy_checked(temporary, package)
        else:
            combined = hashlib.sha256()
            with os.fdopen(descriptor, "wb") as output:
                for source, part in sources:
                    _copy_checked(source, part, output, combined)
                output.flush()
                os.fsync(output.fileno())
            if temporary.stat().st_size != package["size"] or combined.hexdigest() != package["sha256"].lower():
                raise ClientError("Assembled GUI checksum verification failed; restore an intact bundle.")
        _check_path(target, outside_git=True)
        # A hard link publishes complete bytes atomically and can never overwrite.
        # Standard NTFS, APFS and Linux filesystems support this operation.
        try:
            os.link(temporary, target)
        except FileExistsError:
            raise ClientError("The installer output appeared during restoration; it will not be overwritten.") from None
        return target
    finally:
        temporary.unlink(missing_ok=True)


def open_folder(folder: Path) -> None:
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(str(folder))
        else:
            command = "open" if system == "Darwin" else "xdg-open"
            subprocess.run([command, str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        print("Could not open the folder automatically. Open the displayed folder manually.")


def choose_package(manifest: dict, current_platform: str):
    available = [(app, package) for app in manifest["apps"] for package in app["packages"] if package["platform"] == current_platform]
    if not available:
        raise ClientError("No GUI installer is listed for this operating system/CPU.")
    print(f"\nDesktop GUI installers ({current_platform}; official release links)")
    for index, (app, _) in enumerate(available, 1):
        print(f"  {index}  {app['name']} {app['version']}")
    print("  0  Cancel")
    while True:
        try:
            choice = input(f"Choose [0-{len(available)}]: ").strip()
        except EOFError:
            return None
        if choice == "0":
            return None
        if choice in {str(index) for index in range(1, len(available) + 1)}:
            return available[int(choice) - 1]
        print("Choose one of the displayed numbers.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--app", help="Application ID; omit for the current-platform menu.")
    result.add_argument("--download", action="store_true", help="Authorize download of the pinned official installer and companions; never execute them.")
    result.add_argument("--platform", choices=sorted(PLATFORMS), help="Restore another platform's package; requires --app.")
    result.add_argument("--output-dir", type=Path, help="Directory outside Git; default: ~/Downloads/VPN-GUIs.")
    result.add_argument("--profiles-file", type=Path, default=default_profiles_file(), help="Private profile bundle; overrides VPN_PROFILES_FILE.")
    profiles = result.add_mutually_exclusive_group()
    profiles.add_argument("--export-profiles", action="store_true", help="Export configured profiles to a fresh private directory (default in the menu).")
    profiles.add_argument("--no-profiles", action="store_true", help="Restore only the installer; do not read or export VPN profiles.")
    opening = result.add_mutually_exclusive_group()
    opening.add_argument("--open-folder", "--openfolder", action="store_true", help="Open the output folder, never the installer.")
    opening.add_argument("--no-open", action="store_true", help="Do not open the output folder (default with --app).")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.platform and not args.app:
        arguments.error("--platform requires --app; the interactive menu uses the current platform.")
    try:
        manifest = load_manifest()
        current_platform = args.platform or platform_id()
        if args.app:
            selected = next(((app, package) for app in manifest["apps"] if app["id"] == args.app
                             for package in app["packages"] if package["platform"] == current_platform), None)
            if selected is None:
                raise ClientError("The requested application/platform is not listed.")
        else:
            selected = choose_package(manifest, current_platform)
            if selected is None:
                return 0
        if selected[1].get("requirements"):
            print("Package requirements:")
            for requirement in selected[1]["requirements"]:
                print(f"  - {requirement}")
        if "parts" not in selected[1] and not args.download:
            print(f"Official installer: {selected[1]['sourceUrl']}")
            for companion in selected[1].get("companions", []):
                print(f"Official prerequisite: {companion['sourceUrl']}")
            print("Use --download to fetch and verify these packages, or install from the official links manually.")
            print("No downloads, profile exports or installation performed.")
            return 0
        options = {"allow_download": True} if args.download else {}
        destination = restore_package(*selected, output_dir=args.output_dir, **options)
        for companion in sorted(selected[1].get("companions", []), key=lambda item: item["installOrder"]):
            print(f"Install first ({companion['installOrder']}): {companion['description']}")
            print(f"Verified companion: {destination.parent / companion['filename']}")
        print(f"Verified installer: {destination}")
        print("Open/extract and install it manually. Keep normal OS security checks enabled.")
        print("Nothing was installed or started; system proxy and routing settings are unchanged.")
        if not args.no_profiles and (args.export_profiles or not args.app):
            profile_directory = destination.parent / f"profiles-{uuid.uuid4().hex}"
            _check_path(profile_directory, outside_git=True)
            if os.path.lexists(profile_directory):
                raise ClientError("The private profile directory already exists; retry to create a fresh directory.")
            profile_file = export_gui_profiles(selected[0]["id"], profile_directory, args.profiles_file)
            print(f"Private VPN import file: {profile_file}")
            print("This file contains VPN credentials. Keep it private; do not upload it to support messages or Git.")
            if selected[0]["id"] == "clash-verge-rev":
                print("In the installed GUI, import this local YAML profile, then select a configured profile in the VPN group.")
            else:
                print("In the installed GUI, import the links from this text file, then select a configured profile.")
            print("Profiles were exported only; no GUI was launched or configured automatically.")
        if not args.no_open and (args.open_folder or not args.app):
            open_folder(destination.parent)
        return 0
    except KeyboardInterrupt:
        print("Cancelled. No installer was launched.")
        return 130
    except ClientError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("Error: Cannot prepare the installer or private profiles. Check the official download, output permissions, free space and hard-link support.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
