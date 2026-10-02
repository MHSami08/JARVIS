"""
plugins/self_dev.py - JARVIS studies its OWN code. Two modes, you choose by what you say.

  PROMPT mode (the default - changes nothing)
      "prepare a prompt for main.py to fix bugs"  /  "analyse ui.py and give me a prompt"
      JARVIS analyses the file and writes one finished prompt you can paste into ANY
      AI (Claude, ChatGPT, Gemini...). It is copied to the clipboard and saved in
      claude_prompts/. No project file is touched.

  EDIT mode (only when you tell it to modify the code)
      "fix the bugs in weather_report.py yourself"  /  "go ahead and edit ui.py"
      JARVIS asks Gemini for small find/replace edits, checks that each one matches
      exactly once and that the file still compiles, shows the change on the HUD, and
      writes NOTHING until YOU press CONFIRM (core/confirm.py - the model cannot press
      it). The original is backed up to .jarvis_backups/ and "undo" restores it.
      It cannot edit itself, the confirm/undo/plugin-loader code, config/ or memory/.
      Changes load on the next launch - a running program is never edited live.

Both modes: it only works inside the JARVIS folder it lives in; config/, memory/ and
certificates are never read; anything that looks like a key or password is replaced
with <REDACTED> before any text leaves your PC.
"""

import ast
import difflib
import hashlib
import platform
import py_compile
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from core import confirm, gemini
from core.undo import push_undo

ROOT = Path(__file__).resolve().parent.parent      # JARVIS knows where it lives
OUT_DIR = ROOT / "claude_prompts"
BACKUP_DIR = ROOT / ".jarvis_backups"
PROTECTED = {                                      # edit mode may never change these
    "plugins/self_dev.py", "core/confirm.py", "core/undo.py", "core/plugin_loader.py",
}
MAX_EDITS = 6
SKIP_DIRS = {
    ".git", "venv", ".venv", "__pycache__", "node_modules",
    ".jarvis_backups", "claude_prompts", "config", "memory",
}
ALLOWED_SUFFIX = {".py", ".html"}
MAX_ANALYSE_CHARS = 400_000     # most Gemini will be sent for analysis
MAX_EMBED_CHARS = 60_000        # above this, the prompt says "attach the file"
MAX_FINDINGS = 12

PLUGIN = {
    "name": "self_dev",
    "description": (
        "Works on JARVIS's OWN source code, one file at a time. Default mode='prompt': "
        "analyses the file and writes a ready-to-paste development prompt for the user "
        "to give to another AI (Claude, ChatGPT...) - it changes NO file. Use "
        "mode='edit' ONLY when the user explicitly tells JARVIS to modify, fix or "
        "improve the code itself (e.g. 'fix it yourself', 'go ahead and edit', 'apply "
        "the changes'); even then the user must press CONFIRM on screen before "
        "anything is written. If the user only asks for a prompt, analysis or review, "
        "use mode='prompt'. When unsure, use 'prompt'. action='list' names the files. "
        "Do NOT use for the user's own projects."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "'list' or 'work' (default 'work')"},
            "file": {"type": "STRING", "description": "File to work on, e.g. 'main.py' or 'core/tts.py'"},
            "goal": {"type": "STRING",
                     "description": "What the user wants done, e.g. 'find and fix bugs', "
                                    "'improve the UI code', 'make error handling safer'. Default: find and fix bugs."},
            "mode": {"type": "STRING",
                     "description": "'prompt' (default, never changes files) or 'edit' (only if the user "
                                    "explicitly asked JARVIS to change the code)"},
        },
        "required": [],
    },
}


# ── finding the file ────────────────────────────────────────────────────────

def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _files() -> list:
    out = []
    for p in ROOT.rglob("*"):
        if (p.is_file() and p.suffix.lower() in ALLOWED_SUFFIX
                and not (SKIP_DIRS & set(p.relative_to(ROOT).parts))):
            out.append(p)
    return sorted(out)


