# google_workspace.py
"""Google Docs and Google Sheets control for JARVIS.

Auth is OAuth 2.0 "installed app" flow:

  config/credentials.json   the client secret you download from Google Cloud
                            (Desktop app type) — you supply this once
  config/google_token.json  the refreshable user token — written here after the
                            first consent, so later sessions never re-prompt

The signed-in account's email is captured at consent time (userinfo.email scope)
and stored alongside the token as "email". Files are opened in the browser with
`?authuser=<email>` so Google picks that exact account even when the browser is
signed into several.

Nothing in this module is imported at discovery time except the stdlib, so the
`google-*` packages are optional: if they are missing the tool still loads and
simply answers with the pip command. Every failure path returns a sentence for
the model to read out — this file never raises out of `google_workspace()`.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────────────
def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = _get_base_dir()
CONFIG_DIR       = BASE_DIR / "config"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH       = CONFIG_DIR / "google_token.json"

# Both scopes are needed: one action file covers two APIs, and asking for them
# together means one consent screen and one cached token instead of two.
_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    # Lets us learn WHICH account signed in, so browser links can pin it.
    "https://www.googleapis.com/auth/userinfo.email",
]

_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# URL of the last Doc/Sheet this module created or touched (with ?authuser=).
# Module-level on purpose: action_loader keeps the module in sys.modules, so it
# survives between tool calls for the life of the process. "open it" with no ID
# falls back to this.
_LAST_ACCESSED_URL: str = ""

# Interactive consent has to finish inside the executor's per-tool budget —
# main.py caps every action at _TOOL_TIMEOUT_S = 180 s. Give up a little before
# that so the user gets a sentence back rather than a bare timeout kill.
_OAUTH_TIMEOUT_S = 150


class _AuthError(RuntimeError):
    """Carries a sentence meant for the user, not a traceback."""


_MISSING_LIB_MSG = (
    "Google Workspace needs three packages that are not installed. "
    "Run:  pip install google-api-python-client google-auth-oauthlib "
    "google-auth-httplib2   ({err})"
)

_MISSING_CREDS_MSG = (
    "I do not have Google credentials yet. Put your OAuth client file at "
    f"{CREDENTIALS_PATH} (Google Cloud Console → APIs & Services → Credentials "
    "→ Create credentials → OAuth client ID → Desktop app → download JSON), "
    "then ask me again and I will open a browser for you to approve access."
)


# ── Lazy library load ─────────────────────────────────────────────────────────
# Cached after the first success. On failure we raise _AuthError instead of
# ImportError so the caller reports one helpful line and the tool stays loaded.
_LIBS: dict | None = None


def _libs() -> dict:
    global _LIBS
    if _LIBS is None:
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
        except ImportError as e:
            raise _AuthError(_MISSING_LIB_MSG.format(err=e))
        try:
            # Preferred transport when present — the official httplib2 wrapper.
            from google_auth_httplib2 import AuthorizedHttp
        except ImportError:
            AuthorizedHttp = None
        _LIBS = {
            "Credentials":       Credentials,
            "Request":           Request,
            "InstalledAppFlow":  InstalledAppFlow,
            "build":             build,
            "HttpError":         HttpError,
            "AuthorizedHttp":    AuthorizedHttp,
        }
    return _LIBS


def _read_token_file() -> dict:
    """The raw token JSON as a dict, or {} if absent/unreadable."""
    try:
        data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _cached_email() -> str:
    """Email stored next to the token ('' if we never captured it)."""
    return str(_read_token_file().get("email") or "").strip()


def _token_covers_scopes(info: dict) -> bool:
    """True only if the stored token was GRANTED every scope we need now.

    Checked against the raw file, not the loaded Credentials: from_authorized_user_file
    is handed _SCOPES and would happily claim the new scope an old token never
    received. Refreshing such a token with the wider scope list fails, so we
    send the user through consent once instead."""
    granted = info.get("scopes")
    if isinstance(granted, str):
        granted = granted.split()
    return bool(granted) and set(_SCOPES) <= set(granted)


def _fetch_email(access_token: str) -> str:
    """Ask Google who this token belongs to. Never raises — '' on any failure."""
    if not access_token:
        return ""
    try:
        req = urllib.request.Request(
            _USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("email") or "").strip()
    except Exception as e:
        print(f"[Workspace] ⚠️ Could not fetch account email: {e}")
        return ""


def _save_token(creds, email: str | None = None) -> None:
    """Persist the refreshable token (plus the account email) so the next
    session skips the browser.

    `email=None` keeps the stored address, fetching it if we never had one.
    Pass an explicit value (even '') after a fresh sign-in, so a different
    account can never inherit the previous account's address."""
    try:
        if email is None:
            email = _cached_email() or _fetch_email(getattr(creds, "token", ""))
        data = json.loads(creds.to_json())
        if email:
            data["email"] = email
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        # Not fatal — the session keeps working, it just re-prompts next launch.
        print(f"[Workspace] ⚠️ Could not save token to {TOKEN_PATH}: {e}")


def _credentials():
    """Return valid Google credentials, or raise _AuthError with a sentence."""
    libs        = _libs()
    Credentials = libs["Credentials"]

    if not CREDENTIALS_PATH.exists():
        raise _AuthError(_MISSING_CREDS_MSG)

    creds = None
    if TOKEN_PATH.exists():
        if not _token_covers_scopes(_read_token_file()):
            # Token predates the userinfo.email scope (or is malformed).
            print("[Workspace] 🔐 Stored token lacks a required scope — re-authorising")
        else:
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), _SCOPES)
            except Exception as e:
                print(f"[Workspace] ⚠️ Stored token unreadable ({e}) — re-authorising")
                creds = None

    if creds and creds.valid:
        if not _cached_email():
            _save_token(creds)      # backfill the email once
        return creds

    # An expired token with a refresh token renews silently — this is the path
    # every session after the first one takes.
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(libs["Request"]())
            _save_token(creds)
            return creds
        except Exception as e:
            print(f"[Workspace] ⚠️ Token refresh failed ({e}) — re-authorising")

    # First run, revoked token, or a scope change: interactive consent. This
    # opens the user's browser and blocks until they approve, so it runs with a
    # deadline and says so plainly if it expires.
    print("[Workspace] 🔐 Opening browser for Google consent…")
    # Google may return the email scope alongside "openid"; oauthlib treats any
    # difference from the requested scope list as an error unless relaxed.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    try:
        flow = libs["InstalledAppFlow"].from_client_secrets_file(
            str(CREDENTIALS_PATH), _SCOPES
        )
        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            timeout_seconds=_OAUTH_TIMEOUT_S,
            authorization_prompt_message=(
                "JARVIS needs Google Docs & Sheets access. "
                "Opening your browser — approve there to continue."
            ),
            success_message="JARVIS is connected. You can close this tab.",
        )
    except Exception as e:
        raise _AuthError(
            "Google sign-in did not complete "
            f"({type(e).__name__}: {e}). If you closed the browser or it timed "
            "out, just ask me again — or delete "
            f"{TOKEN_PATH} and retry if the token looks stale."
        )

    # Fresh sign-in: always re-fetch, never inherit a previous account's email.
    _save_token(creds, _fetch_email(getattr(creds, "token", "")))
    return creds


