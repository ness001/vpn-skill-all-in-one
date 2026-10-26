"""Verify cached cores offline; download pinned official releases only by request."""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from vpn_common import (
    ClientError, ROOT, TOOLS, limited_read, private_directory, private_write,
    sha256_file, valid_sha256,
)

RELEASES = {
    "vless": {
        "project": "XTLS/Xray-core", "tag": "v26.3.27", "name": "xray",
        "assets": {
            "windows-amd64": "Xray-windows-64.zip",
            "darwin-amd64": "Xray-macos-64.zip",
            "darwin-arm64": "Xray-macos-arm64-v8a.zip",
        },
    },
    "hysteria2": {
        "project": "HyNetworks/hysteria", "tag": "app/v2.12.3", "name": "hysteria",
        "assets": {
            "windows-amd64": "hysteria-windows-amd64.exe",
            "darwin-amd64": "hysteria-darwin-amd64",
            "darwin-arm64": "hysteria-darwin-arm64",
        },
    },
}
BUNDLED = ROOT / "vendor" / "cores"
MAX_DOWNLOAD = 160 * 1024 * 1024
MAX_UNPACKED = 256 * 1024 * 1024
TRUSTED_HOSTS = {
    "api.github.com", "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com", "msedge.sf.dl.delivery.mp.microsoft.com",
}


def core_profile(profile: str) -> str:
    if profile not in RELEASES:
        raise ClientError("Choose protocol vless or hysteria2.")
    return profile


def platform_id() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    result = f"{system}-{arch}"
    if result not in RELEASES["vless"]["assets"]:
        raise ClientError("Supported systems: Windows x64 and macOS Intel/Apple Silicon.")
    return result


def validate_download_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)):
        raise ClientError("Download redirected outside the official HTTPS release hosts.")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, destination: Path, limit: int) -> None:
    validate_download_url(url)
    request = urllib.request.Request(url, headers={
        "User-Agent": "private-vpn-client/1", "Accept": "application/vnd.github+json",
    })
    opener = urllib.request.build_opener(SafeRedirect())
    with opener.open(request, timeout=30) as response, destination.open("xb") as stream:
        validate_download_url(response.geturl())
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > limit:
            raise ClientError("Official release download exceeds its size limit.")
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ClientError("Official release download exceeds its size limit.")
            stream.write(chunk)


def release_digest(metadata: dict, profile: str, asset_name: str, explicit: str | None) -> tuple[str, str]:
    profile = core_profile(profile)
    release = RELEASES[profile]
    if (metadata.get("tag_name") != release["tag"]
            or metadata.get("draft") is not False or metadata.get("prerelease") is not False):
        raise ClientError("Release metadata does not match the pinned stable release.")
    assets = [item for item in metadata.get("assets", []) if item.get("name") == asset_name]
    if len(assets) != 1:
        raise ClientError("Expected official release asset is missing or ambiguous.")
    asset = assets[0]
    expected_url = f"https://github.com/{release['project']}/releases/download/{release['tag']}/{asset_name}"
    if asset.get("browser_download_url") != expected_url:
        raise ClientError("Unexpected official release asset URL.")
    if type(asset.get("size")) is not int or not 0 < asset["size"] <= MAX_DOWNLOAD:
        raise ClientError("Official release asset size is invalid.")
    published = asset.get("digest") or ""
    published_hash = valid_sha256(published[7:]) if published.startswith("sha256:") else None
    if explicit:
        digest = valid_sha256(explicit)
        if published_hash and not hmac.compare_digest(digest, published_hash):
            raise ClientError("Provided checksum disagrees with the published SHA-256 digest.")
    elif published_hash:
        digest = published_hash
    else:
        raise ClientError("This release has no published SHA-256 digest; supply a trusted --sha256.")
    return expected_url, digest


def extract_binary(archive: Path, destination: Path, expected_name: str) -> None:
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) > 200 or sum(item.file_size for item in entries) > MAX_UNPACKED:
            raise ClientError("Release archive exceeds extraction limits.")
        for item in entries:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                    or ":" in item.filename or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                raise ClientError("Unsafe entry in the release archive.")
        binaries = [item for item in entries if item.filename == expected_name and not item.is_dir()]
        if len(binaries) != 1:
            raise ClientError("Expected executable is missing or ambiguous in release archive.")
        # Never extract paths from the archive, even after validating them.
        with package.open(binaries[0]) as source, destination.open("xb") as target:
            size = 0
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UNPACKED:
                    raise ClientError("Executable exceeds extraction limits.")
                target.write(chunk)


def install_location(profile: str, system: str, tools: Path = TOOLS) -> tuple[Path, str]:
    profile = core_profile(profile)
    release = RELEASES[profile]
    suffix = ".exe" if system.startswith("windows-") else ""
    directory = tools / release["name"] / release["tag"].replace("/", "-") / system
    return directory, release["name"] + suffix


