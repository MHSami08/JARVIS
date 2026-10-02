"""
file_navigator plugin — "take me to that file", "open it", "change X to Y in it".

What it does
  drives    list the drives / volumes (with labels, e.g. D:\\ "Data")
  find      search by name across one drive, all drives, or inside a folder
  navigate  find the best match and SHOW it in File Explorer / Finder (file is selected)
  pick      choose from a numbered list when several files match
  open      open a file with its default app (or a folder in the file manager)
  read      read a text file (all of it, or a line range)
  edit      change a text file: replace / append / prepend / overwrite
  restore   undo the last edit of a file (every edit makes a backup first)

Safety
  * Every edit backs the file up first to ~/.jarvis_backups/  -> "restore" undoes it.
  * System folders (Windows, Program Files, /etc, /usr ...) can never be edited.
  * Secrets (api_keys.json, .env, SSH keys, *.pem, *.key, *.kdbx) can't be read or edited.
  * Only UTF-8 text files up to 2 MB can be edited. No delete/move here — that stays
    in file_controller.
"""
import hashlib
import os
import platform
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

PLUGIN = {
    "name": "file_navigator",
    "description": (
        "Find files and folders by name on any drive, take the user to them in File Explorer, "
        "open them, read them, and edit their text. Use for: 'take me to the X file', "
        "'navigate to X in the Data drive', 'open X', 'what's in X', 'change A to B in X', "
        "'add a line to X', 'undo that edit'. Use action='navigate' for 'take me to / show me'. "
        "If several files match, the tool returns a numbered list: read it to the user, then call "
        "action='pick' with their choice. Do NOT use file_controller for finding/navigating/editing; "
        "file_controller is only for move, copy, rename, delete."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "drives | find | navigate | pick | open | read | edit | restore"},
            "query": {"type": "STRING", "description": "File or folder name (or part of it), e.g. 'budget 2025'"},
            "path": {"type": "STRING", "description": "Exact path, if known"},
            "drive": {"type": "STRING", "description": "Drive letter ('D') or volume label ('Data') to search in"},
            "folder": {"type": "STRING", "description": "Only match items inside a folder whose name contains this, e.g. 'Projects'"},
            "kind": {"type": "STRING", "description": "file | folder | any (default any)"},
            "index": {"type": "INTEGER", "description": "For pick: the number from the list (1-based)"},
            "then": {"type": "STRING", "description": "For pick: navigate (default) | open | read"},
            "mode": {"type": "STRING", "description": "For edit: replace | append | prepend | overwrite"},
            "find": {"type": "STRING", "description": "For edit/replace: the exact text to find"},
            "text": {"type": "STRING", "description": "For edit: the new text (replacement, or text to add)"},
            "start_line": {"type": "INTEGER", "description": "For read: first line (1-based)"},
            "end_line": {"type": "INTEGER", "description": "For read: last line"},
        },
        "required": ["action"],
    },
}

_OS = platform.system()
_BACKUP_DIR = Path.home() / ".jarvis_backups"
_MAX_EDIT_BYTES = 2 * 1024 * 1024
_MAX_SPOKEN_CHARS = 1500
_SEARCH_SECONDS = 20.0
_MAX_DEPTH = 12
_KEEP_BACKUPS = 20

_last = {"results": [], "path": None}
_lock = threading.Lock()

_SKIP_DIRS = {
    "$recycle.bin", "system volume information", "windows", "program files",
    "program files (x86)", "programdata", "appdata", "node_modules", ".git",
    "__pycache__", "$windows.~bt", "recovery", "proc", "sys", "dev", "lib",
    "lib64", "bin", "sbin", "usr", "library", ".cache", ".venv", "venv",
}
_SECRET_NAMES = {"api_keys.json", ".env", "id_rsa", "id_ed25519", "id_ecdsa"}
_SECRET_SUFFIXES = {".pem", ".key", ".kdbx", ".pfx", ".p12"}


# ── helpers ─────────────────────────────────────────────────────────────────

def _log(player, msg):
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass


def _say(p: Path) -> str:
    parent = p.parent.name or str(p.parent)
    return f"{p.name} in {parent}"