def _service(api: str, version: str):
    """Build a Google API client. `api` is 'docs' or 'sheets'."""
    libs = _libs()
    creds = _credentials()
    try:
        if libs["AuthorizedHttp"] is not None:
            http = libs["AuthorizedHttp"](creds)
            return libs["build"](api, version, http=http, cache_discovery=False)
        return libs["build"](api, version, credentials=creds, cache_discovery=False)
    except Exception as e:
        raise _AuthError(f"Could not reach the Google {api} API: {e}")


# ── Input helpers ─────────────────────────────────────────────────────────────
# Accepts a raw ID or any Google URL, because people paste the whole address.
_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")


def _extract_id(value: str, what: str) -> str:
    v = (value or "").strip()
    if not v:
        raise _AuthError(f"I need the {what} — either its ID or its full URL.")
    m = _ID_RE.search(v)
    return m.group(1) if m else v


# ── Browser links & last-accessed tracking ────────────────────────────────────
_KIND_PATH = {"sheet": "spreadsheets", "doc": "document"}
_KIND_NOUN = {"sheet": "spreadsheet", "doc": "document"}
_GOOGLE_FILE_RE = re.compile(r"docs\.google\.com/(spreadsheets|document)/d/([a-zA-Z0-9_-]+)")
_BARE_ID_RE = re.compile(r"[a-zA-Z0-9_-]+")


def _file_url(kind: str, file_id: str, email: str = "") -> str:
    """Edit URL for a Doc/Sheet, pinned to `email` via ?authuser= when known."""
    url = f"https://docs.google.com/{_KIND_PATH[kind]}/d/{file_id}/edit"
    if email:
        url += "?authuser=" + urllib.parse.quote(email, safe="@")
    return url


def _remember(kind: str, file_id: str) -> str:
    """Record (and return) the URL of the file we just created or touched."""
    global _LAST_ACCESSED_URL
    _LAST_ACCESSED_URL = _file_url(kind, file_id, _cached_email())
    return _LAST_ACCESSED_URL


def _parse_google_url(value: str) -> tuple[str, str] | None:
    """(kind, id) from a docs.google.com Doc/Sheet URL, else None."""
    m = _GOOGLE_FILE_RE.search(value or "")
    if not m:
        return None
    return ("sheet" if m.group(1) == "spreadsheets" else "doc"), m.group(2)


def _resolve_target(doc_ref: str, sheet_ref: str) -> tuple[str, str] | None:
    """Which file to open: explicit ID/URL first, else the last one touched."""
    for ref, default_kind in ((sheet_ref, "sheet"), (doc_ref, "doc")):
        if not ref:
            continue
        parsed = _parse_google_url(ref)     # a full URL says what it is itself
        if parsed:
            return parsed
        file_id = _extract_id(ref, "document or spreadsheet ID")
        if not _BARE_ID_RE.fullmatch(file_id):
            raise _AuthError("That does not look like a Google Doc or Sheet ID or URL.")
        return default_kind, file_id
    # Rebuilt from kind+id (not reused as-is) so it always carries the CURRENT account.
    return _parse_google_url(_LAST_ACCESSED_URL)


def _open_in_browser(doc_ref: str, sheet_ref: str) -> str:
    global _LAST_ACCESSED_URL
    target = _resolve_target(doc_ref, sheet_ref)
    if target is None:
        return "I don't have a recent document to open. Please specify the name or ID."

    kind, file_id = target
    email = _cached_email()
    if not email:
        _credentials()              # signs in if needed; raises _AuthError with a sentence
        email = _cached_email()

    # Always rebuilt from the ID — a user-supplied URL is never opened verbatim.
    url  = _file_url(kind, file_id, email)
    noun = _KIND_NOUN[kind]

    try:
        opened = webbrowser.open(url)
    except Exception as e:
        print(f"[Workspace] ⚠️ webbrowser.open failed: {type(e).__name__}: {e}")
        opened = False

    if not opened:
        return f"I could not launch a browser. The {noun} is at {url}"

    _LAST_ACCESSED_URL = url
    acct = f" under your account {email}" if email else ""
    return f"Opened the {noun} in your browser{acct}."


def _rows(values) -> list[list]:
    """Coerce the model's `values` into the list-of-lists the Sheets API wants.

    `["a","b"]` means one row; `[["a","b"],["c","d"]]` means two. Both shapes
    turn up depending on how the model fills the schema, so accept either."""
    if not values:
        return []
    if all(isinstance(v, (list, tuple)) for v in values):
        return [list(r) for r in values]
    return [list(values)]


def _cell(value) -> str:
    """Sheets cells arrive as str/float/bool/None; render them for speech."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _doc_text(doc: dict) -> str:
    """Flatten a Docs document body into plain text, tables included."""
    out: list[str] = []

    def _walk(elements) -> None:
        for el in elements or []:
            para = el.get("paragraph")
            if para:
                line = "".join(
                    run.get("textRun", {}).get("content", "")
                    for run in para.get("elements", [])
                )
                out.append(line.rstrip("\n"))
            table = el.get("table")
            if table:
                for row in table.get("tableRows", []):
                    cells = []
                    for cell in row.get("tableCells", []):
                        inner = []
                        for sub in cell.get("content", []):
                            p = sub.get("paragraph")
                            if p:
                                inner.append("".join(
                                    r.get("textRun", {}).get("content", "")
                                    for r in p.get("elements", [])
                                ).strip())
                        cells.append(" ".join(t for t in inner if t))
                    out.append(" | ".join(cells))

    _walk(doc.get("body", {}).get("content", []))
    return "\n".join(out).strip()


def _doc_end_index(doc: dict) -> int:
    """Index just before the document's final newline — where an append lands."""
    body = doc.get("body", {}).get("content", [])
    if not body:
        return 1
    return max(1, int(body[-1].get("endIndex", 2)) - 1)


