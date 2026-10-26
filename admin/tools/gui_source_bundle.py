#!/usr/bin/env python3
"""Record exact GUI/copyleft source links without mirroring source archives."""
import json
from pathlib import Path


SOURCES = [
    ("v2rayn", "2dust/v2rayN", "521230c40d5c180bc0727cf4003907edfae5a3e0"),
    ("globalhotkeys", "2dust/GlobalHotKeys", "162d401dfe0140b41d1fa349b9aadb4060e739b1"),
    ("sing-box", "SagerNet/sing-box", "b5ebaa1fc0f2b94256180b95468e73ef53caa27d"),
    ("mihomo", "MetaCubeX/mihomo", "e26714a181ac0e2fa803453c0a8e9a9ce94e31cb"),
    ("xray-fork", "autorepobot/Xray", "ced1f5508828102592f186aeed08798997c137ff"),
    ("clash-verge-rev", "clash-verge-rev/clash-verge-rev", "28f2efc504059b1dc75c793618b775c8e1b2a5f1"),
    ("clash-verge-service", "clash-verge-rev/clash-verge-service-ipc", "b964ed2992599fadefd589425c1acdabcb875623"),
]


def acquire(item):
    name, project, commit = item
    return {"name": name, "project": project, "commit": commit,
            "sourceUrl": f"https://codeload.github.com/{project}/tar.gz/{commit}"}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New source-link candidate; existing files never replaced")
    args = parser.parse_args()
    sources = [acquire(item) for item in SOURCES]
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"schemaVersion": 1, "sources": sources}, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
