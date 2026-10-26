#!/usr/bin/env python3
"""Build official GUI download-link metadata without downloading package bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MAX_ASSET = 1024 * 1024 * 1024
ALLOWED = {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "codeload.github.com", "msedge.sf.dl.delivery.mp.microsoft.com"}


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Only official HTTPS release/source hosts are allowed")


def download(url: str, path: Path, max_size: int = MAX_ASSET) -> str:
    check_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "vpn-gui-links", "Accept": "application/vnd.github+json"})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.build_opener(Redirect()).open(request, timeout=60) as response, path.open("xb") as target:
        check_url(response.geturl())
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            size += len(chunk)
            if size > max_size:
                raise ValueError("Metadata exceeds reviewed size bound")
            digest.update(chunk)
            target.write(chunk)
    return digest.hexdigest()


def package_link(app: dict, package: dict, metadata: dict) -> dict:
    assets = [a for a in metadata["assets"] if a["name"] == package["asset"]]
    if len(assets) != 1:
        raise ValueError("Expected exactly one official package")
    asset = assets[0]
    expected = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        raise ValueError("A published upstream SHA256 is required")
    if type(asset["size"]) is not int or not 0 < asset["size"] <= MAX_ASSET:
        raise ValueError("Unexpected upstream package size")
    url = f"https://github.com/{app['project']}/releases/download/{app['version']}/{package['asset']}"
    if asset["browser_download_url"] != url:
        raise ValueError("Release asset origin mismatch")
    check_url(url)
    result = {"platform": package["platform"], "filename": package["asset"],
              "sha256": expected[7:], "size": asset["size"], "sourceUrl": url,
              "requirements": package.get("requirements", [])}
    if package.get("companions"):
        result["companions"] = []
        for spec in package["companions"]:
            check_url(spec["sourceUrl"])
            if (urllib.parse.urlsplit(spec["sourceUrl"]).hostname != "msedge.sf.dl.delivery.mp.microsoft.com"
                    or not re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])
                    or type(spec["size"]) is not int or not 0 < spec["size"] <= MAX_ASSET):
                raise ValueError("Companion requires reviewed Microsoft-direct link, size and hash")
            result["companions"].append({key: spec[key] for key in
                ("filename", "sha256", "size", "sourceUrl", "installOrder", "description")})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path, help="Reviewed non-secret app/version/asset selection JSON")
    parser.add_argument("--output", type=Path, required=True, help="New candidate manifest; no overwriting")
    parser.add_argument("--online", action="store_true", help="Authorize official release metadata requests only")
    args = parser.parse_args(argv)
    if not args.online:
        parser.error("--online is required to fetch release metadata")
    if args.output.exists():
        parser.error("Output already exists")
    selected = json.loads(args.selection.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory(prefix="gui-release-meta-") as temp:
        for index, app in enumerate(selected["apps"]):
            metadata_path = Path(temp) / f"{index}.json"
            api = f"https://api.github.com/repos/{app['project']}/releases/tags/{urllib.parse.quote(app['version'], safe='')}"
            download(api, metadata_path, 8 * 1024 * 1024)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata["tag_name"] != app["version"] or metadata.get("draft") is not False or metadata.get("prerelease") is not False:
                raise ValueError("Selection must pin an official stable release")
            packages = [package_link(app, package, metadata) for package in app["packages"]]
            results.append({"id": app["id"], "name": app["name"], "version": app["version"],
                            "license": app["license"], "sourceUrl": f"https://github.com/{app['project']}/tree/{app['version']}",
                            "packages": packages})
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"schemaVersion": 1, "apps": results}, stream, indent=2)
        stream.write("\n")
    print("GUI link manifest saved; package bytes were not downloaded or executed. Companion hashes are reviewed pins, not fresh signature verification.")


if __name__ == "__main__":
    main()