def _http_error(e: Exception, what: str) -> str:
    """Turn an HttpError into something worth saying out loud."""
    libs   = _LIBS or {}
    HttpError = libs.get("HttpError")
    if HttpError is not None and isinstance(e, HttpError):
        status = getattr(getattr(e, "resp", None), "status", "?")
        if str(status) == "404":
            return f"I could not find that {what} — check the ID or URL."
        if str(status) in ("401", "403"):
            return (f"Google refused access to that {what} (HTTP {status}). "
                    "Make sure the account you signed in with can open it.")
        detail = ""
        try:
            detail = json.loads(e.content.decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        return f"Google returned HTTP {status} for that {what}: {detail or e}"
    return f"{what} failed: {e}"


# ── Source resolution ─────────────────────────────────────────────────────────
# The model must never be asked to retype a file's contents into `content`:
# long text reproduced inside a function-call argument is where truncation and
# paraphrase happen. When a file is on disk we read it here instead, and the
# model only has to name the file.
_FILE_TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".rst", ".csv", ".tsv", ".json", ".yaml",
    ".yml", ".xml", ".html", ".htm", ".log", ".py", ".js", ".ts", ".css",
}


def _read_source_file(path_str: str) -> tuple[str, str]:
    """Return (text, note). `note` is empty when the whole file was read.

    Raises _AuthError only for a path that plainly is not usable, so the caller
    can say so in one sentence instead of failing deep inside the API client."""
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        # Actions run with the project root as cwd, but a bare name is far more
        # likely to mean "the file the user just dropped in".
        path = (BASE_DIR / path)

    if not path.exists():
        raise _AuthError(f"I could not find a file at {path}.")
    if path.is_dir():
        raise _AuthError(f"{path} is a folder, not a file.")

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise _AuthError(f"I could not read {path.name}: {e}")

    note = ""
    if path.suffix.lower() not in _FILE_TEXT_SUFFIXES:
        # Binary-ish or unexpected type: still send it, but tell the user why it
        # may look wrong rather than silently writing mojibake into their Doc.
        note = (f" (note: '{path.suffix or 'no extension'}' is not a plain-text "
                "format, so the content may not look right)")
    return text, note


def _resolve_content(params: dict, player) -> tuple[str, str]:
    """Work out the document body from `source_file`, the dropped-in file, or
    the model's `content` — in that order of trust."""
    src = str(params.get("source_file", "") or "").strip()

    if not src and player is not None:
        # Same fallback main.py applies to file_processor, done here so this
        # tool needs no edit to main.py.
        try:
            src = (getattr(player, "current_file", None) or "").strip()
        except Exception:
            src = ""

    if src:
        text, note = _read_source_file(src)
        if not text.strip():
            raise _AuthError(f"{Path(src).name} is empty — nothing to write.")
        return text, note

    # No file involved: the model is genuinely composing the text, which is fine
    # for short content. Anything long went through the file path above.
    return str(params.get("content", "") or ""), ""


# ── Google Docs ───────────────────────────────────────────────────────────────
# One insertText request carries a bounded amount of text. A whole document in a
# single request risks a rejected payload, so long bodies are inserted in chunks,
# each starting where the previous one ended.
_INSERT_CHUNK = 100_000


def _insert_text(svc, doc_id: str, index: int, text: str) -> None:
    """Insert `text` at `index`, chunked, in one batchUpdate per chunk."""
    for start in range(0, len(text), _INSERT_CHUNK):
        chunk = text[start:start + _INSERT_CHUNK]
        svc.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [
                {"insertText": {"location": {"index": index}, "text": chunk}}
            ]},
        ).execute()
        index += _u16(chunk)


# Markdown-lite styling. The model (or a .md source file) writes "# Title",
# "## Section", "### Sub" and **bold**; the markers are stripped and become real
# Docs styles. Fenced ``` blocks are inserted as-is, unstyled.
_MD_HEADING_RE = re.compile(r"^(#{1,3})[ \t]+(.*\S)[ \t]*$")
_MD_BOLD_RE    = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_STYLE_BATCH   = 400          # style requests per batchUpdate call


def _u16(s: str) -> int:
    """Length in UTF-16 code units — the unit Docs indexes are counted in
    (an emoji is 2, so len() would drift every style range after it)."""
    return len(s.encode("utf-16-le")) // 2


def _parse_markdown(text: str) -> tuple[str, list[tuple[str, int, int, int]]]:
    """→ (plain_text, spans). Each span is (kind, start, end, level) with
    offsets in UTF-16 units from the start of plain_text; kind is
    'heading' (level 1-3) or 'bold'."""
    out_lines: list[str] = []
    spans: list[tuple[str, int, int, int]] = []
    pos, in_fence = 0, False

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue                       # the fence marker itself is dropped

        level, bolds = 0, []
        if in_fence:
            plain = line
        else:
            m = _MD_HEADING_RE.match(line)
            if m:
                level, line = len(m.group(1)), m.group(2)
            out, last = "", 0
            for bm in _MD_BOLD_RE.finditer(line):
                out += line[last:bm.start()]
                b0 = _u16(out)
                out += bm.group(1)
                bolds.append((b0, _u16(out)))
                last = bm.end()
            plain = out + line[last:]

        if level and plain:
            spans.append(("heading", pos, pos + _u16(plain), level))
        for b0, b1 in bolds:
            spans.append(("bold", pos + b0, pos + b1, 0))
        out_lines.append(plain)
        pos += _u16(plain) + 1             # +1 for the newline between lines

    return "\n".join(out_lines), spans


def _markdown_default(params: dict, player) -> bool:
    """Should text read from a FILE be treated as markdown? Only .md files by
    default — a .py or .txt full of '# comment' lines must not become headings."""
    src = str(params.get("source_file", "") or "").strip()
    if not src and player is not None:
        try:
            src = (getattr(player, "current_file", None) or "").strip()
        except Exception:
            src = ""
    if not src:
        return True
    return Path(src).suffix.lower() in (".md", ".markdown")


def _write_doc_text(svc, doc_id: str, index: int, text: str, markdown: bool,
                    lead: str = "", reset: bool = False) -> tuple[int, str]:
    """Insert `lead + text` at `index`, then style it. Returns (characters of
    body text written, note). The text lands first, so a styling failure can
    never lose it — it only adds a sentence to the note."""
    plain, spans = _parse_markdown(text) if markdown else (text, [])
    _insert_text(svc, doc_id, index, lead + plain)
    if not markdown:
        return len(plain), ""

    base = index + _u16(lead)              # where `plain` starts in the document
    reqs: list[dict] = []
    if reset and plain:
        # Appended text inherits the formatting at the insertion point — e.g.
        # the previous heading. Reset the new paragraphs first, then style.
        end = base + _u16(plain)
        reqs.append({"updateParagraphStyle": {
            "range": {"startIndex": base, "endIndex": end},
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "fields": "namedStyleType"}})
        reqs.append({"updateTextStyle": {
            "range": {"startIndex": base, "endIndex": end},
            "textStyle": {"bold": False}, "fields": "bold"}})
    for kind, s, e, level in spans:
        if e <= s:
            continue
        rng = {"startIndex": base + s, "endIndex": base + e}
        if kind == "heading":
            reqs.append({"updateParagraphStyle": {
                "range": rng,
                "paragraphStyle": {"namedStyleType": f"HEADING_{level}"},
                "fields": "namedStyleType"}})
        else:
            reqs.append({"updateTextStyle": {
                "range": rng, "textStyle": {"bold": True}, "fields": "bold"}})
    if not reqs:
        return len(plain), ""

    try:
        for i in range(0, len(reqs), _STYLE_BATCH):
            svc.documents().batchUpdate(
                documentId=doc_id, body={"requests": reqs[i:i + _STYLE_BATCH]}
            ).execute()
    except Exception as e:
        return len(plain), (" The text is in, but styling it failed: "
                            + _http_error(e, "document"))

    heads = sum(1 for k, s, e, _ in spans if k == "heading" and e > s)
    bolds = sum(1 for k, s, e, _ in spans if k == "bold" and e > s)
    if heads or bolds:
        return len(plain), f" Styled {heads} heading(s) and {bolds} bold span(s)."
    return len(plain), ""


