#!/usr/bin/env python3
"""Choose a configured VPN profile, start local proxies and open a separate proxy browser."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from browser import running_browser
from core_install import resolve_core
from gui import main as gui_main
from vpn import BIND, build_config, load_profile, profile_id, profile_label, profile_names, resolve_protocol, running_core
from vpn_common import CleanupError, ClientError, ROOT, default_profiles_file

PYTHON_HELP = "Install Python 3.11+ from https://www.python.org/downloads/ and run VPN again."
CHECK_CODE = """import http.client, ssl, sys
connection = http.client.HTTPSConnection('127.0.0.1', int(sys.argv[1]), timeout=12, context=ssl.create_default_context())
try:
    connection.set_tunnel('example.com', 443)
    connection.request('HEAD', '/', headers={'Host': 'example.com', 'Connection': 'close'})
    response = connection.getresponse()
    sys.exit(0 if 200 <= response.status < 400 else 1)
finally:
    connection.close()
"""


def choose_profile(profiles_file: Path | None = None) -> str | None:
    profiles_file = profiles_file if profiles_file is not None else default_profiles_file()
    try:
        entries = [(name, profile_label(name, load_profile(profiles_file, name)))
                   for name in profile_names(profiles_file)]
    except ClientError:
        # A missing/invalid bundle must not prevent opening the GUI installer menu.
        entries = []
        print("Connection profiles unavailable; supply a valid private profile bundle to connect.")
    print("\nVPN")
    for index, (_, label) in enumerate(entries, 1):
        print(f"  {index}  {label}")
    gui_choice, exit_choice = str(len(entries) + 1), str(len(entries) + 2)
    print(f"  {gui_choice}  Desktop GUI installers\n  {exit_choice}  Exit")
    while True:
        try:
            choice = input(f"Choose [1-{exit_choice}]: ").strip()
        except EOFError:
            return None
        if choice == gui_choice:
            return "__gui__"
        if choice == exit_choice:
            return None
        if choice in {str(index) for index in range(1, len(entries) + 1)}:
            return entries[int(choice) - 1][0]
        print("Choose one of the displayed numbers.")


def check_forwarding(http_port: int) -> None:
    # A subprocess bounds DNS/TLS/header reads together; no environment proxy or
    # no_proxy value can bypass the explicitly selected loopback CONNECT proxy.
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with subprocess.Popen([sys.executable, "-I", "-c", CHECK_CODE, str(http_port)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, **options) as probe:
        try:
            status = probe.wait(timeout=20)
        except subprocess.TimeoutExpired:
            raise ClientError("HTTPS check timed out; browsing was not verified.") from None
        finally:
            if probe.poll() is None:
                probe.kill()
                probe.wait(timeout=5)
    if status:
        raise ClientError("HTTPS check failed; browsing was not verified. TLS verification remains enabled.")
    print("HTTPS check passed through the selected VPN (example.com).", flush=True)


def proxy_instructions(socks_port: int, http_port: int) -> None:
    print(f"Set an application's HTTP proxy to {BIND}:{http_port} or SOCKS5 to {BIND}:{socks_port}.", flush=True)
    print("Keep this terminal open; Ctrl+C stops the VPN. System proxy settings are unchanged.", flush=True)


def wait_session(core, browser=None) -> None:
    while True:
        status = core.poll()
        if status is not None:
            raise ClientError(f"VPN client stopped (status {status}); raw core output is suppressed.")
        if browser is not None:
            status = browser.poll()
            if status is not None:
                if status:
                    print("The separate browser stopped. Local proxies remain available; Ctrl+C stops the VPN.", flush=True)
                    browser = None
                else:
                    return
        time.sleep(0.2)


def connect(args) -> None:
    profile = load_profile(args.profiles_file, args.profile)
    config = build_config(args.profile, profile, args.socks_port, args.http_port)
    protocol = resolve_protocol(args.profile, profile)
    core = resolve_core(protocol, None, None)
    print(f"Starting {profile_label(args.profile, profile)}...", flush=True)
    with running_core(protocol, config, core, args.socks_port, args.http_port, args.ready_timeout) as child:
        print(f"{args.profile.upper()} local proxies ready. Website access is not yet verified.", flush=True)
        if args.check:
            check_forwarding(args.http_port)
            return
        with ExitStack() as browser_session:
            browser = None
            if not args.no_browser:
                try:
                    browser = browser_session.enter_context(running_browser(args.http_port))
                except CleanupError:
                    raise
                except ClientError as error:
                    print(str(error), flush=True)
                except OSError:
                    print("Cannot open the separate browser. Local proxies remain available.", flush=True)
            if browser is not None:
                print("Separate proxy browser opened. Your normal browser and system proxy are unchanged.", flush=True)
                print("Keep this terminal open. Close the separate browser or press Ctrl+C to stop.", flush=True)
            else:
                proxy_instructions(args.socks_port, args.http_port)
            wait_session(child, browser)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("profile", nargs="?", type=profile_id, help="Configured profile ID; omit to show the menu.")
    result.add_argument("--no-browser", action="store_true", help="Run local proxies without opening a browser.")
    result.add_argument("--check", action="store_true", help="Check HTTPS through the VPN, then stop; no browser.")
    result.add_argument("--profiles-file", type=Path, default=default_profiles_file(), help=argparse.SUPPRESS)
    result.add_argument("--socks-port", type=int, default=10808, help=argparse.SUPPRESS)
    result.add_argument("--http-port", type=int, default=10809, help=argparse.SUPPRESS)
    result.add_argument("--ready-timeout", type=float, default=20, help=argparse.SUPPRESS)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.profile is None and (args.check or args.no_browser):
        arguments.error("Choose a configured profile ID when using --check or --no-browser.")
    try:
        if sys.version_info < (3, 11):
            raise ClientError(PYTHON_HELP)
        args.profile = args.profile or choose_profile(args.profiles_file)
        if args.profile is None:
            return 0
        if args.profile == "__gui__":
            return gui_main(["--profiles-file", str(args.profiles_file)])
        connect(args)
        print("Stopped. Temporary VPN configuration and browser profile removed.")
        return 0
    except KeyboardInterrupt:
        print("Stopped. Temporary VPN configuration and browser profile removed.")
        return 130
    except ClientError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Error: {type(error).__name__}; details suppressed to protect connection profiles.", file=sys.stderr)
        return 1


def interrupted(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, interrupted)
    raise SystemExit(main())
