"""
temp_cleaner plugin — "clear my temp files", "clean prefetch", "how much junk do I have?"

Windows only. Runs ONLY when asked (the tool description tells Gemini never to call it
on its own). It deletes the CONTENTS of three folders, never the folders themselves:
    %TEMP%             your user temp folder
    C:\\Windows\\Temp    system temp (full clean needs administrator rights)
    C:\\Windows\\Prefetch  Windows' app-launch cache (needs administrator rights)

Why it deletes directly instead of pressing Ctrl+A / Ctrl+D in File Explorer:
  * Ctrl+D sends files to the Recycle Bin, so no disk space is freed and the bin fills up.
  * Explorer stops and asks about every file that is in use; this skips them and moves on.
  * It needs no window, focus or mouse, and it can tell you exactly what it freed.

Safety
  * A folder is only touched if its name is Temp / Tmp / Prefetch and it is not a drive root,
    so a mis-set %TEMP% (say, C:\\) can never wipe anything important.
  * Junctions and symlinks are removed as links and NEVER followed into their target.
  * Files that are in use are skipped, not forced.
  * 'scan' shows what would go and deletes nothing.
"""
import ctypes
import os
import platform
import shutil
import stat
import time

PLUGIN = {
    "name": "temp_cleaner",
    "description": (
        "Clears Windows junk: the user %TEMP% folder, C:\\Windows\\Temp and C:\\Windows\\Prefetch. "
        "Use ONLY when the user explicitly asks to clear / clean / delete temp files, temporary files, "
        "%temp%, or prefetch ('clear my temp', 'clean the prefetch', 'free up space from temp'). "
        "NEVER call it on your own, as a suggestion, or on a schedule. "
        "action='scan' only reports how much there is and deletes nothing (use for 'how much junk do I have?'); "
        "action='clean' deletes. targets is optional: 'all' (default), 'user temp', 'windows temp', or 'prefetch'. "
        "This is permanent deletion, not the Recycle Bin."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "scan | clean"},
            "targets": {"type": "STRING", "description": "all | user temp | windows temp | prefetch (default all)"},
        },
        "required": ["action"],
    },
}

_OS = platform.system()
_TIME_BUDGET = 90.0          # seconds; report what was done if a huge folder runs long
_REPARSE = 0x400             # FILE_ATTRIBUTE_REPARSE_POINT (junctions, symlinks)
_SAFE_NAMES = {"temp", "tmp", "prefetch"}
_LABELS = {"user_temp": "your Temp folder", "windows_temp": "Windows Temp", "prefetch": "Prefetch"}


# ── helpers ─────────────────────────────────────────────────────────────────

def _targets() -> dict:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    t = {}
    ut = os.environ.get("TEMP") or os.environ.get("TMP")
    if ut:
        t["user_temp"] = ut
    t["windows_temp"] = os.path.join(root, "Temp")
    t["prefetch"] = os.path.join(root, "Prefetch")
    return t


def _admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _is_safe_target(path: str) -> bool:
    p = os.path.normpath(path)
    _, tail = os.path.splitdrive(p)
    if not tail.strip("\\/"):
        return False                      # a drive root
    return os.path.basename(p).lower() in _SAFE_NAMES


def _is_link(st) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _pick(spec) -> list:
    s = str(spec or "all").lower().strip()
    allt = ["user_temp", "windows_temp", "prefetch"]
    if s in ("", "all", "everything", "both"):
        return allt
    chosen = []
    if "user" in s or "%temp%" in s or "appdata" in s:
        chosen.append("user_temp")
    if "windows" in s and "temp" in s:
        chosen.append("windows_temp")
    if "prefetch" in s:
        chosen.append("prefetch")
    if not chosen and "temp" in s:
        chosen = ["user_temp", "windows_temp"]
    return chosen or allt


def _files(n: int) -> str:
    return f"{n} file" + ("" if n == 1 else "s")


def _human(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} bytes" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class _Stats:
    def __init__(self):
        self.files = 0
        self.bytes = 0
        self.skipped = 0
        self.timed_out = False


# ── scan / clean ────────────────────────────────────────────────────────────

def _measure(path: str, stats: _Stats, deadline: float) -> None:
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            stats.timed_out = True
            return
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _is_link(st):
                    stats.files += 1                  # the link itself, never its target
                elif stat.S_ISDIR(st.st_mode):
                    stack.append(e.path)
                else:
                    stats.files += 1
                    stats.bytes += st.st_size


def _remove_file(path: str, size: int, stats: _Stats) -> None:
    try:
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)             # read-only attribute
            os.remove(path)
        stats.files += 1
        stats.bytes += size
    except OSError:
        stats.skipped += 1                            # in use or protected: leave it


def _clean_dir(path: str, stats: _Stats, deadline: float) -> None:
    try:
        entries = list(os.scandir(path))
    except OSError:
        stats.skipped += 1
        return
    for e in entries:
        if time.monotonic() > deadline:
            stats.timed_out = True
            return
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            stats.skipped += 1
            continue
        if _is_link(st):
            try:                                      # remove the link, never follow it
                try:
                    os.unlink(e.path)
                except OSError:
                    os.rmdir(e.path)
                stats.files += 1
            except OSError:
                stats.skipped += 1
        elif stat.S_ISDIR(st.st_mode):
            _clean_dir(e.path, stats, deadline)
            try:
                os.rmdir(e.path)                      # only succeeds once it is empty
            except OSError:
                pass
        else:
            _remove_file(e.path, st.st_size, stats)


# ── entry point ─────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).lower().strip()
    try:
        if _OS != "Windows":
            return "Sir, temp_cleaner only works on Windows."
        if action not in ("scan", "clean"):
            return "Sir, temp_cleaner needs an action: scan or clean."

        targets = _targets()
        admin = _admin()
        deadline = time.monotonic() + _TIME_BUDGET
        total = _Stats()
        notes: list = []
        touched = 0

        for name in _pick(parameters.get("targets")):
            label = _LABELS[name]
            path = targets.get(name)
            if not path or not os.path.isdir(path):
                notes.append(f"I couldn't find {label}")
                continue
            if not _is_safe_target(path):
                notes.append(f"I won't touch {path}, it doesn't look like a temp folder")
                continue
            try:
                os.listdir(path)
            except PermissionError:
                notes.append(f"{label} needs administrator rights")
                continue

            touched += 1
            if action == "scan":
                _measure(path, total, deadline)
            else:
                _clean_dir(path, total, deadline)

        if not admin and any(n in _pick(parameters.get("targets")) for n in ("windows_temp", "prefetch")):
            notes.append("Start JARVIS as administrator to clear Windows Temp and Prefetch fully")

        if action == "scan":
            msg = (f"Sir, there are {_files(total.files)} of junk using {_human(total.bytes)}. "
                   f"Say clean to delete them.")
        else:
            msg = f"Sir, I deleted {_files(total.files)} and freed {_human(total.bytes)}."
            if total.skipped:
                msg += f" {total.skipped} items were in use and skipped."
        if total.timed_out:
            msg += " That folder is huge, so I stopped partway. Run it again to continue."
        if notes:
            msg += " " + ". ".join(dict.fromkeys(notes)) + "."
        if touched == 0:
            msg = "Sir, " + (". ".join(dict.fromkeys(notes)) + "." if notes else "I found nothing to clean.")

        if player:
            try:
                player.write_log(f"JARVIS: {msg}")
            except Exception:
                pass
        return msg
    except Exception as e:
        return f"Sir, temp_cleaner failed: {e}"
