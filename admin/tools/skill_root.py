"""Locate a complete helper checkout without reading profiles or downloading files."""
import argparse
import os
from pathlib import Path


REQUIRED = (
    "admin/tools/skill_root.py", "plugin.json", "clients/vpn.py", "admin/install-server.sh",
    "admin/tools/speed_test.py", "admin/tools/guest_diagnostics.sh",
    "docs/CLIENTS.md", "infra/vpn/main.bicep", "vendor/manifest.json",
)
SOURCE_URL = "https://github.com/ness001/vpn-skill-all-in-one.git"


def cache_root():
    return Path.home() / ".cache" / "vpn-skill" / "source"


def complete(candidate):
    return all((candidate / name).is_file() for name in REQUIRED)


def resolve_root(root=None, skill_dir=None, *, cwd=None, editable=False):
    """Prefer an explicit root, bundled helpers, nearby source, then shared cache."""
    selected = root if root is not None else os.environ.get("VPN_SKILL_ROOT")
    if selected is not None:
        candidate = Path(selected).expanduser()
        if not candidate.is_absolute():
            raise ValueError("VPN_SKILL_ROOT/--root must be an absolute checkout path")
        candidate = candidate.resolve()
        if not complete(candidate):
            raise ValueError("Incomplete helper checkout at the explicit root")
        if editable and not (candidate / ".git").exists():
            raise ValueError("Vendor maintenance requires an editable Git source checkout")
        return candidate

    candidates = []
    if skill_dir is not None:
        directory = Path(skill_dir).expanduser()
        if not directory.is_absolute() or directory.parent.name != "skills":
            raise ValueError("--skill-dir must be an absolute skills/<name> directory")
        if not editable:
            candidates.append(directory.parent.parent)
    directory = Path(cwd if cwd is not None else Path.cwd()).resolve()
    for parent in (directory, *directory.parents):
        candidates.extend((parent, parent / "toolkit"))
    candidates.append(cache_root())
    for candidate in candidates:
        candidate = candidate.resolve()
        if complete(candidate) and (not editable or (candidate / ".git").exists()):
            return candidate
    raise ValueError(
        f"No complete helper checkout found. Prepare {cache_root()} from {SOURCE_URL}; "
        "follow the loaded skill's first-use instructions."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Absolute helper checkout; overrides VPN_SKILL_ROOT")
    parser.add_argument("--skill-dir", help="Absolute loaded skills/<name> directory")
    parser.add_argument("--editable", action="store_true", help="Require source for vendor maintenance")
    args = parser.parse_args(argv)
    try:
        root = resolve_root(args.root, args.skill_dir, editable=args.editable)
    except ValueError as error:
        parser.error(str(error))
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
