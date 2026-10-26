"""Own one isolated Chrome/Edge process tree; never touch an existing browser."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import platform
import signal
import subprocess
import time

from vpn import stop_child
from vpn_common import CleanupError, ClientError, private_directory


def browser_path(system: str | None = None) -> Path:
    system = system or platform.system()
    if system == "Windows":
        bases = [Path(base) for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")) if base]
        candidates = [base / relative for relative in (
            "Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe",
        ) for base in bases]
    elif system == "Darwin":
        candidates = [base / relative for relative in (
            "Google Chrome.app/Contents/MacOS/Google Chrome", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ) for base in (Path("/Applications"), Path.home() / "Applications")]
    else:
        raise ClientError("The separate browser supports Windows and macOS only.")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ClientError("Chrome or Edge was not found. Install either browser to open it automatically next time.")


def command_for(browser: Path, private: Path, proxy_port: int) -> list[str]:
    if not 1 <= proxy_port <= 65535:
        raise ClientError("Proxy port must be between 1 and 65535.")
    return [str(browser), f"--user-data-dir={private}", f"--proxy-server=http://127.0.0.1:{proxy_port}",
            "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-background-mode",
            "--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--new-window", "about:blank"]


class WindowsJob:
    """A kill-on-close job contains only the browser launched by this session."""

    def __init__(self):
        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                        ("max_working_set", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.kernel.QueryInformationJobObject.restype = wintypes.BOOL
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ClientError("Cannot create an isolated browser process group.")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ClientError("Cannot protect the browser process group.")

    def attach_and_resume(self, child) -> None:
        if not self.kernel.AssignProcessToJobObject(self.handle, int(child._handle)):
            raise ClientError("Cannot isolate this browser; local proxies remain available.")
        # Start suspended so no browser descendants can escape before job assignment.
        resume = ctypes.WinDLL("ntdll").NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = ctypes.c_long
        if resume(int(child._handle)) < 0:
            raise ClientError("Cannot start the isolated browser.")

    def close(self) -> None:
        if not self.handle:
            return
        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_uint64 * 4), ("page_faults", wintypes.DWORD),
                        ("total_processes", wintypes.DWORD), ("active_processes", wintypes.DWORD),
                        ("terminated_processes", wintypes.DWORD)]
        try:
            if not self.kernel.TerminateJobObject(self.handle, 0):
                raise CleanupError("Cannot stop the isolated browser process group; cleanup did not complete.")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                info = Accounting()
                if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                    raise CleanupError("Cannot verify isolated browser shutdown; cleanup did not complete.")
                if info.active_processes == 0:
                    return
                time.sleep(0.05)
            raise CleanupError("Isolated browser shutdown timed out; cleanup did not complete.")
        finally:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def stop_browser(child, job: WindowsJob | None) -> None:
    if job is not None:
        try:
            job.close()
        finally:
            stop_child(child)
        return
    # Chrome helpers inherit the new session's process group, not the user's group.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    stop_child(child)


@contextmanager
def running_browser(proxy_port: int):
    executable = browser_path()
    with private_directory() as directory:
        job = WindowsJob() if os.name == "nt" else None
        child = None
        try:
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | 0x4} if job else {"start_new_session": True}
            child = subprocess.Popen(command_for(executable, directory, proxy_port), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
            if job:
                job.attach_and_resume(child)
            yield child
        finally:
            if child is not None:
                stop_browser(child, job)
            elif job is not None:
                job.close()