def _create_doc(title: str, content: str, markdown: bool = True) -> str:
    svc = _service("docs", "v1")
    doc = svc.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId", "")

    n, note = (_write_doc_text(svc, doc_id, 1, content, markdown)
               if content else (0, ""))

    url = _remember("doc", doc_id)
    return (f"Created the document '{title}'"
            + (f" with {n:,} characters of content" if content else "")
            + f".{note}\n{doc_id}\n{url}")


def _read_doc(document_id: str) -> str:
    svc   = _service("docs", "v1")
    doc   = svc.documents().get(documentId=document_id).execute()
    title = doc.get("title", "Untitled")
    text  = _doc_text(doc)

    if not text:
        return f"'{title}' is empty."
    # Long documents would otherwise be read out in full over the speakers.
    if len(text) > 6000:
        text = text[:6000] + "\n…[truncated — the document is longer than this]"
    return f"'{title}' contains:\n\n{text}"


def _append_doc(document_id: str, text: str, markdown: bool = True) -> str:
    if not text:
        return "There is no text to append."
    svc   = _service("docs", "v1")
    doc   = svc.documents().get(documentId=document_id).execute()
    index = _doc_end_index(doc)

    n, note = _write_doc_text(svc, document_id, index, text, markdown,
                              lead="\n", reset=True)

    title = doc.get("title", "the document")
    return f"Appended {n:,} characters to '{title}'.{note}"


# ── Google Sheets ─────────────────────────────────────────────────────────────
# ── Sheets: styling & charts ──────────────────────────────────────────────────
# Everything below talks to spreadsheets().batchUpdate. Failures are ordinary
# HttpErrors: they propagate to google_workspace(), which turns them into a
# sentence (with Google's own error message) — nothing here can kill the agent.
_DEFAULT_HEADER_BG = "#2B579A"
_BAND_COLOR        = "#EEF3FA"
_OUTER_BORDER      = "#5F6368"
_INNER_BORDER      = "#BDC1C6"
_DARK_TEXT         = "#202124"
_CHART_W, _CHART_H = 600, 371

_NAMED_COLORS = {
    "white": "#FFFFFF", "black": "#000000", "red": "#D93025", "green": "#188038",
    "blue": "#1A73E8", "navy": "#1F3864", "yellow": "#FBBC04", "orange": "#E8710A",
    "purple": "#8E24AA", "gray": "#808080", "grey": "#808080", "teal": "#00897B",
    "pink": "#E91E63", "brown": "#795548",
}

_NUMBER_PRESETS = {
    "usd": ("CURRENCY", '"$"#,##0.00'), "$": ("CURRENCY", '"$"#,##0.00'),
    "dollar": ("CURRENCY", '"$"#,##0.00'), "currency": ("CURRENCY", '"$"#,##0.00'),
    "bdt": ("CURRENCY", '"\u09f3"#,##0.00'), "\u09f3": ("CURRENCY", '"\u09f3"#,##0.00'),
    "taka": ("CURRENCY", '"\u09f3"#,##0.00'),
    "eur": ("CURRENCY", '"\u20ac"#,##0.00'), "\u20ac": ("CURRENCY", '"\u20ac"#,##0.00'),
    "gbp": ("CURRENCY", '"\u00a3"#,##0.00'), "\u00a3": ("CURRENCY", '"\u00a3"#,##0.00'),
    "percent": ("PERCENT", "0.00%"), "percentage": ("PERCENT", "0.00%"),
    "%": ("PERCENT", "0.00%"),
    "number": ("NUMBER", "#,##0.00"), "integer": ("NUMBER", "#,##0"),
    "date": ("DATE", "yyyy-mm-dd"),
}

_CHART_ALIASES = {
    "": "COLUMN", "COLUMNS": "COLUMN", "VERTICALBAR": "COLUMN",
    "BARS": "BAR", "HORIZONTALBAR": "BAR", "LINES": "LINE", "PIES": "PIE",
    "DONUT": "PIE",
}


def _opt_bool(value) -> bool | None:
    """True/False for bool-ish input, None when absent or unrecognised."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("true", "yes", "1", "on"):
        return True
    if s in ("false", "no", "0", "off"):
        return False
    return None


def _parse_color(value) -> dict | None:
    """'#2B579A' / '2b579a' / '#fff' / 'navy' / 'rgb(43,87,154)' → Google's
    {red, green, blue} (0.0–1.0). None if it cannot be read — never raises."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    s = _NAMED_COLORS.get(s, s).lower()
    m = re.fullmatch(r"#?([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})", s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))   # alpha ignored
    else:
        m = re.fullmatch(r"(?:rgb\()?\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)?", s)
        if not m:
            return None
        r, g, b = (min(int(x), 255) / 255 for x in m.groups())
    return {"red": round(r, 4), "green": round(g, 4), "blue": round(b, 4)}


def _color_or_default(value, default_hex: str, notes: list, label: str) -> dict:
    """Parse `value`; fall back to the default (and say so) if it is unreadable."""
    if value not in (None, ""):
        c = _parse_color(value)
        if c is not None:
            return c
        notes.append(f"I could not read the {label} '{value}', so I used the default.")
    return _parse_color(default_hex)


def _is_dark(color: dict) -> bool:
    return (0.299 * color["red"] + 0.587 * color["green"] + 0.114 * color["blue"]) < 0.6


# -- A1 notation → GridRange ---------------------------------------------------
_CELL_RE = re.compile(r"([A-Za-z]{0,3})(\d{0,7})")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _col_letters(index: int) -> str:
    out, n = "", index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _split_sheet(range_name: str) -> tuple[str | None, str]:
    """"'My Tab'!A1:C5" → ('My Tab', 'A1:C5'). No '!' → (None, whole string)."""
    r = (range_name or "").strip()
    if "!" not in r:
        return None, r
    title, a1 = r.rsplit("!", 1)
    title = title.strip()
    if len(title) >= 2 and title[0] == "'" and title[-1] == "'":
        title = title[1:-1].replace("''", "'")
    return title, a1.strip()


