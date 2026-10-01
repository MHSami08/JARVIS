"""
manage_file_access — let JARVIS work outside your home folder (D: drive, a Data
folder, an external disk) without weakening the safety check.

WHY THIS EXISTS
    actions/file_controller.py only allows paths inside your home folder. A drive
    such as D:\\ is outside it, so every request there came back "Access denied" —
    and no Windows permission change can fix that, because the block is in JARVIS,
    not in Windows.

HOW IT STAYS SAFE
    * Granting a folder is NEVER done by the model alone. `add` parks the change
      behind the on-screen CONFIRM / CANCEL banner (core/confirm.py), exactly like
      shutdown. Only your button press writes it to config.
    * Folders are stored in config/api_keys.json under "file_access_roots".
      Removing one is instant — it only ever reduces access.
    * Refused outright: the system drive root (C:\\), Windows, Program Files,
      ProgramData and, on Linux/macOS, / /etc /usr /bin /sbin /boot /sys /proc /dev.
    * A granted folder itself can never be deleted by JARVIS.

VOICE EXAMPLES
    "Give yourself access to my D drive"        -> add  D:\\
    "Allow the Data folder on D"                -> add  Data  (found on your drives)
    "Which folders can you access?"             -> list
    "Show my drives"                            -> drives
    "Stop accessing the D drive"                -> remove
"""

import os
import platform
import re
import shutil
import string
from pathlib import Path

PLUGIN = {
    "name": "manage_file_access",
    "description": (
        "Lists, grants or revokes JARVIS's access to folders and drives OUTSIDE the "
        "home folder (e.g. the D: drive or a Data folder). Use it when the user asks "
        "to access/open/read files on another drive, or when file_controller answers "
        "'Access denied'. action: 'list' (granted folders), 'drives' (drives on this "
        "PC with free space), 'add' (path = 'D:\\\\', 'D:\\\\Data' or just a folder "
        "name like 'Data'), 'remove' (path). 'add' shows a CONFIRM button the user "
        "must press — never claim access was granted until they do."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list | drives | add | remove"},
            "path": {
                "type": "STRING",
                "description": "Drive or folder: 'D:\\\\', 'D:\\\\Data', 'd drive', or a folder name like 'Data'",
            },
        },
        "required": ["action"],
    },
}

_CONFIG_KEY = "file_access_roots"
_WIN = platform.system() == "Windows"


# ── config ────────────────────────────────────────────────────────────────────
def _load() -> list[str]:
    try:
        from memory.config_manager import load_api_keys
        return [str(r) for r in (load_api_keys().get(_CONFIG_KEY) or [])]
    except Exception:
        return []


def _save(roots: list[str]) -> None:
    from memory.config_manager import _patch_config
    _patch_config(**{_CONFIG_KEY: roots})


# ── safety ────────────────────────────────────────────────────────────────────
def _blocked_reason(p: Path) -> str:
    """'' if the folder may be granted, else a plain-English reason."""
    try:
        r = p.resolve()
    except Exception:
        return "that path cannot be resolved"

    if _WIN:
        sysdrive = os.environ.get("SystemDrive", "C:").rstrip("\\/") + "\\"
        if str(r).lower() == sysdrive.lower():
            return f"the system drive {sysdrive} holds Windows itself — grant a folder on it instead"
        for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            v = os.environ.get(var)
            if v:
                b = Path(v).resolve()
                if r == b or r.is_relative_to(b):
                    return f"{b} is a protected system location"
    else:
        for b in ("/", "/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc", "/dev", "/var"):
            bp = Path(b)
            if r == bp or (b != "/" and r.is_relative_to(bp)):
                return f"{b} is a protected system location"
    return ""