def _drives() -> list[tuple[str, str]]:
    """[(root, label)] — on Windows the volume label is what 'the Data drive' means."""
    out: list[tuple[str, str]] = []
    if _OS == "Windows":
        import ctypes
        import string
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if mask >> i & 1:
                root = f"{letter}:\\"
                buf = ctypes.create_unicode_buffer(261)
                ok = ctypes.windll.kernel32.GetVolumeInformationW(
                    root, buf, 261, None, None, None, None, 0)
                out.append((root, buf.value if ok else ""))
        return out
    out.append(("/", ""))
    for base in ("/Volumes", "/media", "/mnt", f"/media/{os.environ.get('USER', '')}"):
        try:
            for d in sorted(Path(base).iterdir()):
                if d.is_dir():
                    out.append((str(d), d.name))
        except Exception:
            pass
    return out


def _resolve_drive(name: str) -> list[str]:
    """'D', 'D:' or a label like 'Data' -> matching roots. [] if nothing matches."""
    n = name.strip().rstrip("\\/").lower()
    if not n:
        return []
    roots = []
    for root, label in _drives():
        letter = root[:1].lower() if _OS == "Windows" else ""
        if (_OS == "Windows" and n in (letter, letter + ":")) or label.lower() == n:
            roots.append(root)
    if not roots:   # looser: label contains the word
        roots = [r for r, lab in _drives() if lab and n in lab.lower()]
    return roots


def _is_blocked(p: Path, write: bool) -> str | None:
    name = p.name.lower()
    if name in _SECRET_NAMES or p.suffix.lower() in _SECRET_SUFFIXES:
        return f"{p.name} holds secrets, so I won't {'edit' if write else 'read'} it"
    if write:
        prot = [os.environ.get(k) for k in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)")]
        prot += ["/etc", "/usr", "/bin", "/sbin", "/lib", "/boot", "/sys", "/proc",
                 "/System", "/Library"]
        try:
            rp = p.resolve()
            for pr in filter(None, prot):
                if rp.is_relative_to(Path(pr).resolve()):
                    return "that is a protected system location"
        except Exception:
            pass
    return None