def _parse_a1(a1: str) -> dict | None:
    """'A1:D10', 'A:C', '2:9', 'C' or 'B2' → {r0, r1, c0, c1}; r1/c1 are
    exclusive ends, any value may be None (= unbounded). None if unreadable."""
    parts = (a1 or "").replace("$", "").split(":")
    if not a1 or len(parts) > 2:
        return None

    def cell(p: str):
        m = _CELL_RE.fullmatch(p.strip())
        if not m or not (m.group(1) or m.group(2)):
            return None
        row = int(m.group(2)) - 1 if m.group(2) else None
        if row is not None and row < 0:
            return None
        return (_col_index(m.group(1)) if m.group(1) else None), row

    a = cell(parts[0])
    b = cell(parts[1]) if len(parts) == 2 else a
    if a is None or b is None:
        return None

    def span(x, y):
        if x is not None and y is not None and y < x:
            x, y = y, x
        return x, (y + 1 if y is not None else None)

    c0, c1 = span(a[0], b[0])
    r0, r1 = span(a[1], b[1])
    return {"r0": r0, "r1": r1, "c0": c0, "c1": c1}


def _a1_text(grid: dict, tab: str = "") -> str:
    text = (f"{_col_letters(grid['startColumnIndex'])}{grid['startRowIndex'] + 1}:"
            f"{_col_letters(grid['endColumnIndex'] - 1)}{grid['endRowIndex']}")
    return f"{tab}!{text}" if tab else text


def _overlaps(a: dict, b: dict) -> bool:
    def span(g, lo, hi):
        return g.get(lo, 0), g.get(hi, 10 ** 9)
    ar0, ar1 = span(a, "startRowIndex", "endRowIndex")
    br0, br1 = span(b, "startRowIndex", "endRowIndex")
    ac0, ac1 = span(a, "startColumnIndex", "endColumnIndex")
    bc0, bc1 = span(b, "startColumnIndex", "endColumnIndex")
    return ar0 < br1 and br0 < ar1 and ac0 < bc1 and bc0 < ac1