# ── finding the folder the user means ─────────────────────────────────────────
def _drives() -> list[Path]:
    if _WIN:
        return [Path(f"{c}:\\") for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
    found = [Path("/")]
    for base in ("/mnt", "/media", "/Volumes"):
        b = Path(base)
        if b.is_dir():
            found += [d for d in b.iterdir() if d.is_dir()]
    return found


def _locate(spoken: str) -> tuple[Path | None, str]:
    """Turn what the user said into a real folder. Returns (path, problem)."""
    raw = (spoken or "").strip().strip('"').strip("'")
    if not raw:
        return None, "Which folder or drive?"

    # "d", "d:", "D drive", "d:\"  ->  D:\
    m = re.fullmatch(r"([a-zA-Z])\s*(?::|\s+drive|:\s*drive)?\s*[\\/]?", raw)
    if _WIN and m:
        raw = f"{m.group(1).upper()}:\\"

    p = Path(raw).expanduser()
    if p.is_absolute() or p.drive:
        return (p, "") if p.is_dir() else (None, f"I can't find a folder at {p}.")

    # A bare name such as "Data": look for it at the top level of every drive.
    hits = []
    for d in _drives():
        try:
            for child in d.iterdir():
                if child.is_dir() and child.name.lower() == raw.lower():
                    hits.append(child)
        except Exception:
            continue
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"I couldn't find a top-level folder called '{raw}' on any drive. Give me the full path."
    return None, ("There is more than one: " + ", ".join(str(h) for h in hits)
                  + ". Tell me which one.")


def _same(a: str, b: str) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except Exception:
        return a.lower() == b.lower()


# ── actions ───────────────────────────────────────────────────────────────────
def _list() -> str:
    roots = _load()
    home = Path.home()
    if not roots:
        return (f"I can access your home folder ({home}) only. "
                "Ask me to add a drive or folder if you want more.")
    return (f"I can access your home folder ({home}) and: "
            + "; ".join(roots) + ".")


def _show_drives() -> str:
    lines = []
    for d in _drives():
        try:
            u = shutil.disk_usage(d)
            lines.append(f"{d}  {u.free / 1e9:.0f} GB free of {u.total / 1e9:.0f} GB")
        except Exception:
            lines.append(f"{d}  (not ready)")
    return "Drives on this PC:\n" + "\n".join(lines) if lines else "No drives found."


def _add(spoken: str) -> str:
    target, problem = _locate(spoken)
    if target is None:
        return problem
    target = target.resolve()

    why = _blocked_reason(target)
    if why:
        return f"I won't take access to {target}: {why}."

    if target == Path.home().resolve() or target.is_relative_to(Path.home().resolve()):
        return f"{target} is inside your home folder, so I can already use it."
    for existing in _load():
        try:
            if target == Path(existing).resolve() or target.is_relative_to(Path(existing).resolve()):
                return f"I already have access to {existing}, which covers {target}."
        except Exception:
            continue

    def _grant() -> str:
        roots = _load()
        if not any(_same(r, str(target)) for r in roots):
            roots.append(str(target))
            _save(roots)
        return f"Access granted to {target}."

    from core import confirm
    return confirm.request(
        key="file_access_add",
        title=f"Allow file access to {target}",
        detail=(f"JARVIS will be able to list, read, write, move, copy, rename and "
                f"delete (to the Recycle Bin) files inside {target}. "
                f"You can revoke this any time by asking, or by removing it from "
                f"'{_CONFIG_KEY}' in config/api_keys.json."),
        run=_grant,
    )


def _remove(spoken: str) -> str:
    roots = _load()
    if not roots:
        return "No extra folders are granted, so there is nothing to remove."
    target, _ = _locate(spoken)
    keep = [r for r in roots
            if not ((target is not None and _same(r, str(target)))
                    or r.lower() == (spoken or "").strip().lower())]
    if len(keep) == len(roots):
        return "That folder isn't in my access list. Currently: " + "; ".join(roots) + "."
    _save(keep)
    return f"Done — I no longer have access to {spoken}."


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        action = str(parameters.get("action", "")).lower().strip()
        path = str(parameters.get("path", "") or "")
        if action == "list":
            return _list()
        if action == "drives":
            return _show_drives()
        if action == "add":
            return _add(path)
        if action == "remove":
            return _remove(path)
        return "Use action: list, drives, add or remove."
    except Exception as e:
        return f"Sir, manage_file_access failed: {e}"