def _tokens(q: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", q.lower()) if t]


def _score(name: str, query: str, toks: list[str], depth: int) -> float:
    nl, ql = name.lower(), query.lower().strip()
    stem = nl.rsplit(".", 1)[0] if "." in nl else nl
    if nl == ql:
        base = 100.0
    elif stem == ql:
        base = 95.0
    else:
        hit = sum(1 for t in toks if t in nl)
        frac = hit / len(toks) if toks else 0
        if frac < 0.7:
            return 0.0
        base = 40 + 40 * frac + 15 * min(1.0, len(ql) / max(1, len(nl)))
    return base - depth * 1.5


def _search(parameters: dict, kind: str) -> list[tuple[float, Path]]:
    query = str(parameters.get("query", "")).strip()
    toks = _tokens(query)
    if not toks:
        return []
    drive = str(parameters.get("drive", "")).strip()
    hint = str(parameters.get("folder", "")).strip().lower()

    roots: list[str] = []
    if drive:
        roots = _resolve_drive(drive)
        if not roots:
            hint = hint or drive.lower()   # "the Data folder" — not a drive after all
    if not roots:
        roots = [r for r, _ in _drives()]
        home = str(Path.home())
        if home not in roots:
            roots.insert(0, home)

    q = deque((r, 0) for r in roots)
    found: list[tuple[float, Path]] = []
    exact = 0
    deadline = time.monotonic() + _SEARCH_SECONDS
    while q and time.monotonic() < deadline and exact < 3:
        cur, depth = q.popleft()
        try:
            it = list(os.scandir(cur))
        except Exception:
            continue
        for e in it:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except Exception:
                continue
            nl = e.name.lower()
            want = kind == "any" or (kind == "folder") == is_dir
            if want and (not hint or hint in str(cur).lower()):
                s = _score(e.name, query, toks, depth)
                if s > 0:
                    found.append((s, Path(e.path)))
                    if s >= 99:
                        exact += 1
            if is_dir and depth < _MAX_DEPTH and nl not in _SKIP_DIRS and not nl.startswith("$"):
                q.append((e.path, depth + 1))
    found.sort(key=lambda t: -t[0])
    return found[:8]


def _listing(results) -> str:
    return "; ".join(f"{i}. {_say(p)}" for i, (_, p) in enumerate(results[:5], 1))


def _target(parameters: dict, kind: str):
    """-> (Path|None, message|None). Message is set when we need the user's help."""
    raw = str(parameters.get("path", "")).strip().strip('"')
    if raw:
        p = Path(raw).expanduser()
        return (p, None) if p.exists() else (None, f"I can't find {raw}")
    if str(parameters.get("query", "")).strip():
        res = _search(parameters, kind)
        if not res:
            return None, "I couldn't find anything with that name"
        top = res[0][0]
        if len(res) == 1 or (top >= 90 and top - res[1][0] >= 15) or (top >= 60 and top - res[1][0] >= 30):
            return res[0][1], None
        with _lock:
            _last["results"] = [p for _, p in res[:5]]
        return None, f"I found {min(5, len(res))} matches: {_listing(res)}. Which one?"
    if _last["path"] and Path(_last["path"]).exists():
        return Path(_last["path"]), None
    return None, "Tell me which file you mean"


def _reveal(p: Path) -> None:
    if _OS == "Windows":
        if p.is_dir():
            subprocess.Popen(["explorer", str(p)])
        else:
            subprocess.Popen(["explorer", f"/select,{p}"])
    elif _OS == "Darwin":
        subprocess.Popen(["open", str(p)] if p.is_dir() else ["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)])


def _open(p: Path) -> None:
    if _OS == "Windows":
        os.startfile(str(p))  # noqa: S606 — user-requested, default handler
    elif _OS == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


# ── read / edit / restore ───────────────────────────────────────────────────

def _read_text(p: Path) -> tuple[str | None, str | None]:
    if p.is_dir():
        return None, f"{p.name} is a folder"
    raw = p.read_bytes()
    if b"\x00" in raw[:4096]:
        return None, f"{p.name} is not a text file"
    try:
        return raw.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return None, f"{p.name} is not UTF-8 text"


def _backup(p: Path) -> Path:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(str(p.resolve()).encode()).hexdigest()[:8]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = _BACKUP_DIR / f"{h}_{ts}_{p.name}.bak"
    dest.write_bytes(p.read_bytes())
    old = sorted(_BACKUP_DIR.glob(f"{h}_*.bak"))
    for stale in old[:-_KEEP_BACKUPS]:
        try:
            stale.unlink()
        except Exception:
            pass
    return dest


def _write(p: Path, text: str, bom: bool) -> None:
    tmp = p.with_name(p.name + ".jarvis_tmp")
    tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    os.replace(tmp, p)


def _nl(s: str, like: str) -> str:
    """Match the file's own line endings so we never mix \\n and \\r\\n."""
    s = s.replace("\r\n", "\n")
    return s.replace("\n", "\r\n") if "\r\n" in like else s


def _do_edit(p: Path, params: dict) -> str:
    why = _is_blocked(p, write=True)
    if why:
        return f"Sir, {why}."
    if p.is_dir():
        return f"Sir, {p.name} is a folder."
    if p.stat().st_size > _MAX_EDIT_BYTES:
        return f"Sir, {p.name} is too large to edit safely."
    content, err = _read_text(p)
    if err:
        return f"Sir, {err}."
    bom = p.read_bytes().startswith(b"\xef\xbb\xbf")

    mode = str(params.get("mode", "replace")).lower().strip()
    new = str(params.get("text", ""))
    if mode == "replace":
        target = str(params.get("find", ""))
        if not target:
            return "Sir, tell me which text to replace."
        target = _nl(target, content)
        count = content.count(target)
        if count == 0:
            return f"Sir, I couldn't find that text in {p.name}. Nothing was changed."
        result = content.replace(target, _nl(new, content))
        summary = f"Replaced {count} occurrence{'s' if count != 1 else ''} in {p.name}"
    elif mode == "append":
        sep = "" if content.endswith(("\n", "\r\n")) or not content else _nl("\n", content)
        result = content + sep + _nl(new, content) + (_nl("\n", content) if new and not new.endswith("\n") else "")
        summary = f"Added that to the end of {p.name}"
    elif mode == "prepend":
        result = _nl(new, content) + (_nl("\n", content) if new and not new.endswith("\n") else "") + content
        summary = f"Added that to the top of {p.name}"
    elif mode == "overwrite":
        result = _nl(new, content)
        summary = f"Rewrote {p.name}"
    else:
        return "Sir, edit mode must be replace, append, prepend or overwrite."

    if result == content:
        return f"Sir, that would not change {p.name}."
    _backup(p)
    _write(p, result, bom)
    return f"{summary}. Say 'undo that edit' to put it back."


def _do_restore(p: Path) -> str:
    why = _is_blocked(p, write=True)
    if why:
        return f"Sir, {why}."
    h = hashlib.sha1(str(p.resolve()).encode()).hexdigest()[:8]
    backups = sorted(_BACKUP_DIR.glob(f"{h}_*.bak")) if _BACKUP_DIR.exists() else []
    if not backups:
        return f"Sir, I have no earlier version of {p.name}."
    latest = backups[-1]
    data = latest.read_bytes()
    if p.exists():
        _backup(p)               # safety copy, so a restore can itself be undone
    p.write_bytes(data)
    try:
        latest.unlink()          # consumed
    except Exception:
        pass
    return f"Restored the previous version of {p.name}."


# ── entry point ─────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).lower().strip()
    kind = str(parameters.get("kind", "any")).lower().strip()
    if kind not in ("file", "folder", "any"):
        kind = "any"
    try:
        if action == "drives":
            ds = _drives()
            if not ds:
                return "Sir, I couldn't list the drives."
            return "Drives: " + ", ".join(
                f"{r.rstrip(chr(92))} ({lab})" if lab else r.rstrip(chr(92)) for r, lab in ds)

        if action == "find":
            res = _search(parameters, kind)
            if not res:
                return "Sir, I couldn't find anything with that name."
            with _lock:
                _last["results"] = [p for _, p in res[:5]]
                _last["path"] = str(res[0][1])
            msg = f"I found {min(5, len(res))}: {_listing(res)}."
            _log(player, msg)
            return msg

        if action == "pick":
            idx = int(parameters.get("index") or 0)
            with _lock:
                items = list(_last["results"])
            if not items or not (1 <= idx <= len(items)):
                return "Sir, I have no numbered list to pick from. Ask me to find it first."
            p = items[idx - 1]
            with _lock:
                _last["path"] = str(p)
            then = str(parameters.get("then", "navigate")).lower()
            if then == "open":
                _open(p)
                return f"Opening {_say(p)}."
            if then == "read":
                return _read_reply(p, parameters)
            _reveal(p)
            return f"Here it is: {_say(p)}."

        if action in ("navigate", "open", "read", "edit", "restore"):
            want = "folder" if (kind == "folder") else ("file" if action in ("read", "edit", "restore") else kind)
            p, msg = _target(parameters, want)
            if msg:
                return f"Sir, {msg}" + ("" if msg.endswith("?") else ".")
            with _lock:
                _last["path"] = str(p)
            if action == "navigate":
                _reveal(p)
                _log(player, f"Showing {p}")
                return f"Here it is: {_say(p)}."
            if action == "open":
                _open(p)
                return f"Opening {_say(p)}."
            if action == "read":
                return _read_reply(p, parameters)
            if action == "edit":
                r = _do_edit(p, parameters)
                _log(player, f"{r} ({p})")
                return r
            return _do_restore(p)

        return "Sir, file_navigator needs an action: drives, find, navigate, pick, open, read, edit or restore."
    except Exception as e:
        return f"Sir, file_navigator failed: {e}"


def _read_reply(p: Path, params: dict) -> str:
    why = _is_blocked(p, write=False)
    if why:
        return f"Sir, {why}."
    text, err = _read_text(p)
    if err:
        return f"Sir, {err}."
    lines = text.splitlines()
    a, b = params.get("start_line"), params.get("end_line")
    if a or b:
        a = max(1, int(a or 1))
        b = min(len(lines), int(b or len(lines)))
        text = "\n".join(lines[a - 1:b])
    if len(text) > _MAX_SPOKEN_CHARS:
        text = text[:_MAX_SPOKEN_CHARS] + f"\n... (file has {len(lines)} lines; ask for a line range to hear more)"
    return text if text.strip() else f"{p.name} is empty."