def _resolve_range(svc, spreadsheet_id: str, range_name: str) -> tuple[dict, dict]:
    """Turn a user range into a fully bounded GridRange plus its sheet's metadata.

    Empty range = the used area of the first tab. Open ends ('A:D', 'A1:A') are
    closed at the last row/column that actually holds data, so banding and
    borders never spill down a thousand empty rows."""
    meta = svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields=("sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)),"
                "bandedRanges(bandedRangeId,range))"),
    ).execute()
    sheets = meta.get("sheets", [])
    if not sheets:
        raise _AuthError("That spreadsheet has no sheets.")

    title, a1 = _split_sheet(range_name)
    parsed = None
    if title is None and a1:
        parsed = _parse_a1(a1)
        if parsed is None:
            title, a1 = a1, ""          # not a cell range, so it names a tab
    elif a1:
        parsed = _parse_a1(a1)
        if parsed is None:
            raise _AuthError(f"I could not read the range '{range_name}'.")

    if title:
        entry = next((s for s in sheets
                      if s["properties"].get("title", "").lower() == title.lower()), None)
        if entry is None:
            raise _AuthError(f"There is no sheet tab called '{title}'.")
    else:
        entry = sheets[0]

    props = entry["properties"]
    tab   = props.get("title", "")
    p     = parsed or {"r0": None, "r1": None, "c0": None, "c1": None}
    r0    = p["r0"] if p["r0"] is not None else 0
    c0    = p["c0"] if p["c0"] is not None else 0
    r1, c1 = p["r1"], p["c1"]

    if r1 is None or c1 is None:
        vals = svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range="'" + tab.replace("'", "''") + "'",
        ).execute().get("values", [])
        if r1 is None:
            r1 = len(vals)
        if c1 is None:
            c1 = max((len(r) for r in vals), default=0)

    if r1 <= r0 or c1 <= c0:
        raise _AuthError("There is no data in that range yet — write some values first.")

    grid = {"sheetId": props["sheetId"], "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}
    return grid, entry


def _number_format(spec: str) -> tuple[str, str]:
    """'usd' / 'bdt' / 'percent' / a raw pattern like '#,##0.0' → (type, pattern)."""
    s = spec.strip()
    return _NUMBER_PRESETS.get(s.lower(), ("NUMBER", s))


def _style_from_params(params: dict) -> dict:
    return {
        "header_bg":     params.get("header_bg_color"),
        "header_fg":     params.get("header_text_color"),
        "header_align":  params.get("header_align"),
        "banding":       _opt_bool(params.get("banding")),
        "borders":       _opt_bool(params.get("borders")),
        "autofit":       _opt_bool(params.get("auto_fit_columns")),
        "number_format": params.get("number_format"),
        "number_range":  params.get("number_format_range"),
    }


def _sheet_id_or_last(sheet_ref: str) -> str:
    """Explicit ID/URL, else the spreadsheet we touched last ('format it')."""
    if (sheet_ref or "").strip():
        return _extract_id(sheet_ref, "spreadsheet ID or URL")
    last = _parse_google_url(_LAST_ACCESSED_URL)
    if last and last[0] == "sheet":
        return last[1]
    raise _AuthError("Which spreadsheet? Give me its ID or URL.")


def _format_sheet(spreadsheet_id: str, range_name: str, style: dict, svc=None) -> str:
    """Make a table presentation-ready. Every switch defaults ON, so a bare
    format_sheet call produces the full polished look; pass false to drop one."""
    svc = svc or _service("sheets", "v4")
    grid, entry = _resolve_range(svc, spreadsheet_id, range_name)
    tab = entry["properties"].get("title", "")
    sid = grid["sheetId"]
    r0, r1 = grid["startRowIndex"], grid["endRowIndex"]
    c0, c1 = grid["startColumnIndex"], grid["endColumnIndex"]
    notes: list[str] = []
    steps: list[str] = []
    reqs:  list[dict] = []

    # Header row: fill, bold text, contrasting text colour, alignment.
    bg = _color_or_default(style.get("header_bg"), _DEFAULT_HEADER_BG, notes, "header color")
    fg_raw = style.get("header_fg")
    fg = _parse_color(fg_raw) if fg_raw not in (None, "") else None
    if fg is None:
        if fg_raw not in (None, ""):
            notes.append(f"I could not read the header text color '{fg_raw}', "
                         "so I picked one that contrasts with the fill.")
        fg = _parse_color("#FFFFFF" if _is_dark(bg) else _DARK_TEXT)
    align = str(style.get("header_align") or "CENTER").strip().upper()
    if align not in ("LEFT", "CENTER", "RIGHT"):
        notes.append(f"Header alignment '{align}' is not LEFT, CENTER or RIGHT; I centred it.")
        align = "CENTER"

    header = {**grid, "endRowIndex": r0 + 1}
    reqs.append({"repeatCell": {
        "range": header,
        "cell": {"userEnteredFormat": {
            "backgroundColor": bg,
            "horizontalAlignment": align,
            "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True, "foregroundColor": fg},
        }},
        "fields": ("userEnteredFormat(backgroundColor,horizontalAlignment,"
                   "verticalAlignment,textFormat)"),
    }})
    steps.append("styled header")

    if r0 == 0:
        reqs.append({"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }})
        steps.append("frozen header row")

    # Alternating row colours. A banded range may not overlap another, so any
    # existing one touching this table is removed first (makes re-runs safe).
    if style.get("banding") is not False and r1 - r0 >= 2:
        for b in entry.get("bandedRanges", []):
            if _overlaps(b.get("range", {}), grid):
                reqs.append({"deleteBanding": {"bandedRangeId": b["bandedRangeId"]}})
        reqs.append({"addBanding": {"bandedRange": {
            "range": grid,
            "rowProperties": {
                "headerColor":     bg,
                "firstBandColor":  _parse_color("#FFFFFF"),
                "secondBandColor": _parse_color(_BAND_COLOR),
            },
        }}})
        steps.append("banded rows")

    # Outer frame + thin inner dividers.
    if style.get("borders") is not False:
        outer = {"style": "SOLID_MEDIUM", "color": _parse_color(_OUTER_BORDER)}
        inner = {"style": "SOLID", "color": _parse_color(_INNER_BORDER)}
        reqs.append({"updateBorders": {
            "range": grid, "top": outer, "bottom": outer, "left": outer, "right": outer,
            "innerHorizontal": inner, "innerVertical": inner,
        }})
        steps.append("borders")

    # Currency / percent / number formats on an explicit range.
    nf = style.get("number_format")
    if nf not in (None, ""):
        nr_raw = style.get("number_range")
        if not nr_raw:
            notes.append("Number format skipped: say which columns or cells it applies to "
                         "(number_format_range, for example 'C:D').")
        else:
            p = _parse_a1(_split_sheet(str(nr_raw))[1])
            if p is None:
                notes.append(f"I could not read the number format range '{nr_raw}'.")
            else:
                nr = {"sheetId": sid,
                      "startRowIndex":    p["r0"] if p["r0"] is not None else r0 + 1,
                      "endRowIndex":      p["r1"] if p["r1"] is not None else r1,
                      "startColumnIndex": p["c0"] if p["c0"] is not None else c0,
                      "endColumnIndex":   p["c1"] if p["c1"] is not None else c1}
                ntype, pattern = _number_format(str(nf))
                reqs.append({"repeatCell": {
                    "range": nr,
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": ntype, "pattern": pattern}}},
                    "fields": "userEnteredFormat.numberFormat",
                }})
                steps.append(f"{ntype.lower()} format on {_a1_text(nr)}")

    # Last on purpose: widths are measured AFTER bold header and number formats.
    if style.get("autofit") is not False:
        reqs.append({"autoResizeDimensions": {"dimensions": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c1,
        }}})
        steps.append("fitted column widths")

    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": reqs}
    ).execute()

    msg = f"Formatted {_a1_text(grid, tab)}: {', '.join(steps)}."
    return msg + ("".join(" " + n for n in notes))


def _norm_chart_type(value) -> str:
    s = re.sub(r"[^A-Z]", "", str(value or "").upper()).replace("CHART", "")
    s = _CHART_ALIASES.get(s, s)
    if s not in ("COLUMN", "BAR", "LINE", "PIE"):
        raise _AuthError("Chart type must be COLUMN, BAR, LINE or PIE.")
    return s


def _add_sheet_chart(spreadsheet_id: str, data_range: str, chart_type: str,
                     title: str, position: str) -> str:
    """Chart over `data_range`: first column = labels, first row = series names,
    every further column = one series (a PIE uses only the first series)."""
    kind = _norm_chart_type(chart_type)
    if not (data_range or "").strip():
        raise _AuthError("I need the data range for the chart, such as 'Sheet1!A1:B10'.")

    svc = _service("sheets", "v4")
    grid, entry = _resolve_range(svc, spreadsheet_id, data_range)
    tab = entry["properties"].get("title", "")
    sid = grid["sheetId"]
    r0, r1 = grid["startRowIndex"], grid["endRowIndex"]
    c0, c1 = grid["startColumnIndex"], grid["endColumnIndex"]
    if c1 - c0 < 2 or r1 - r0 < 2:
        raise _AuthError("A chart needs a label column, at least one value column, "
                         "and a header row above the data.")

    def rng(row0, row1, col0, col1):
        return {"sheetId": sid, "startRowIndex": row0, "endRowIndex": row1,
                "startColumnIndex": col0, "endColumnIndex": col1}

    def src(g):
        return {"sourceRange": {"sources": [g]}}

    if kind == "PIE":
        # PieChartSpec has no header concept, so its ranges skip the header row.
        spec = {"pieChart": {
            "legendPosition": "RIGHT_LEGEND",
            "domain": src(rng(r0 + 1, r1, c0, c0 + 1)),
            "series": src(rng(r0 + 1, r1, c0 + 1, c0 + 2)),
        }}
    else:
        axis = "BOTTOM_AXIS" if kind == "BAR" else "LEFT_AXIS"   # bars run sideways
        series = [{"series": src(rng(r0, r1, c, c + 1)), "targetAxis": axis}
                  for c in range(c0 + 1, c1)]
        spec = {"basicChart": {
            "chartType": kind,
            "legendPosition": "BOTTOM_LEGEND" if len(series) > 1 else "NO_LEGEND",
            "headerCount": 1,
            "domains": [{"domain": src(rng(r0, r1, c0, c0 + 1))}],
            "series": series,
        }}
    if (title or "").strip():
        spec["title"] = title.strip()

    # Default anchor: just right of the data. If that falls off the tab's last
    # column, drop below the data instead.
    note = ""
    col_count = entry["properties"].get("gridProperties", {}).get("columnCount", 26)
    anchor_row, anchor_col = r0, c1 + 1
    if anchor_col >= col_count:
        anchor_row, anchor_col = r1 + 1, c0
    if (position or "").strip():
        p = _parse_a1(_split_sheet(position)[1])
        if p and p["r0"] is not None and p["c0"] is not None:
            anchor_row, anchor_col = p["r0"], p["c0"]
        else:
            note = f" I could not read the position '{position}', so I placed it automatically."

    res = svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addChart": {"chart": {
            "spec": spec,
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": sid, "rowIndex": anchor_row,
                               "columnIndex": anchor_col},
                "widthPixels": _CHART_W, "heightPixels": _CHART_H,
            }},
        }}}]},
    ).execute()

    label = f" titled '{title.strip()}'" if (title or "").strip() else ""
    where = f"{_col_letters(anchor_col)}{anchor_row + 1}"
    return (f"Added a {kind.lower()} chart{label} of {_a1_text(grid, tab)} "
            f"to {tab}, anchored at {where}.{note}")