def _resolve(name: str, for_edit: bool = False):
    wanted = name.strip().replace("\\", "/").lower().lstrip("./")
    if not wanted:
        return None, "Which file should I work on?"
    files = _files()
    if for_edit:
        for prot in PROTECTED:
            if wanted == prot or wanted == prot.rsplit("/", 1)[-1]:
                return None, f"Sir, {prot} is protected - I do not edit my own safety code."
        files = [p for p in files if _rel(p) not in PROTECTED and not p.name.startswith("_")]
    hits = [p for p in files if _rel(p).lower() == wanted]
    if not hits:
        hits = [p for p in files if p.name.lower() in (wanted, wanted + ".py")]
    if not hits:
        return None, f"I could not find a file called {name} that I am allowed to read."
    if len(hits) > 1:
        return None, ("That name matches several files: "
                      + ", ".join(_rel(p) for p in hits[:4]) + ". Which one?")
    return hits[0], None


# ── keeping secrets out of the prompt ───────────────────────────────────────

_SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),                 # Google / Gemini keys
    re.compile(r"sk-ant-[0-9A-Za-z_\-]{10,}"),              # Anthropic keys
    re.compile(r"\bsk-[0-9A-Za-z]{20,}"),                   # OpenAI-style keys
    re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}"),            # GitHub tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),      # private keys
]
_ASSIGNED_SECRET = re.compile(
    r"""(?ix)((?:api[_-]?key|secret|token|passw(?:or)?d|auth)[\w]*\s*[:=]\s*)(["'])([^"'\n]{8,})\2""")


def _redact(code: str):
    n = 0

    def _assigned(m):
        nonlocal n
        if "REDACTED" in m.group(3) or m.group(3).lower().startswith(("http", "your", "<")):
            return m.group(0)
        n += 1
        return f"{m.group(1)}{m.group(2)}<REDACTED>{m.group(2)}"

    code = _ASSIGNED_SECRET.sub(_assigned, code)
    for pat in _SECRET_PATTERNS:
        code, k = pat.subn("<REDACTED>", code)
        n += k
    return code, n


# ── free local analysis ─────────────────────────────────────────────────────

def _outline_and_checks(rel: str, code: str):
    """Return (outline_lines, static_findings). Never raises."""
    if not rel.endswith(".py"):
        return [], []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [], [{"line": e.lineno, "severity": "high",
                     "issue": f"The file does not parse: {e.msg}",
                     "suggestion": "Fix this syntax error first."}]
    outline, findings = [], []
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.add(n.module.split(".")[0])
    imports = sorted(mods)
    if imports:
        outline.append("imports: " + ", ".join(imports))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            outline.append(f"class {node.name}  (line {node.lineno}, {len(methods)} methods)")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            outline.append(f"{kind} {node.name}  (line {node.lineno})")
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append({"line": node.lineno, "severity": "medium",
                             "issue": "Bare `except:` also swallows KeyboardInterrupt/SystemExit and hides real errors.",
                             "suggestion": "Catch `Exception` (or something narrower) and log it."})
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in ("eval", "exec"):
                findings.append({"line": node.lineno, "severity": "high",
                                 "issue": f"`{f.id}()` runs arbitrary code.",
                                 "suggestion": "Replace with a safe parser/dispatch table, or justify why it is safe."})
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    findings.append({"line": node.lineno, "severity": "medium",
                                     "issue": "subprocess call with shell=True (command-injection risk if any part is user/model text).",
                                     "suggestion": "Pass an argument list without shell=True."})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in list(node.args.defaults) + [d for d in node.args.kw_defaults if d]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    findings.append({"line": node.lineno, "severity": "medium",
                                     "issue": f"`{node.name}` has a mutable default argument (shared between calls).",
                                     "suggestion": "Default to None and create the list/dict inside the function."})
            length = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1
            if length > 150:
                findings.append({"line": node.lineno, "severity": "low",
                                 "issue": f"`{node.name}` is {length} lines long - hard to test and easy to break.",
                                 "suggestion": "Split into smaller functions (only if it can be done safely)."})
    findings.sort(key=lambda f: ({"high": 0, "medium": 1, "low": 2}.get(f["severity"], 3), f.get("line") or 0))
    return outline, findings


# ── Gemini's deeper pass ────────────────────────────────────────────────────

