"""Starts everything the project needs, from one command.

    python scripts/dev.py

Five processes: the API, the Vite dev server, the Telegram bot, the public
tunnel, and Stripe's webhook forwarder. Started in the right order, reported
under one prefix each, and - the part that took the most care - stopped
together, for good, when this exits.

Three problems this exists to solve, each of which cost real time first.

**Orphans.** On Windows, killing a process does not kill what it started.
uvicorn's reloader leaves its worker; `npx localtunnel` leaves the node
process that holds the subdomain. The result is a port that is still busy
and a subdomain that is taken, so the next run silently comes up on a random
address while everything else still points at the old one. Everything
started here goes into a Job Object with KILL_ON_JOB_CLOSE, so when this
process ends - cleanly, by Ctrl+C, or killed outright - the whole tree goes
with it. Anything left over from a previous run is cleared before starting.

**Order.** The tunnel attaches to the API's port. Start it first and it
answers 503 until somebody notices and restarts it, so this waits for the
port to actually accept a connection before the tunnel is launched.

**Silent misconfiguration.** A service that starts and cannot work is worse
than one that does not start: Stripe forwarding with an expired CLI login
looks identical to a working one until a payment goes missing. Everything
checkable is checked first and said plainly, and a service that cannot work
is skipped with a reason rather than started to fail quietly.
"""
from __future__ import annotations

import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = platform.system() == "Windows"

API_HOST = "127.0.0.1"
API_PORT = 8000
WEB_PORT = 5173
WEBHOOK_PATH = "/api/billing/webhook"

# How long to wait for the API to start listening before giving up on the
# things that depend on it. Generous: a cold start imports SQLAlchemy, the
# Google client and Stripe, which is slow on a laptop that has been idle.
API_WAIT_SECONDS = 90


# ------------------------------------------------------------------
# Output
#
# One colour per service, so five interleaved logs can still be read. Colours
# are skipped when the output is redirected, where escape codes are noise in
# a file rather than colour on a screen.
# ------------------------------------------------------------------
COLOURS = {
    "api": "\033[36m",
    "web": "\033[35m",
    "bot": "\033[32m",
    "tunnel": "\033[33m",
    "stripe": "\033[34m",
    "dev": "\033[90m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
_USE_COLOUR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _paint(text: str, colour: str) -> str:
    return f"{colour}{text}{RESET}" if _USE_COLOUR else text


def which(name: str) -> str | None:
    """Where a tool actually lives, in a form Windows can start.

    shutil.which alone is not enough here. npm, npx and stripe ship two
    files side by side - an extension-less shell script for Unix shells and
    a .cmd for Windows - and which one comes back depends on PATHEXT, which
    Git Bash changes. Getting the shell script is how you end up with
    "WinError 193: not a valid Win32 application", an error that reads like
    a corrupt binary and is really the wrong one of two files.

    So the extension is asked for explicitly rather than left to the
    environment.
    """
    if IS_WINDOWS:
        for extension in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + extension)
            if found:
                return found
    return shutil.which(name)


def runnable(args: list[str]) -> list[str]:
    """A command line CreateProcess will actually accept.

    npm, npx and stripe are installed as .CMD shims on Windows, and those
    are scripts rather than executables - handing one to CreateProcess gets
    "WinError 193: not a valid Win32 application", which reads like a
    corrupt binary and is really a missing interpreter. cmd.exe is that
    interpreter.

    Resolved through an absolute path, so a cmd.exe left in the working
    directory cannot stand in for the real one.
    """
    if not IS_WINDOWS or not args:
        return args
    if args[0].lower().endswith((".cmd", ".bat")):
        cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
        return [str(cmd), "/c", *args]
    return args


_print_lock = threading.Lock()


def say(name: str, message: str) -> None:
    """One line of output, tagged with which service it came from."""
    tag = _paint(f"{name:>6} |", COLOURS.get(name, ""))
    with _print_lock:
        print(f"{tag} {message}", flush=True)


def headline(message: str) -> None:
    with _print_lock:
        print(_paint(message, BOLD), flush=True)


# ------------------------------------------------------------------
# Making sure nothing survives us
# ------------------------------------------------------------------
def _make_job_object():
    """A Windows Job Object that kills everything in it when we exit.

    Processes started by a process already in a job join that job by
    default, so this covers grandchildren - which is the whole point, since
    the leaks are all grandchildren: uvicorn's reloader worker, npm's node,
    npx's node. Closing the handle, including because this process was
    killed outright, terminates the lot.

    Returns None off Windows, where a process group and SIGTERM already do
    the job.
    """
    if not IS_WINDOWS:
        return None

    import ctypes
    from ctypes import wintypes

    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.POINTER(wintypes.ULONG)),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation,
        ctypes.byref(info), ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return job