def _create_sheet(title: str, values=None, style: dict | None = None) -> str:
    """Create a spreadsheet. With `values` (header row first) it also fills the
    first tab and applies the polished default styling in the same call."""
    svc = _service("sheets", "v4")
    sh  = svc.spreadsheets().create(
        body={"properties": {"title": title}}
    ).execute()
    sid = sh.get("spreadsheetId", "")
    url = _remember("sheet", sid)
    msg = f"Created the spreadsheet '{title}'."

    rows = _rows(values)
    if rows:
        # The sheet already exists; a failure past this point must still hand
        # back its ID and link instead of losing it.
        try:
            svc.spreadsheets().values().update(
                spreadsheetId=sid, range="A1", valueInputOption="USER_ENTERED",
                body={"values": rows},
            ).execute()
            msg += f" Wrote {len(rows)} row(s)."
            msg += " " + _format_sheet(sid, "", style or {}, svc=svc)
        except _AuthError as e:
            msg += f" Styling skipped: {e}"
        except Exception as e:
            msg += (" The sheet exists, but filling or styling it failed: "
                    + _http_error(e, "spreadsheet"))
    return f"{msg}\n{sid}\n{url}"


def _read_sheet(spreadsheet_id: str, range_name: str) -> str:
    svc = _service("sheets", "v4")
    res = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_name or "A1:Z100"
    ).execute()
    values = res.get("values", [])
    if not values:
        return f"'{range_name or 'A1:Z100'}' is empty."

    lines = []
    for row in values:
        lines.append(" | ".join(_cell(c) for c in row))
    body = "\n".join(lines)
    if len(body) > 6000:
        body = body[:6000] + "\n…[truncated]"
    return f"{len(values)} row(s) from {range_name or 'A1:Z100'}:\n\n{body}"


def _append_sheet_row(spreadsheet_id: str, range_name: str, values) -> str:
    rows = _rows(values)
    if not rows:
        return "There are no values to append."
    svc = _service("sheets", "v4")
    res = svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name or "A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()
    updated = res.get("updates", {})
    return (f"Appended {len(rows)} row(s) to {updated.get('updatedRange', range_name)}.")


def _update_sheet_cells(spreadsheet_id: str, range_name: str, values) -> str:
    rows = _rows(values)
    if not rows:
        return "There are no values to write."
    if not range_name:
        raise _AuthError("I need a range to write into, such as 'Sheet1!A1'.")
    svc = _service("sheets", "v4")
    res = svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
    return (f"Updated {res.get('updatedCells', 0)} cell(s) in "
            f"{res.get('updatedRange', range_name)}.")


