"""Fresh Ubuntu installation. Dry-run never needs root or changes the host."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

import render

# Release archive hashes, not hashes of extracted executables. Keep the official
# source URL and hash together when reviewing an explicit version upgrade.
RELEASES = {
    "xray": {
        "url": "https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-linux-64.zip",
        "sha256": "23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae",
        "member": "xray", "format": "zip",
    },
    "caddy": {
        "url": "https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_linux_amd64.tar.gz",
        "sha256": "527fbf917c39189a1e3b31d34fa955601680b2d5c8055d2a87b8b9588dec7bb9",
        "member": "caddy", "format": "tar",
    },
    "hy2": {
        "url": "https://github.com/HyNetworks/hysteria/releases/download/app/v2.12.3/hysteria-linux-amd64",
        "sha256": "8c7a68a906998b747a0db87586e364f995fbfddb95693ae6e2fdb68a6e920d3e",
        "member": None, "format": "binary",
    },
}
STATE = Path(render.STATE_ROOT)
MARKER = STATE / "state.json"
UNITS = Path("/etc/systemd/system")
OWNER = "personal-vpn-installer-v1"


class InstallError(Exception):
    pass


class HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if not newurl.startswith("https://"):
            raise InstallError("Refusing a download redirect to an insecure transport.")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Install VLESS or Hysteria2 on a fresh Ubuntu 22.04/24.04 LTS x86_64 server.")
    parser.add_argument("--profile", choices=tuple(render.PROFILES), help="vless or hysteria2")
    parser.add_argument("--domain")
    parser.add_argument("--public-ip")
    parser.add_argument("--email", default="", help="Optional ACME contact email")
    parser.add_argument("--credentials-file", type=Path, help="Explicit private migration JSON; never pass secrets as arguments")
    parser.add_argument("--configure-firewall", action="store_true", help="Only add VPN allow rules if UFW is already active")
    parser.add_argument("--yes", action="store_true", help="Consent to the described local installation without prompts")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and describe changes without network or writes")
    args = parser.parse_args(argv)
    for key, prompt in (("profile", "Protocol [vless/hysteria2]: "), ("domain", "Public DNS hostname: "), ("public_ip", "Server public IPv4: ")):
        if not getattr(args, key):
            if args.yes or not sys.stdin.isatty():
                parser.error("--profile, --domain and --public-ip are all required in noninteractive mode.")
            setattr(args, key, input(prompt).strip())
    args.target = render.validate_target(args.profile, args.domain, args.public_ip, args.email)
    return args


def plan(args):
    print(f"Profile: {args.profile}; hostname: {args.target['domain']}; expected public IPv4: {args.target['public_ip']}")
    print("Target: fresh Ubuntu 22.04 or 24.04 LTS, x86_64, Python 3.10+, systemd; IPv4-only public DNS.")
    if render.resolve_profile(args.profile) == "vless":
        print(f"Install Xray {render.VERSIONS['xray']} (127.0.0.1:39761) and Caddy {render.VERSIONS['caddy']} (TCP 80/443).")
    else:
        print(f"Install Hysteria2 {render.VERSIONS['hy2']}: UDP 443 proxy, TCP 443 ACME TLS-ALPN challenge.")
    print("Real run: check ownership/conflicts/DNS; apt update and install ca-certificates only;")
    print("verify pinned official downloads; create non-root services and private configurations; request public ACME TLS.")
    print("No SSH edits, reboot, full OS upgrade, cloud/DNS changes, Docker, NAT or IP forwarding.")
    print("Firewall: " + ("add only VPN allow rules to already-active UFW; never enable/reset it." if args.configure_firewall else "unchanged (including UFW)."))
    print("Cloud firewall/NSG and DNS must already permit these ports directly to this server.")
    print(f"Private client files: {render.CLIENT_ROOT}/{render.storage_profile(args.profile)}/ (not printed).")


def private_source(path, real):
    try:
        if path.is_symlink():
            raise InstallError("Credential source must be a small regular file, not a symlink.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "r", encoding="utf-8") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
                raise InstallError("Credential source must be a small regular file, not a symlink.")
            if os.name == "posix":
                allowed_owners = {0, os.getuid()}
                if os.geteuid() == 0 and os.environ.get("SUDO_UID", "").isdigit():
                    allowed_owners.add(int(os.environ["SUDO_UID"]))
                if info.st_uid not in allowed_owners or stat.S_IMODE(info.st_mode) & 0o077:
                    raise InstallError("Credential source must be owned by root/the invoking user with mode 0600 or stricter.")
            elif real:
                raise InstallError("Real installation requires Linux file permissions.")
            content = source.read(16385)
            if len(content) > 16384:
                raise InstallError("Credential source exceeds the size limit.")
            return json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InstallError("Cannot read private credential JSON; contents will not be printed.") from None


def ensure_no_symlinks(path):
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise InstallError("Refusing a symlink in an installer-managed path.")


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Installer:
    def __init__(self, args):
        self.args = args
        self.target = args.target
        self.profile = render.resolve_profile(args.profile)
        self.storage_profile = render.storage_profile(args.profile)
        self.cores = ["xray", "caddy"] if self.profile == "vless" else ["hy2"]
        self.state = None
        self.log = None
        self.lock = None

    def run(self, command, *, check=True, env=None):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", env=env)
        if self.log:
            self.log.write(result.stdout)
            self.log.flush()
        if check and result.returncode:
            raise InstallError("A system command failed; inspect the root-only installation log.")
        return result

    def write_state(self):
        temporary = STATE / "state.next"
        ensure_no_symlinks(temporary)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(render.json_text(self.state))
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(MARKER)

    def inspect_platform(self):
        if sys.platform != "linux" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise InstallError("Real installation requires root on Ubuntu 22.04/24.04 LTS; use sudo bash admin/install-server.sh.")
        if sys.version_info < (3, 10):
            raise InstallError("Python 3.10+ is required (included in standard Ubuntu 22.04/24.04 images).")
        release = dict(line.strip().split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
        if release.get("ID", "").strip('"') != "ubuntu" or release.get("VERSION_ID", "").strip('"') not in ("22.04", "24.04"):
            raise InstallError("Only fresh Ubuntu 22.04 and 24.04 LTS are supported.")
        if platform.machine() not in ("x86_64", "amd64") or not Path("/run/systemd/system").is_dir():
            raise InstallError("An x86_64 machine booted with systemd is required.")
        for name in ("apt-get", "systemctl", "systemd-analyze", "ss", "useradd", "runuser"):
            if not shutil.which(name):
                raise InstallError(f"Required base-system tool is missing: {name}.")
        for root in (STATE, Path(render.CONFIG_ROOT), Path(render.OPT_ROOT), Path(render.DATA_ROOT), Path(render.CLIENT_ROOT), UNITS):
            ensure_no_symlinks(root)

    def existing_state(self):
        if not STATE.exists():
            return False
        info = STATE.stat()
        if not STATE.is_dir() or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise InstallError("Installer state directory must be owned by root with mode 0700; refusing to adopt it.")
        if not MARKER.exists():
            raise InstallError("Existing installer directory has no ownership marker; refusing to adopt it.")
        ensure_no_symlinks(MARKER)
        info = MARKER.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1048576:
            raise InstallError("Invalid root-only ownership marker.")
        try:
            self.state = json.loads(MARKER.read_text())
        except (ValueError, OSError):
            raise InstallError("Cannot read installer ownership state.") from None
        saved_target = self.state.get("target") if isinstance(self.state, dict) else None
        matches = False
        if isinstance(saved_target, dict) and saved_target.get("profile") in render.PROFILES:
            matches = {**saved_target, "profile": render.storage_profile(saved_target["profile"])} == {**self.target, "profile": render.storage_profile(self.profile)}
        if not isinstance(self.state, dict) or self.state.get("owner") != OWNER or not matches:
            raise InstallError("Existing installation has a different profile/hostname/IP/email or unknown owner; no changes made.")
        # Keep retry output/configuration byte-identical even if an alias was used.
        self.target = saved_target
        if self.state.get("status") not in ("installing", "complete") or any(not isinstance(self.state.get(key), dict) for key in ("files", "users", "directories")):
            raise InstallError("Installer ownership state has an invalid schema.")
        if self.state["status"] == "complete":
            expected = {str(STATE / "credentials.json")}
            expected.update(str(UNITS / f"personal-vpn-{core}.service") for core in self.cores)
            expected.update(str(Path(render.OPT_ROOT) / core / render.VERSIONS[core] / core) for core in self.cores)
            if not expected.issubset(self.state["files"]) or set(self.state["users"]) != set(self.cores):
                raise InstallError("Completed installation lacks required ownership records; refusing to modify it.")
        self.verify_owned()
        return True

    def managed_path(self, path):
        roots = [Path(render.CONFIG_ROOT), Path(render.OPT_ROOT), Path(render.CLIENT_ROOT)]
        exact = {STATE / "credentials.json"} | {UNITS / f"personal-vpn-{core}.service" for core in self.cores}
        return path in exact or any(root in path.parents for root in roots)

    def verify_owned(self):
        import pwd
        for name in self.state.get("users", []):
            try:
                account = pwd.getpwnam(name)
            except KeyError:
                raise InstallError("An installer-owned service account was removed; manual review is required.") from None
            if name not in self.cores or account.pw_uid != self.state["users"][name] or account.pw_shell != "/usr/sbin/nologin":
                raise InstallError("Service account identity changed; refusing to continue.")
        for raw_path, expected in self.state.get("files", {}).items():
            path = Path(raw_path)
            if not self.managed_path(path):
                raise InstallError("Ownership marker contains an unexpected path.")
            ensure_no_symlinks(path)
            try:
                info = path.stat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != expected["gid"]
                        or stat.S_IMODE(info.st_mode) != expected["mode"] or fingerprint(path) != expected["sha256"]):
                    raise InstallError("An owned file changed outside the installer; refusing to overwrite it.")
            except OSError:
                raise InstallError("An owned file is missing or unreadable; manual review is required.") from None
        for raw_path, expected in self.state.get("directories", {}).items():
            path = Path(raw_path)
            ensure_no_symlinks(path)
            try:
                info = path.stat()
                if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != tuple(expected):
                    raise InstallError("Owned directory permissions changed; refusing to continue.")
            except OSError:
                raise InstallError("An owned directory is missing; manual review is required.") from None

    def check_foreign(self):
        import pwd
        for directory in ("/etc/xray", "/etc/caddy", "/etc/hysteria", "/opt/hysteria", "/opt/ness-vpn-optimized", "/var/lib/hy2-deployment"):
            if Path(directory).exists() or Path(directory).is_symlink():
                raise InstallError("An existing VPN/web-server configuration was found; use a fresh server, not this installer.")
        for name in ("xray", "caddy", "hysteria-server", "hysteria", "v2ray", "ness-vpn-optimized", "nginx", "apache2"):
            result = self.run(["systemctl", "show", f"{name}.service", "--property=LoadState", "--value"], check=False)
            if result.stdout.strip() not in ("", "not-found"):
                raise InstallError("An existing VPN/web-server unit was found; refusing to replace or interfere with it.")
        for core in ("xray", "caddy", "hy2"):
            name = f"personal-vpn-{core}.service"
            path = UNITS / name
            owned = self.state and str(path) in self.state["files"]
            result = self.run(["systemctl", "show", name, "--property=LoadState", "--value"], check=False)
            if not owned and (path.exists() or path.is_symlink() or result.stdout.strip() not in ("", "not-found")):
                raise InstallError("An unowned personal-vpn systemd unit already exists.")
            for root in ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system"):
                dropin = Path(root) / (name + ".d")
                if dropin.exists() or dropin.is_symlink():
                    raise InstallError("Foreign systemd drop-ins exist for an installer service; refusing to continue.")
        for core in self.cores:
            try:
                pwd.getpwnam(core)
            except KeyError:
                continue
            if not self.state or core not in self.state["users"]:
                raise InstallError("A required service account already exists and is not installer-owned.")
        if not self.state:
            for root in (render.CONFIG_ROOT, render.OPT_ROOT, render.DATA_ROOT, render.CLIENT_ROOT):
                if Path(root).exists():
                    raise InstallError("An installer target directory already exists without ownership state.")

    def check_ports(self):
        import re
        allowed_pids = set()
        if self.state:
            for core in self.cores:
                if str(UNITS / f"personal-vpn-{core}.service") in self.state["files"]:
                    result = self.run(["systemctl", "show", f"personal-vpn-{core}.service", "--property=MainPID", "--value"], check=False)
                    if result.stdout.strip().isdigit() and int(result.stdout.strip()):
                        allowed_pids.add(int(result.stdout.strip()))
        ports = [80, 443, 39761] if self.profile == "vless" else [443]
        for transport in ("-t", "-u"):
            for port in ports:
                result = self.run(["ss", "-H", "-l", "-n", "-p", transport, f"sport = :{port}"])
                for line in result.stdout.splitlines():
                    pids = {int(value) for value in re.findall(r"pid=(\d+)", line)}
                    if not pids or not pids.issubset(allowed_pids):
                        raise InstallError(f"Required port {port} is already occupied by an unowned listener.")

    def check_dns(self):
        try:
            ipv4 = {row[4][0] for row in socket.getaddrinfo(self.target["domain"], 443, socket.AF_INET, socket.SOCK_STREAM)}
            if ipv4 != {self.target["public_ip"]}:
                raise InstallError("Hostname A resolution must equal only --public-ip (no CDN proxy); no changes made.")
            try:
                ipv6 = socket.getaddrinfo(self.target["domain"], 443, socket.AF_INET6, socket.SOCK_STREAM)
            except socket.gaierror as error:
                if error.errno not in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)):
                    raise
                ipv6 = []
            if ipv6:
                raise InstallError("AAAA resolution exists; remove it or use a separately reviewed IPv6 deployment.")
        except socket.gaierror:
            raise InstallError("DNS resolution failed; fix public A/AAAA records before installation.") from None

    def initialize(self):
        import fcntl
        if not self.state:
            # mkdir without exist_ok makes simultaneous first installs fail closed.
            STATE.mkdir(mode=0o700)
            self.state = {"owner": OWNER, "target": self.target, "status": "installing", "files": {}, "users": {}, "directories": {}}
            self.write_state()
        lock_path = STATE / "install.lock"
        ensure_no_symlinks(lock_path)
        self.lock = os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError("Another installer holds the host installation lock.") from None
        # Re-read after taking the lock; a concurrent installer may have finished.
        self.existing_state()
        log_path = STATE / "install.log"
        ensure_no_symlinks(log_path)
        self.log = os.fdopen(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600), "a")

    def make_directory(self, path, mode=0o750, uid=0, gid=0):
        path = Path(path)
        ensure_no_symlinks(path)
        if str(path) in self.state["directories"]:
            return
        if path.exists():
            raise InstallError("Refusing to adopt an unrecorded target directory.")
        path.mkdir(mode=mode)
        os.chown(path, uid, gid)
        os.chmod(path, mode)
        self.state["directories"][str(path)] = [uid, gid, mode]
        self.write_state()

    def put_file(self, path, data, mode=0o600, gid=0):
        path = Path(path)
        if isinstance(data, str):
            data = data.encode("utf-8")
        if str(path) in self.state["files"]:
            if fingerprint(path) != hashlib.sha256(data).hexdigest():
                raise InstallError("Generated configuration differs from the owned file; refusing to overwrite it.")
            return
        ensure_no_symlinks(path)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        except FileExistsError:
            raise InstallError("Refusing to overwrite an unrecorded target file.") from None
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            os.fchown(output.fileno(), 0, gid)
            os.fchmod(output.fileno(), mode)
        self.state["files"][str(path)] = {"sha256": hashlib.sha256(data).hexdigest(), "mode": mode, "gid": gid}
        self.write_state()

    def credentials(self):
        path = STATE / "credentials.json"
        requested = None
        if self.args.credentials_file:
            requested = render.validate_credentials(self.args.profile, private_source(self.args.credentials_file, True))
        if str(path) in self.state["files"]:
            saved = render.validate_credentials(self.args.profile, json.loads(path.read_text()))
            if requested is not None and requested != saved:
                raise InstallError("Migration credentials differ from this installation; refusing credential rotation.")
            return saved
        saved = requested if requested is not None else render.new_credentials(self.args.profile)
        self.put_file(path, render.json_text(saved))
        return saved

    def install_accounts(self):
        import pwd
        for core in self.cores:
            if core not in self.state["users"]:
                self.run(["useradd", "--system", "--user-group", "--home-dir", f"{render.DATA_ROOT}/{core}",
                          "--no-create-home", "--shell", "/usr/sbin/nologin", core])
                self.state["users"][core] = pwd.getpwnam(core).pw_uid
                self.write_state()

    def download_binary(self, core):
        release = RELEASES[core]
        destination = Path(render.OPT_ROOT) / core / render.VERSIONS[core] / core
        if str(destination) in self.state["files"]:
            return
        # The standard HTTPS context verifies certificates; never fall back to HTTP.
        request = urllib.request.Request(release["url"], headers={"User-Agent": "personal-vpn-installer/1"})
        try:
            with urllib.request.build_opener(HTTPSOnlyRedirect()).open(request, timeout=90) as response:
                if not response.url.startswith("https://"):
                    raise InstallError("Download redirected to an insecure transport.")
                data = response.read(128 * 1024 * 1024 + 1)
        except (OSError, ValueError):
            raise InstallError("Official binary download failed; retry after checking outbound HTTPS.") from None
        if len(data) > 128 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != release["sha256"]:
            raise InstallError("Official download SHA256 does not match the pinned release; nothing was executed.")
        try:
            if release["format"] == "zip":
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    info = archive.getinfo(release["member"])
                    if info.file_size > 128 * 1024 * 1024:
                        raise InstallError("Oversized release member.")
                    binary = archive.read(info)
            elif release["format"] == "tar":
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                    info = archive.getmember(release["member"])
                    if not info.isfile() or info.size > 128 * 1024 * 1024:
                        raise InstallError("Unexpected release member.")
                    binary = archive.extractfile(info).read()
            else:
                binary = data
        except (KeyError, ValueError, tarfile.TarError, zipfile.BadZipFile):
            raise InstallError("Pinned release archive has an unexpected structure.") from None
        if not binary.startswith(b"\x7fELF"):
            raise InstallError("Pinned release did not contain a Linux executable.")
        self.put_file(destination, binary, mode=0o755)

    def render_files(self, credentials):
        import pwd
        for root, mode in ((render.CONFIG_ROOT, 0o755), (render.OPT_ROOT, 0o755), (render.DATA_ROOT, 0o755), (render.CLIENT_ROOT, 0o700)):
            self.make_directory(root, mode)
        config_dir = Path(render.CONFIG_ROOT) / self.storage_profile
        self.make_directory(config_dir, 0o755 if self.profile == "vless" else 0o750,
                            gid=0 if self.profile == "vless" else pwd.getpwnam("hy2").pw_gid)
        client_dir = Path(render.CLIENT_ROOT) / self.storage_profile
        self.make_directory(client_dir, 0o700)
        for core in self.cores:
            account = pwd.getpwnam(core)
            self.make_directory(Path(render.OPT_ROOT) / core, 0o755)
            self.make_directory(Path(render.OPT_ROOT) / core / render.VERSIONS[core], 0o755)
            if core != "xray":
                self.make_directory(Path(render.DATA_ROOT) / core, 0o700, account.pw_uid, account.pw_gid)
            service_log = STATE / f"personal-vpn-{core}.log"
            ensure_no_symlinks(service_log)
            fd = os.open(service_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            self.download_binary(core)
            self.put_file(UNITS / f"personal-vpn-{core}.service", render.unit(core), mode=0o644)
        if self.profile == "vless":
            for core in ("xray", "caddy"):
                self.make_directory(config_dir / core, 0o750, gid=pwd.getpwnam(core).pw_gid)
            self.put_file(config_dir / "xray/config.json", render.json_text(render.xray_config(credentials)), mode=0o640, gid=pwd.getpwnam("xray").pw_gid)
            self.put_file(config_dir / "caddy/Caddyfile", render.caddy_config(self.target, credentials), mode=0o640, gid=pwd.getpwnam("caddy").pw_gid)
        else:
            self.put_file(config_dir / "config.json", render.json_text(render.hy2_config(self.target, credentials)), mode=0o640, gid=pwd.getpwnam("hy2").pw_gid)
        uri, client = render.client_config(self.target, credentials)
        self.put_file(client_dir / "client-uri.txt", uri)
        self.put_file(client_dir / "client.json", client)
        self.put_file(client_dir / "credentials.json", render.json_text(credentials))
        inventory = {"target": self.target, "versions": {core: render.VERSIONS[core] for core in self.cores},
                     "services": [f"personal-vpn-{core}.service" for core in self.cores]}
        self.put_file(client_dir / "inventory.json", render.json_text(inventory))

    def validate_configs(self):
        for core in self.cores:
            self.run(["systemd-analyze", "verify", str(UNITS / f"personal-vpn-{core}.service")])
        if self.profile == "vless":
            xray = f"{render.OPT_ROOT}/xray/{render.VERSIONS['xray']}/xray"
            self.run(["runuser", "-u", "xray", "--", xray, "run", "-test", "-config", f"{render.CONFIG_ROOT}/{self.storage_profile}/xray/config.json"])
            caddy = f"{render.OPT_ROOT}/caddy/{render.VERSIONS['caddy']}/caddy"
            env = dict(os.environ, HOME=f"{render.DATA_ROOT}/caddy", XDG_DATA_HOME=f"{render.DATA_ROOT}/caddy/data", XDG_CONFIG_HOME=f"{render.DATA_ROOT}/caddy/config")
            # validate provisions modules but does not start listeners or issue certificates.
            self.run(["runuser", "-u", "caddy", "--", caddy, "validate", "--config", f"{render.CONFIG_ROOT}/{self.storage_profile}/caddy/Caddyfile", "--adapter", "caddyfile"], env=env)
        # Hysteria2 has no native standalone config-check command. Its actual
        # startup below parses the config; do not invent a --check flag.

    def configure_firewall(self):
        if not shutil.which("ufw"):
            print("UFW is absent; no host firewall changes. Confirm cloud/other firewall rules separately.")
            return
        active = self.run(["ufw", "status"], env=dict(os.environ, LC_ALL="C")).stdout.startswith("Status: active")
        if not active:
            print("UFW is inactive; left inactive. No SSH or firewall-policy changes.")
            return
        if not self.args.configure_firewall:
            print("WARNING: UFW is active and unchanged; required VPN ports must already be allowed.")
            return
        ports = ["80/tcp", "443/tcp"] if self.profile == "vless" else ["443/tcp", "443/udp"]
        for port in ports:
            self.run(["ufw", "allow", "proto", port.split("/")[1], "from", "any", "to", "any", "port", port.split("/")[0], "comment", "personal-vpn"])
        print("Added VPN allow rules only; existing SSH rules and default firewall policy preserved.")

    def start(self):
        self.run(["systemctl", "daemon-reload"])
        for core in self.cores:
            self.run(["systemctl", "enable", f"personal-vpn-{core}.service"])
            self.run(["systemctl", "start", f"personal-vpn-{core}.service"])
        # An active process is not an authenticated forwarding/TLS acceptance test.
        # Also wait for UDP/TCP listeners so asynchronous ACME failures surface.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if all(self.run(["systemctl", "is-active", "--quiet", f"personal-vpn-{core}.service"], check=False).returncode == 0 for core in self.cores):
                transport = "-t" if self.profile == "vless" else "-u"
                listener = self.run(["ss", "-H", "-l", "-n", transport, "sport = :443"]).stdout.strip()
                if listener:
                    time.sleep(2)
                    if all(self.run(["systemctl", "is-active", "--quiet", f"personal-vpn-{core}.service"], check=False).returncode == 0 for core in self.cores):
                        return
            time.sleep(2)
        raise InstallError("Service did not stay active with its proxy listener within 120s; inspect private logs and ACME/DNS/firewall access.")

    def summary(self, existing=False):
        print("Already installed; credentials/configuration preserved; no restart or changes." if existing else "Installation finished; services active and proxy listener present.")
        for core in self.cores:
            active = self.run(["systemctl", "is-active", "--quiet", f"personal-vpn-{core}.service"], check=False).returncode == 0
            print(f"  personal-vpn-{core}.service: {'active' if active else 'NOT ACTIVE (left unchanged)'}")
        print(f"Private URI/config/credential files: {render.CLIENT_ROOT}/{self.storage_profile}/ (root only)")
        print(f"Private diagnostics: {STATE}/install.log and personal-vpn-*.log (do not publish)")
        print("Public inbound required: " + ("TCP 80 and TCP 443." if self.profile == "vless" else "UDP 443 and TCP 443 (ACME renewal)."))
        print("TLS/ACME may still be settling; authenticated browsing, invalid-auth rejection, renewal and reboot are not verified.")

    def install(self):
        self.inspect_platform()
        self.existing_state()
        if self.state and self.state["status"] == "complete":
            self.credentials()  # Reject a different explicit migration source, without rotation.
            self.summary(existing=True)
            return
        self.check_foreign()
        self.check_ports()
        print("Checking hostname resolution (A must match; no AAAA).")
        self.check_dns()
        self.initialize()
        if self.state["status"] == "complete":
            self.credentials()
            self.summary(existing=True)
            return
        self.check_foreign()
        self.check_ports()
        credentials = self.credentials()
        print("Installing prerequisite CA certificates and pinned official binaries; private logs retained on failure.")
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", NEEDRESTART_MODE="l")
        self.run(["apt-get", "update"], env=env)
        self.run(["apt-get", "install", "--yes", "--no-install-recommends", "ca-certificates"], env=env)
        self.install_accounts()
        self.render_files(credentials)
        print("Validating configuration and systemd units.")
        self.validate_configs()
        self.configure_firewall()
        print("Starting services; public ACME validation requires correct DNS and open cloud/host ports.")
        self.start()
        self.state["status"] = "complete"
        self.write_state()
        self.summary()


def main(argv=None):
    if sys.version_info < (3, 10):
        print("ERROR: Python 3.10+ is required.", file=sys.stderr)
        return 1
    installer = None
    try:
        args = parse_args(argv)
        if args.credentials_file:
            render.validate_credentials(args.profile, private_source(args.credentials_file, not args.dry_run))
        plan(args)
        if args.dry_run:
            print("DRY RUN: inputs valid. No root check, DNS lookup, download, credentials generated, or host changes.")
            return 0
        if not args.yes:
            if not sys.stdin.isatty() or input("Install on this fresh server and accept ACME CA terms? Type yes: ").strip() != "yes":
                raise InstallError("Installation cancelled; pass --yes only after reviewing the documented changes and ACME terms.")
        os.umask(0o077)
        installer = Installer(args)
        installer.install()
        return 0
    except (InstallError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError):
        # Do not expose arbitrary subprocess/config exceptions containing secrets.
        print("ERROR: Installation stopped safely; inspect root-only state/logs. No automatic deletion or rollback was attempted.", file=sys.stderr)
        return 1
    finally:
        if installer:
            if installer.log:
                installer.log.close()
            if installer.lock:
                installer.lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
