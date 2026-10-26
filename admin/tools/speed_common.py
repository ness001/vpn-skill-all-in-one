"""Shared speed-test helpers; no browser dependencies or private deployment defaults."""
from contextlib import ExitStack
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import socket

ROOT = Path(__file__).resolve().parents[2]


def select_profiles(args, parser, configured_names, default_profiles=None):
    """Resolve configured IDs only for execution; dry plans never open a bundle."""
    if args.profiles is None:
        if default_profiles is not None:
            args.profiles = list(default_profiles)
        elif args.dry_run:
            args.profiles = []
        else:
            try:
                args.profiles = list(configured_names(args.profiles_file))
            except Exception:
                parser.error("Cannot select configured profiles; check the private bundle or pass --profiles explicitly.")
            if not args.profiles:
                parser.error("The private bundle contains no configured profiles.")
    if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name)
           for name in args.profiles):
        parser.error("Profile identifiers must use 1-64 letters, digits, underscores or hyphens, starting with a letter or digit.")
    if len(set(args.profiles)) != len(args.profiles):
        parser.error("Repeated profile names are not allowed.")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def runtime_root():
    return Path.home() / ".cache" / "vpn-skill" / "runtime"


def output_path(value: Path | None, root: Path | None = None) -> Path | None:
    if value is None:
        return None
    root = (root if root is not None else runtime_root()).resolve()
    allowed = root / ".local" / "speed-tests"
    candidate = value if value.is_absolute() else root / value
    if (candidate.is_symlink() or candidate.exists()
            or candidate.resolve().parent != allowed
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.json", candidate.name)
            or any(path.is_symlink() for path in (root / ".local", allowed))):
        raise ValueError("Output must be a new JSON file inside .local/speed-tests (no links or overwrite).")
    return candidate.resolve()


def free_ports() -> tuple[int, int]:
    with ExitStack() as stack:
        numbers = []
        for _ in range(2):
            listener = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", 0))
            numbers.append(listener.getsockname()[1])
        udp = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        udp.bind(("127.0.0.1", numbers[0]))
        return tuple(numbers)
