#!/usr/bin/env python3
"""Show official desktop client releases and explicitly export private imports."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

from gui_profiles import export_gui_profiles
from vpn_common import ClientError, default_profiles_file

APPS = {
    "v2rayn": ("v2rayN", "https://github.com/2dust/v2rayN/releases"),
    "clash-verge-rev": ("Clash Verge Rev", "https://github.com/clash-verge-rev/clash-verge-rev/releases"),
}


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


def choose_app() -> str | None:
    print("\nDesktop GUI clients (official release pages)")
    names = list(APPS)
    for index, app_id in enumerate(names, 1):
        print(f"  {index}  {APPS[app_id][0]}")
    print("  0  Cancel")
    while True:
        try:
            choice = input(f"Choose [0-{len(names)}]: ").strip()
        except EOFError:
            return None
        if choice == "0":
            return None
        if choice in {str(index) for index in range(1, len(names) + 1)}:
            return names[int(choice) - 1]
        print("Choose one of the displayed numbers.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--app", help="Supported application ID; omit for the menu.")
    result.add_argument("--output-dir", type=Path, help="Private export parent outside Git; default: ~/Downloads/VPN-GUIs.")
    result.add_argument("--profiles-file", type=Path, default=default_profiles_file(), help="Private profile bundle; overrides VPN_PROFILES_FILE.")
    profiles = result.add_mutually_exclusive_group()
    profiles.add_argument("--export-profiles", action="store_true", help="Explicitly export imports for an installed client to a fresh private directory.")
    profiles.add_argument("--no-profiles", action="store_true", help="Show release links only (the default); never read profiles.")
    opening = result.add_mutually_exclusive_group()
    opening.add_argument("--open-folder", "--openfolder", action="store_true", help="Open the private export folder, never a client or installer.")
    opening.add_argument("--no-open", action="store_true", help="Do not open the private export folder (default).")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.open_folder and not args.export_profiles:
        arguments.error("--open-folder requires --export-profiles.")
    try:
        app_id = args.app if args.app is not None else choose_app()
        if app_id is None:
            return 0
        if app_id not in APPS:
            raise ClientError("The requested application is not supported.")
        name, url = APPS[app_id]
        print(f"Official {name} releases: {url}")
        print("Install the package for your OS/CPU manually; follow upstream requirements and integrity guidance.")
        if not args.export_profiles:
            print("No downloads, profile exports or installation performed. Use --export-profiles for an installed client.")
            return 0
        base = args.output_dir or Path.home() / "Downloads" / "VPN-GUIs"
        directory = base.expanduser().absolute() / f"profiles-{uuid.uuid4().hex}"
        profile_file = export_gui_profiles(app_id, directory, args.profiles_file)
        print(f"Private VPN import file: {profile_file}")
        print("This file contains VPN credentials. Keep it private; do not upload it to support messages or Git.")
        if app_id == "clash-verge-rev":
            print("In the installed GUI, import this local YAML profile, then select a configured profile in the VPN group.")
        else:
            print("In the installed GUI, import the links from this text file, then select a configured profile.")
        print("Profiles were exported only; no client was launched or configured automatically.")
        if args.open_folder:
            open_folder(profile_file.parent)
        return 0
    except KeyboardInterrupt:
        print("Cancelled. No client or installer was launched.")
        return 130
    except ClientError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("Error: Cannot prepare private profiles. Check the private input path and output permissions.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