def _gemini_analysis(rel: str, code: str, goal: str, files: list):
    prompt = f"""You are a careful senior Python reviewer looking at ONE file of a desktop voice assistant (JARVIS: PyQt6 HUD, Gemini Live API, plugin system).
Other project files (names only): {", ".join(files[:60])}

File: {rel}
Goal: {goal}

Find real problems and worthwhile improvements that fit the goal. Be specific and honest;
if you are not sure something is a bug, say so. Do not invent line numbers.

Reply with ONLY a JSON object, no prose, no fences:
{{"summary": "2-3 sentences on what this file does and its overall condition",
  "findings": [{{"line": <int or null>, "severity": "high|medium|low", "issue": "...", "suggestion": "..."}}]}}
At most {MAX_FINDINGS} findings, most important first.

FILE CONTENT:
{code}"""
    data = gemini.as_json(prompt, tier=gemini.SMART, timeout_ms=120_000, default=None)
    if not isinstance(data, dict):
        return "", []
    summary = str(data.get("summary") or "").strip()
    out = []
    for f in (data.get("findings") or [])[:MAX_FINDINGS]:
        if isinstance(f, dict) and f.get("issue"):
            ln = f.get("line")
            out.append({"line": ln if isinstance(ln, int) else None,
                        "severity": str(f.get("severity") or "medium").lower(),
                        "issue": str(f["issue"]).strip(),
                        "suggestion": str(f.get("suggestion") or "").strip()})
    return summary, out


# ── assembling the prompt ───────────────────────────────────────────────────

def _fmt_findings(items: list) -> str:
    if not items:
        return "_None found._"
    lines = []
    for i, f in enumerate(items, 1):
        where = f"line {f['line']}" if f.get("line") else "location unknown"
        sug = f"  \n   Suggested: {f['suggestion']}" if f.get("suggestion") else ""
        lines.append(f"{i}. **[{f['severity']}]** ({where}) {f['issue']}{sug}")
    return "\n".join(lines)