def _adopt(job, process: subprocess.Popen) -> None:
    """Puts a process into the job, so it cannot outlive us."""
    if job is None:
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
    handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, process.pid)
    if not handle:
        return
    try:
        kernel32.AssignProcessToJobObject(job, handle)
    finally:
        kernel32.CloseHandle(handle)


# ------------------------------------------------------------------
# Clearing the way
# ------------------------------------------------------------------
def _port_busy(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex((API_HOST, port)) == 0


def _pids_on_port(port: int) -> list[int]:
    if not IS_WINDOWS:
        return []
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=20
        ).stdout
    except Exception:
        return []
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
            if parts[1].endswith(f":{port}"):
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    pass
    return sorted(pids)


def _kill_tree(pid: int) -> None:
    """Kills a process and everything under it.

    /T is the point - without it the grandchildren survive and keep holding
    whatever the parent was holding. Resolved through an absolute path so a
    taskkill.exe sitting in the working directory cannot stand in for it.
    """
    if IS_WINDOWS:
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        subprocess.run(
            [str(taskkill), "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=30,
        )
    else:
        os.kill(pid, signal.SIGKILL)


def _stray_tunnels() -> list[int]:
    """localtunnel processes from an earlier run.

    They matter more than they look: while one is alive it holds the
    subdomain, and the next run is quietly given a random address instead
    while MINIAPP_URL, the bot's links and Google's redirect URIs all still
    point at the old one.
    """
    if not IS_WINDOWS:
        return []
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='node.exe'", "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        if "localtunnel" in line or "--subdomain" in line:
            parts = [p for p in line.strip().split(",") if p]
            if parts and parts[-1].isdigit():
                pids.append(int(parts[-1]))
    return pids


def clear_leftovers() -> None:
    """Whatever a previous run left holding a port or the subdomain."""
    cleared = []
    for label, port in (("api", API_PORT), ("web", WEB_PORT)):
        for pid in _pids_on_port(port):
            _kill_tree(pid)
            cleared.append(f"{label} on {port} (pid {pid})")
    for pid in _stray_tunnels():
        _kill_tree(pid)
        cleared.append(f"tunnel (pid {pid})")

    if cleared:
        say("dev", "cleared from a previous run: " + ", ".join(cleared))
        time.sleep(2)


# ------------------------------------------------------------------
# Preflight
# ------------------------------------------------------------------
def _env() -> dict:
    from dotenv import dotenv_values

    return dotenv_values(ROOT / ".env")


def _subdomain(env: dict) -> str | None:
    """The tunnel subdomain, taken from MINIAPP_URL rather than hardcoded.

    They have to agree: the bot's dashboard links, Google's redirect URIs and
    Telegram's Mini App URL are all built from MINIAPP_URL, so a tunnel on a
    different address is a tunnel nothing points at.
    """
    url = (env.get("MINIAPP_URL") or "").strip()
    if not url:
        return None
    host = urlparse(url).hostname or ""
    return host.split(".")[0] if host.endswith(".loca.lt") else None


def _stripe_reason(stderr: str | None) -> str:
    """The CLI's complaint, in one readable line.

    Its failures arrive as a sentence followed by a pretty-printed JSON
    body, so taking the first line that merely contains "error" gets you
    `"error": {` - a fragment of punctuation presented as a diagnosis. The
    useful part is either the summary line or the message inside the body.
    """
    lines = [l.strip() for l in (stderr or "").splitlines() if l.strip()]
    for line in lines:
        if '"message"' in line:
            return line.split('"message"', 1)[1].strip(' :",').rstrip('",')[:70]
    for line in lines:
        if "Authorization failed" in line or "not logged in" in line or "no API key" in line:
            return line[:70]
    return lines[0][:70] if lines else "not signed in"


def preflight(env: dict) -> dict:
    """What is missing, and what that means. Returns which services can run."""
    problems: list[str] = []
    can = {"api": True, "web": True, "bot": True, "tunnel": True, "stripe": True}

    python = ROOT / ".venv" / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python")
    if not python.exists():
        problems.append("no .venv - run: python -m venv .venv && .venv/Scripts/pip install -r requirements.txt")
        can["api"] = can["bot"] = False

    if not (ROOT / "frontend" / "node_modules").exists():
        problems.append("frontend/node_modules missing - run: cd frontend && npm install")
        can["web"] = False

    if not (env.get("TELEGRAM_BOT_TOKEN") or "").strip():
        problems.append("TELEGRAM_BOT_TOKEN is empty - the bot cannot start")
        can["bot"] = False

    if not _subdomain(env):
        problems.append(
            "MINIAPP_URL is not a *.loca.lt address, so the tunnel has no subdomain to claim"
        )
        can["tunnel"] = False

    # Stripe is the one that fails silently, so it gets the closest look: a
    # forwarder running against an expired login looks exactly like a working
    # one until a payment goes missing.
    stripe_cli = which("stripe")
    if not stripe_cli:
        problems.append("stripe CLI not on PATH - webhooks will not be forwarded")
        can["stripe"] = False
    else:
        try:
            probe = subprocess.run(
                runnable([stripe_cli, "listen", "--print-secret"]),
                capture_output=True, text=True, timeout=60,
            )
            printed = next(
                (l.strip() for l in (probe.stdout or "").splitlines() if l.strip().startswith("whsec_")),
                "",
            )
            if not printed:
                problems.append(
                    f"stripe CLI cannot reach your account ({_stripe_reason(probe.stderr)}) - run: stripe login"
                )
                can["stripe"] = False
            elif printed != (env.get("STRIPE_WEBHOOK_SECRET") or "").strip():
                problems.append(
                    "STRIPE_WEBHOOK_SECRET in .env is not the one `stripe listen` uses, so forwarded "
                    "events will fail signature checks - copy the secret the forwarder prints into .env"
                )
        except Exception as e:  # noqa: BLE001 - reported, not swallowed
            problems.append(f"could not ask the stripe CLI ({type(e).__name__}) - webhooks unchecked")

    if problems:
        headline("\nBefore we start:")
        for p in problems:
            say("dev", p)
        headline("")
    return can


# ------------------------------------------------------------------
# Running
# ------------------------------------------------------------------
class Service:
    def __init__(self, name: str, args: list[str], cwd: Path):
        self.name, self.args, self.cwd = name, args, cwd
        self.process: subprocess.Popen | None = None

    def start(self, job) -> None:
        creation = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        self.process = subprocess.Popen(
            runnable(self.args),
            cwd=str(self.cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            creationflags=creation,
            # A group of its own off Windows, so one signal reaches the whole
            # thing rather than only the shell in front of it.
            start_new_session=not IS_WINDOWS,
        )
        _adopt(job, self.process)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            line = line.rstrip()
            if line:
                say(self.name, line)
        code = self.process.wait()
        if code not in (0, None):
            say(self.name, f"exited with code {code}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                _kill_tree(self.process.pid)
            except Exception:
                pass


def wait_for_api() -> bool:
    say("dev", f"waiting for the API on {API_HOST}:{API_PORT} ...")
    deadline = time.time() + API_WAIT_SECONDS
    while time.time() < deadline:
        if _port_busy(API_PORT):
            say("dev", "API is listening")
            return True
        time.sleep(0.5)
    say("dev", f"the API did not come up within {API_WAIT_SECONDS}s")
    return False


def main() -> int:
    env = _env()
    can = preflight(env)

    if not can["api"]:
        say("dev", "cannot start without the API - fix the above and try again")
        return 1

    clear_leftovers()

    python = ROOT / ".venv" / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python")
    npm = which("npm") or "npm"
    npx = which("npx") or "npx"
    stripe_cli = which("stripe")

    job = _make_job_object()
    if IS_WINDOWS and job is None:
        say("dev", "could not create a job object - stray processes may survive a hard kill")

    services: list[Service] = []

    def launch(service: Service) -> None:
        say("dev", f"starting {service.name}")
        service.start(job)
        services.append(service)

    try:
        launch(Service("api", [
            str(python), "-m", "uvicorn", "miniapp.api:app",
            "--host", API_HOST, "--port", str(API_PORT),
        ], ROOT))

        if not wait_for_api():
            return 1

        if can["web"]:
            launch(Service("web", [npm, "run", "dev"], ROOT / "frontend"))
        if can["bot"]:
            launch(Service("bot", [str(python), "bot.py"], ROOT))
        if can["tunnel"]:
            launch(Service("tunnel", [
                npx, "--yes", "localtunnel",
                "--port", str(API_PORT), "--subdomain", _subdomain(env) or "",
            ], ROOT))
        if can["stripe"] and stripe_cli:
            launch(Service("stripe", [
                stripe_cli, "listen",
                "--forward-to", f"http://{API_HOST}:{API_PORT}{WEBHOOK_PATH}",
            ], ROOT))

        headline("\nRunning. Ctrl+C stops everything.\n")
        for name, url in (
            ("dashboard", f"http://localhost:{WEB_PORT}"),
            ("api", f"http://{API_HOST}:{API_PORT}"),
            ("public", (env.get("MINIAPP_URL") or "not set").strip()),
        ):
            say("dev", f"{name:<10} {url}")
        headline("")

        while True:
            time.sleep(0.5)
            if services[0].process and services[0].process.poll() is not None:
                say("dev", "the API stopped - shutting the rest down")
                return 1

    except KeyboardInterrupt:
        headline("\nstopping ...")
        return 0
    finally:
        for service in reversed(services):
            service.stop()
        # Closing the job handle is the belt to that braces: anything the
        # loop above missed, or that was started by something we started,
        # dies here.
        if job is not None:
            import ctypes

            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)


if __name__ == "__main__":
    sys.exit(main())