def fetch_core(profile: str, explicit_hash: str | None = None, tools: Path = TOOLS, *, online: bool = False) -> Path:
    system = platform_id()
    profile = core_profile(profile)
    release = RELEASES[profile]
    if not online:
        if explicit_hash:
            raise ClientError("--sha256 is a release-download option; use --online explicitly.")
        core = resolve_core(profile, None, None, tools)
        bundled_directory, _ = install_location(profile, system, BUNDLED)
        source = "bundled" if core.parent == bundled_directory else "cached"
        print(f"Verified {source} {release['name']} {release['tag']} ({system}); no download needed.")
        return core
    asset_name = release["assets"][system]
    destination, binary_name = install_location(profile, system, tools)
    if destination.exists() or destination.is_symlink():
        core = verify_local_core(profile, system, destination, binary_name, bundled=False,
                                 asset_hash=explicit_hash)
        print(f"Verified cached {release['name']} {release['tag']} ({system}); existing files not overwritten.")
        return core
    bundled_directory, bundled_name = install_location(profile, system, BUNDLED)
    if bundled_directory.exists() or bundled_directory.is_symlink():
        verify_local_core(profile, system, bundled_directory, bundled_name, bundled=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with private_directory(destination.parent) as work:
        metadata_path = work / "release.json"
        api_url = f"https://api.github.com/repos/{release['project']}/releases/tags/{urllib.parse.quote(release['tag'], safe='')}"
        download(api_url, metadata_path, 2 * 1024 * 1024)
        metadata = json.loads(limited_read(metadata_path, 2 * 1024 * 1024))
        url, digest = release_digest(metadata, profile, asset_name, explicit_hash)
        size = next(item["size"] for item in metadata["assets"] if item["name"] == asset_name)
        archive = work / "download"
        download(url, archive, size)
        if archive.stat().st_size != size or not hmac.compare_digest(sha256_file(archive), digest):
            raise ClientError("Release checksum verification failed; nothing was installed or executed.")
        core = work / binary_name
        if asset_name.endswith(".zip"):
            extract_binary(archive, core, binary_name)
            archive.unlink()
        else:
            archive.rename(core)
        if os.name != "nt":
            core.chmod(0o700)
        manifest = {
            "schemaVersion": 1, "profile": profile, "project": release["project"],
            "tag": release["tag"], "platform": system, "asset": asset_name,
            "assetSha256": digest, "binarySha256": sha256_file(core),
        }
        metadata_path.unlink()
        private_write(work / "verified.json", json.dumps(manifest).encode())
        # Refuse replacement; another installation may have won the race.
        if destination.exists():
            raise ClientError("The install destination appeared during download; retry verification.")
        work.rename(destination)
    print(f"Installed verified {release['name']} {release['tag']} ({system}).")
    return destination / binary_name


def verify_executable(core: Path, expected_hash: str) -> None:
    try:
        matches = core.is_file() and hmac.compare_digest(sha256_file(core), expected_hash)
    except OSError:
        matches = False
    if not matches:
        raise ClientError("Core executable checksum verification failed; refusing to execute it.")
    if os.name != "nt" and not os.access(core, os.X_OK):
        raise ClientError("Core executable is not executable; set owner execute permission.")


def verify_local_core(profile: str, system: str, directory: Path, name: str, *,
                      bundled: bool, asset_hash: str | None = None, manifest_adapter=None) -> Path:
    source = "Bundled" if bundled else "Cached"
    core = directory / name
    manifest_path = directory / "verified.json"
    if (directory.is_symlink() or not directory.is_dir() or core.is_symlink()
            or manifest_path.is_symlink() or not core.is_file()):
        raise ClientError(f"{source} core is incomplete or uses links; restore its trusted files. No download attempted.")
    try:
        manifest = json.loads(limited_read(manifest_path, 8192))
    except (OSError, ValueError):
        raise ClientError(f"{source} core metadata is missing or invalid; restore its trusted files. No download attempted.") from None
    profile = core_profile(profile)
    release = RELEASES[profile]
    expected = {
        "schemaVersion": 1, "project": release["project"], "tag": release["tag"],
        "platform": system, "asset": release["assets"][system],
    }
    if manifest_adapter is not None and not bundled:
        manifest = manifest_adapter(manifest, profile)
    if (not isinstance(manifest, dict) or type(manifest.get("schemaVersion")) is not int
            or manifest.get("profile") != profile
            or any(manifest.get(key) != value for key, value in expected.items())
            or not isinstance(manifest.get("assetSha256"), str)
            or not isinstance(manifest.get("binarySha256"), str)):
        raise ClientError(f"{source} core metadata does not match the pinned release.")
    recorded_asset_hash = valid_sha256(manifest["assetSha256"])
    if asset_hash and not hmac.compare_digest(recorded_asset_hash, valid_sha256(asset_hash)):
        raise ClientError("Provided checksum disagrees with the cached release-asset SHA-256 digest.")
    verify_executable(core, valid_sha256(manifest["binarySha256"]))
    return core


def resolve_core(profile: str, external: str | None, digest: str | None, tools: Path = TOOLS) -> Path:
    profile = core_profile(profile)
    if external:
        if not digest:
            raise ClientError("An external --core requires --core-sha256 from a trusted source.")
        core = Path(external).expanduser().resolve(strict=True)
        verify_executable(core, valid_sha256(digest))
        return core
    if digest:
        raise ClientError("--core-sha256 is only used with --core.")
    system = platform_id()
    for base, bundled in ((BUNDLED, True), (tools, False)):
        directory, name = install_location(profile, system, base)
        if directory.exists() or directory.is_symlink():
            # A present but invalid bundle must never fall through to a cache or network.
            return verify_local_core(profile, system, directory, name, bundled=bundled)
    raise ClientError(
        f"No cached core for {profile} ({system}). This toolkit stores official links, not executables; "
        f"no download attempted. For a manual download use fetch-core {profile} --online, "
        "or provide --core and --core-sha256."
    )