def _build_prompt(rel, goal, code, crlf, redactions, summary, static, ai, outline, files, embed):
    reqs = ROOT / "requirements.txt"
    deps = ""
    try:
        names = [re.split(r"[<>=!~\[ ;#]", l.strip(), 1)[0] for l in reqs.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        deps = ", ".join(n for n in names if n)[:600]
    except Exception:
        pass
    nl = code.count("\n") + 1
    code_block = (f"```{'python' if rel.endswith('.py') else 'html'}\n{code}\n```" if embed else
                  f"_The file is too large to paste ({len(code):,} characters), so it is **attached** as `{Path(rel).name}`. "
                  f"Read the attached file in full before answering._")
    attach_note = "" if embed else "\n> **Before sending: attach `" + rel + "` to this message.**\n"
    return f"""# Task: {goal}
{attach_note}
I am working on **JARVIS**, a Python desktop voice assistant that runs locally on my PC.
I want you to work on **one file**: `{rel}` ({nl:,} lines).

## Project context
- Python {platform.python_version()} on {platform.system()}; PyQt6 HUD; Gemini Live API for voice; drop-in plugin system (`plugins/*.py` with a `PLUGIN` dict and `run()`).
- Dependencies (from requirements.txt): {deps or 'not available'}
- Other files in the project (names only): {", ".join(files[:80])}
- My files use {"Windows (CRLF)" if crlf else "Unix (LF)"} line endings.

## What I want
{goal}

## Pre-analysis from JARVIS (a first pass - it can be wrong, so verify each point against the code)
**What the file does:** {summary or '_analysis unavailable_'}

**Checks that ran locally on the code:**
{_fmt_findings(static)}

**Gemini's review:**
{_fmt_findings(ai)}

## Rules - please follow these strictly
1. **Do not rename or remove** any function, class, constant, tool name or `PLUGIN` name, and do not change signatures - other files import and call them. If you think one must change, ask first.
2. Change only what is needed for the goal. **Do not reformat or "tidy" unrelated code.**
3. No new dependencies unless unavoidable; if you add one, say so clearly at the top.
4. Keep it compatible with Python {platform.python_version()} and with how the code is already structured (threads, Qt signals, async).
5. Never hard-code secrets. Keep any key/password handling exactly as it is.
6. If a finding above is wrong or not worth fixing, say so instead of changing code for the sake of it.

## How to answer
1. First, a short list of the issues you **confirmed** in the code (and any pre-analysis points you disagree with, with reasons).
2. Then the changes as **numbered edits**, each with: the exact old text to find (enough lines to be unique), the exact new text, and one sentence on why. {"If the file is under about 300 lines, you may give the whole corrected file instead." if nl < 300 else "Do not rewrite the whole file - it is large; give edits only."}
3. For each edit, say how I can test it, and flag anything that could break other parts of JARVIS.

## File outline
{chr(10).join('- ' + o for o in outline) if outline else '_not available_'}

## The code{f"  ({redactions} secret(s) replaced with <REDACTED>)" if redactions else ""}
{code_block}
"""


def _log(player, msg):
    if player:
        try:
            player.write_log(msg)
        except Exception:
            pass


def _copy(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False


# ── EDIT mode: Gemini proposes small edits, YOU confirm ─────────────────────

def _edit_prompt(rel, text, goal, files, feedback):
    fix = f"\nYour previous attempt was rejected: {feedback}\nFix that.\n" if feedback else ""
    return f"""You are editing ONE file of a Python desktop voice assistant called JARVIS.
Other project files (context only): {", ".join(files[:60])}

File: {rel}
Goal: {goal}
{fix}
Reply with ONLY a JSON object, no prose, no markdown fences:
{{"edits": [{{"find": "...", "replace": "...", "why": "..."}}]}}

Rules:
- At most {MAX_EDITS} edits. Only real bugs or clear, low-risk improvements that serve the goal.
- "find" must be copied EXACTLY from the file (same indentation) and appear exactly ONCE; add
  surrounding lines to make it unique. Keep it short.
- Do not rename functions, classes, constants or tool names that other files may use.
- Do not reformat code you are not fixing. Do not add dependencies.
- Never touch lines containing <REDACTED> (secrets were hidden from you on purpose).
- If nothing is worth changing, reply {{"edits": []}}.

FILE CONTENT:
{text}"""


def _apply_edits(text, edits):
    """(new_text, error). Every find must match the ORIGINAL exactly once."""
    new = text
    for i, e in enumerate(edits, 1):
        if not isinstance(e, dict):
            return text, f"edit {i} is not an object"
        find, repl = e.get("find"), e.get("replace")
        if not isinstance(find, str) or not isinstance(repl, str) or not find.strip():
            return text, f"edit {i} is missing find/replace"
        if "<REDACTED>" in find or "<REDACTED>" in repl:
            return text, f"edit {i} touches a hidden secret line"
        if find == repl:
            return text, f"edit {i} changes nothing"
        n = new.count(find)
        if n != 1:
            return text, f"edit {i}: 'find' matched {n} times, it must match exactly once"
        new = new.replace(find, repl, 1)
    return new, None


def _syntax_error(rel, text):
    if not rel.endswith(".py"):
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(text)
        tmp = f.name
    try:
        py_compile.compile(tmp, doraise=True)
        return None
    except py_compile.PyCompileError as e:
        return str(e).replace(tmp, rel)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _propose(rel, text, goal, files):
    """Ask Gemini, validate, retry once with the reason. -> (edits, new_text, error)."""
    feedback = ""
    for _ in range(2):
        data = gemini.as_json(_edit_prompt(rel, text, goal, files, feedback),
                              tier=gemini.SMART, timeout_ms=120_000, default=None)
        if not isinstance(data, dict) or not isinstance(data.get("edits"), list):
            feedback = "the reply was not the required JSON object"
            continue
        edits = data["edits"][:MAX_EDITS]
        if not edits:
            return [], text, None
        new, err = _apply_edits(text, edits)
        if err is None:
            err = _syntax_error(rel, new)
        if err is None:
            return edits, new, None
        feedback = err
    return [], text, feedback


def _do_edit(path, rel, goal, files, player):
    raw_bytes = path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    original = raw_bytes.decode("utf-8")
    crlf = "\r\n" in original
    original = original.replace("\r\n", "\n")
    if len(original) > MAX_ANALYSE_CHARS:
        return f"Sir, {rel} is too large for me to edit safely in one pass."
    shown, _hidden = _redact(original)           # what Gemini sees; secrets hidden

    _log(player, f"JARVIS: editing plan for {rel}: {goal}...")
    edits, _new_shown, err = _propose(rel, shown, goal, files)
    if err:
        return f"Sir, I could not produce a safe change for {rel}: {err}"
    if not edits:
        return f"I looked through {rel} and found nothing worth changing for that goal."
    # The edits were validated against the redacted text; replay them on the REAL text.
    new_text, err = _apply_edits(original, edits)
    if err is None:
        err = _syntax_error(rel, new_text)
    if err:
        return f"Sir, the change for {rel} did not apply cleanly: {err}"

    diff = "\n".join(difflib.unified_diff(original.splitlines(), new_text.splitlines(),
                                          f"a/{rel}", f"b/{rel}", lineterm=""))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prop = BACKUP_DIR / "proposals"
    prop.mkdir(parents=True, exist_ok=True)
    diff_path = prop / f"{stamp}_{path.stem}.diff"
    diff_path.write_text(diff, encoding="utf-8")
    for line in diff.splitlines()[:60]:
        _log(player, f"  {line}")
    whys = "; ".join(str(e.get("why", "")).strip() for e in edits if e.get("why"))

    def _apply() -> str:
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return f"{rel} changed since I looked at it, so I applied nothing."
            backup = BACKUP_DIR / stamp / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            out = new_text.replace("\n", "\r\n") if crlf else new_text
            path.write_bytes(out.encode("utf-8"))

            def _undo() -> str:
                shutil.copy2(backup, path)
                return f"Restored {rel}. Restart me to load the old version."

            push_undo(f"edit to {rel}", _undo)
            return (f"Applied {len(edits)} change(s) to {rel}. Restart me to load them. "
                    f"The original is saved; say undo to revert.")
        except Exception as e:
            return f"Sir, applying the change to {rel} failed: {e}"

    return confirm.request(
        key=f"self_dev:{rel}:{stamp}",
        title=f"Apply {len(edits)} change(s) to {rel}",
        detail=(whys[:280] or "See the diff in the log.") + f"  (diff: {diff_path.name})",
        run=_apply,
    )


# ── PROMPT mode ─────────────────────────────────────────────────────────────

def _do_prompt(path, rel, goal, files, player):
    raw = path.read_bytes().decode("utf-8", errors="replace")
    crlf = "\r\n" in raw
    code, redactions = _redact(raw.replace("\r\n", "\n"))
    if len(code) > MAX_ANALYSE_CHARS:
        return f"Sir, {rel} is too large for me to analyse in one pass."

    _log(player, f"JARVIS: analysing {rel} for: {goal}...")
    outline, static = _outline_and_checks(rel, code)
    summary, ai = _gemini_analysis(rel, code, goal, files)
    embed = len(code) <= MAX_EMBED_CHARS
    prompt = _build_prompt(rel, goal, code, crlf, redactions, summary, static, ai, outline, files, embed)

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{path.stem}.md"
    out.write_text(prompt, encoding="utf-8")
    copied = _copy(prompt)

    _log(player, f"JARVIS: prompt for {rel} saved to {out.relative_to(ROOT).as_posix()}")
    for line in prompt.splitlines()[:25]:
        _log(player, f"  {line}")
    parts = [f"The prompt for {rel} is ready with {len(static) + len(ai)} finding(s). "
             "I did not change any file."]
    parts.append("It is on your clipboard and saved in the claude_prompts folder."
                 if copied else "It is saved in the claude_prompts folder - the clipboard was not available.")
    if not embed:
        parts.append(f"The file is large, so attach {Path(rel).name} to your message in the other AI.")
    if redactions:
        parts.append(f"I hid {redactions} secret value(s) in it.")
    if not ai:
        parts.append("Gemini's analysis was unavailable, so it only has the local checks.")
    return " ".join(parts)


# ── the tool ────────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        action = (parameters.get("action") or "work").strip().lower()
        mode = (parameters.get("mode") or "prompt").strip().lower()
        mode = "edit" if mode == "edit" else "prompt"        # anything unclear = safe mode
        files = _files()
        if action == "list":
            big = sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:5]
            return (f"I can work on {len(files)} files. The largest are "
                    + ", ".join(_rel(p) for p in big)
                    + ". Which one, and do you want a prompt or should I edit it?")

        path, err = _resolve(parameters.get("file") or "", for_edit=(mode == "edit"))
        if err:
            return err
        rel = _rel(path)
        goal = (parameters.get("goal") or "").strip() or "Find and fix bugs"
        names = [_rel(p) for p in files]
        if mode == "edit":
            return _do_edit(path, rel, goal, names, player)
        return _do_prompt(path, rel, goal, names, player)
    except Exception as e:
        return f"Sir, I could not finish that: {e}"