# ── Public entry point ────────────────────────────────────────────────────────
def google_workspace(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params      = parameters or {}
    action_type = str(params.get("action_type", "")).strip().lower()

    title       = str(params.get("title", "")).strip()
    doc_ref     = str(params.get("document_id", "")).strip()
    sheet_ref   = str(params.get("spreadsheet_id", "")).strip()
    range_name  = str(params.get("range_name", "")).strip()
    values      = params.get("values") or []
    text        = str(params.get("text", ""))

    if player:
        player.write_log(f"[Workspace] {action_type or '(no action)'}")

    print(f"[Workspace] 📄 action_type={action_type!r}")

    try:
        # create_doc / append_doc may take their body from a file on disk, so
        # the model never retypes it. Resolved only for those two actions.
        content, src_note = "", ""
        had_text = bool(text)
        if action_type == "create_doc":
            content, src_note = _resolve_content(params, player)
        elif action_type == "append_doc" and not text:
            text, src_note = _resolve_content(params, player)

        # Markdown styling: always on for text the model composes; for text read
        # from a file only for .md (override with format_markdown).
        use_md = _opt_bool(params.get("format_markdown"))
        if use_md is None:
            from_file = action_type == "create_doc" or (
                action_type == "append_doc" and not had_text)
            use_md = _markdown_default(params, player) if from_file else True

        if action_type == "create_doc":
            return _create_doc(title or "Untitled document", content, use_md) + src_note

        if action_type == "read_doc":
            doc_id = _extract_id(doc_ref, "document ID or URL")
            result = _read_doc(doc_id)
            _remember("doc", doc_id)
            return result

        if action_type == "append_doc":
            doc_id = _extract_id(doc_ref, "document ID or URL")
            result = _append_doc(doc_id, text, use_md) + src_note
            _remember("doc", doc_id)
            return result

        if action_type == "create_sheet":
            return _create_sheet(title or "Untitled spreadsheet", values,
                                 _style_from_params(params))

        if action_type == "read_sheet":
            sheet_id = _extract_id(sheet_ref, "spreadsheet ID or URL")
            result = _read_sheet(sheet_id, range_name)
            _remember("sheet", sheet_id)
            return result

        if action_type == "append_sheet_row":
            sheet_id = _extract_id(sheet_ref, "spreadsheet ID or URL")
            result = _append_sheet_row(sheet_id, range_name, values)
            _remember("sheet", sheet_id)
            return result

        if action_type == "update_sheet_cells":
            sheet_id = _extract_id(sheet_ref, "spreadsheet ID or URL")
            result = _update_sheet_cells(sheet_id, range_name, values)
            _remember("sheet", sheet_id)
            return result

        if action_type == "format_sheet":
            sheet_id = _sheet_id_or_last(sheet_ref)
            result = _format_sheet(sheet_id, range_name, _style_from_params(params))
            _remember("sheet", sheet_id)
            return result

        if action_type == "add_sheet_chart":
            sheet_id = _sheet_id_or_last(sheet_ref)
            result = _add_sheet_chart(
                sheet_id,
                str(params.get("chart_data_range") or range_name or "").strip(),
                str(params.get("chart_type") or "").strip(),
                str(params.get("chart_title") or title or "").strip(),
                str(params.get("chart_position") or "").strip(),
            )
            _remember("sheet", sheet_id)
            return result

        if action_type == "open_in_browser":
            return _open_in_browser(doc_ref, sheet_ref)

        if not action_type:
            return ("Tell me what to do with Google Workspace: create_doc, "
                    "read_doc, append_doc, create_sheet, read_sheet, "
                    "append_sheet_row, update_sheet_cells, format_sheet, "
                    "add_sheet_chart, or open_in_browser.")
        return f"Unknown Google Workspace action: {action_type}"

    except _AuthError as e:
        # Expected failures — setup missing, consent declined, no such file.
        # These are answers, not bugs, so they are logged and spoken plainly.
        print(f"[Workspace] ⚠️ {e}")
        return str(e)
    except Exception as e:
        # Anything else (a dropped connection, a malformed range) still comes
        # back as a sentence so the session survives it.
        print(f"[Workspace] ❌ {type(e).__name__}: {e}")
        return _http_error(e, "Google Workspace request")


# ── Tool declaration (auto-discovered by core/action_loader.py) ───────────────
TOOL = {
    "name": "google_workspace",
    "description": (
        "Creates, reads and edits Google Docs and Google Sheets in the user's "
        "own Google account. Use this whenever the user asks to make, open, "
        "read, add to, or update a document or spreadsheet — e.g. 'write this "
        "into a Google Doc', 'add a row to my sheet', 'what does my budget "
        "sheet say'. Pick action_type first, then fill only the fields that "
        "action needs. For the *_doc actions supply document_id (an ID or a "
        "full docs.google.com URL); for the *_sheet actions supply "
        "spreadsheet_id (an ID or a full sheets.google.com URL). "
        "To show the user a file in their browser ('open it', 'show me the "
        "sheet') use open_in_browser: it opens the given document_id / "
        "spreadsheet_id, or the most recently created or used file when none "
        "is given, under the signed-in Google account. "
        "POLISH IS THE DEFAULT. Whenever you design or fill a spreadsheet, make "
        "it polished and presentation-ready: pass the rows (header first) as "
        "create_sheet's values — it styles the new sheet automatically — or, "
        "for a sheet that already has data, call format_sheet afterwards. That "
        "gives a dark header with contrasting bold text, banded rows, borders, "
        "a frozen header row and fitted column widths. Use number_format + "
        "number_format_range for money or percentages (percent cells must hold "
        "fractions, 0.25 for 25%). Call add_sheet_chart when the user wants a "
        "chart or the data is naturally a comparison, trend or share. "
        "format_sheet and add_sheet_chart use the most recently used "
        "spreadsheet when none is named. In documents, write headings as lines "
        "starting '# ', '## ' or '### ' and bold as **text** — they become "
        "real Google Docs headings and bold. "
        "IMPORTANT: when the user refers to a file on disk, pass its path as "
        "source_file and leave content/text empty — the file is read from disk "
        "verbatim. Never retype or summarise a file's contents into content: "
        "long text copied by hand comes out truncated."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action_type": {
                "type": "STRING",
                "description": (
                    "Which operation to run. Docs: create_doc | read_doc | "
                    "append_doc. Sheets: create_sheet | read_sheet | "
                    "append_sheet_row | update_sheet_cells | format_sheet | "
                    "add_sheet_chart. Browser: open_in_browser."
                )
            },
            "title": {
                "type": "STRING",
                "description": "Name for a new document or spreadsheet (create_doc, create_sheet)."
            },
            "source_file": {
                "type": "STRING",
                "description": (
                    "Path to a file on disk whose contents should become the "
                    "document body (create_doc, append_doc). ALWAYS prefer this "
                    "over retyping: when the user points at a file — 'write this "
                    "markdown file into a Doc', 'put report.md in there' — pass "
                    "its path here and leave content/text empty. Leave blank to "
                    "use the file currently dropped onto the interface."
                )
            },
            "content": {
                "type": "STRING",
                "description": (
                    "Body text for a new document (create_doc), typed directly. "
                    "Use only for short text the user spoke or that you are "
                    "composing. For a file, use source_file instead — do NOT "
                    "copy a file's contents in here."
                )
            },
            "document_id": {
                "type": "STRING",
                "description": (
                    "Google Doc ID or full URL (read_doc, append_doc, open_in_browser). "
                    "Example: https://docs.google.com/document/d/<ID>/edit"
                )
            },
            "text": {
                "type": "STRING",
                "description": (
                    "Text to add to the end of an existing document (append_doc). "
                    "Use source_file instead when the text lives in a file."
                )
            },
            "spreadsheet_id": {
                "type": "STRING",
                "description": (
                    "Google Sheet ID or full URL (read_sheet, append_sheet_row, "
                    "update_sheet_cells, open_in_browser). "
                    "Example: https://docs.google.com/spreadsheets/d/<ID>/edit"
                )
            },
            "range_name": {
                "type": "STRING",
                "description": (
                    "A1-notation range, e.g. 'Sheet1!A1:C10'. Read: optional "
                    "(defaults to the first 100 rows). Append: optional (the "
                    "sheet to append to). Update: required — it is the target."
                )
            },
            "header_bg_color": {
                "type": "STRING",
                "description": "Header row fill as hex, e.g. '#2B579A' (the default). create_sheet with values, format_sheet."
            },
            "header_text_color": {
                "type": "STRING",
                "description": "Header text colour as hex, e.g. '#FFFFFF'. Omit to auto-pick white or dark for contrast."
            },
            "header_align": {
                "type": "STRING",
                "description": "Header alignment: CENTER (default) | LEFT | RIGHT."
            },
            "banding": {
                "type": "BOOLEAN",
                "description": "Alternating row shading. On by default; pass false to turn off."
            },
            "borders": {
                "type": "BOOLEAN",
                "description": "Outer border plus inner dividers. On by default; pass false to turn off."
            },
            "auto_fit_columns": {
                "type": "BOOLEAN",
                "description": "Resize columns to fit their text. On by default; pass false to turn off."
            },
            "number_format": {
                "type": "STRING",
                "description": "Format for number_format_range: usd | bdt | eur | gbp | percent | number | integer | date, or a raw pattern like '#,##0.0'."
            },
            "number_format_range": {
                "type": "STRING",
                "description": "Cells that get number_format, e.g. 'C:D' or 'Sheet1!C2:C20'. Required when number_format is set."
            },
            "chart_type": {
                "type": "STRING",
                "description": "add_sheet_chart: COLUMN | BAR | LINE | PIE (default COLUMN)."
            },
            "chart_title": {
                "type": "STRING",
                "description": "add_sheet_chart: title shown on the chart."
            },
            "chart_data_range": {
                "type": "STRING",
                "description": "add_sheet_chart: A1 range including the header row, e.g. 'Sheet1!A1:B10'. First column = labels, further columns = series."
            },
            "chart_position": {
                "type": "STRING",
                "description": "add_sheet_chart: cell where the chart's top-left corner goes, e.g. 'F2'. Default: just right of the data."
            },
            "format_markdown": {
                "type": "BOOLEAN",
                "description": "create_doc / append_doc: turn '# ' headings and **bold** into Docs styles. Default true for typed text and .md files, false for other files."
            },
            "values": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": (
                    "Cell values for create_sheet (initial rows, header first), "
                    "append_sheet_row and update_sheet_cells. "
                    "One flat list is a single row, e.g. ['Alice', '42']; nest "
                    "lists for several rows."
                )
            }
        },
        "required": ["action_type"]
    },
    "handler": google_workspace,
}
