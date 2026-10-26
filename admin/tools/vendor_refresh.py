"""Build pinned official core link metadata, never download release executables."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "clients"))
from core_install import RELEASES, download, release_digest
from vpn_common import ClientError, limited_read


def core_links(profile: str, metadata: dict) -> list[dict]:
    release = RELEASES[profile]
    records = []
    for system, asset_name in release["assets"].items():
        url, digest = release_digest(metadata, profile, asset_name, None)
        asset = next(item for item in metadata["assets"] if item["name"] == asset_name)
        records.append({
            "schemaVersion": 1, "profile": profile, "project": release["project"],
            "tag": release["tag"], "platform": system, "asset": asset_name,
            "assetSha256": digest, "assetSize": asset["size"], "assetUrl": url,
            "releaseUrl": f"https://github.com/{release['project']}/releases/tag/{release['tag']}",
            "sourceUrl": f"https://github.com/{release['project']}/tree/{release['tag']}",
            "sourceArchiveUrl": f"https://github.com/{release['project']}/archive/refs/tags/{release['tag']}.tar.gz",
        })
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New candidate JSON; existing files are never replaced")
    parser.add_argument("--online", action="store_true", help="Authorize fetching official release metadata only")
    args = parser.parse_args(argv)
    if not args.online:
        parser.error("--online is required to fetch release metadata")
    if args.output.exists():
        parser.error("Output already exists; choose a new candidate path")
    cores = []
    with tempfile.TemporaryDirectory(prefix="vpn-core-links-") as temp:
        for profile, release in RELEASES.items():
            path = Path(temp) / f"{profile}.json"
            url = f"https://api.github.com/repos/{release['project']}/releases/tags/{urllib.parse.quote(release['tag'], safe='')}"
            download(url, path, 2 * 1024 * 1024)
            cores.extend(core_links(profile, json.loads(limited_read(path, 2 * 1024 * 1024))))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"schemaVersion": 1, "cores": cores}, stream, indent=2)
        stream.write("\n")
    print("Candidate links saved. Before integration, review licenses/source references and supply independently verified binarySha256/size metadata; no release artifacts downloaded.")


if __name__ == "__main__":
    main()
