# JARVIS — Module-to-Module Connection Map

A dependency map of the JARVIS codebase: what each file imports, what it exports,
who consumes those exports, and how data flows from the agent loop through the
tool handlers to the Gemini API wrapper and the model router.

> Line numbers reference the tree as of 2026-10-13. Root: `D:\Claude Project\JARVIS`.
> Changes since 2026-10-12: Study Station added (`plugins/study_mentor.py`,
> `core/study_guard.py`, `core/study_canvas.py`, `runtime/study_board.html`,
> `tools/fetch_study_vendor.py`); `core/model_router.py` documented; `core/gemini.py`
> is no longer a pure leaf (lazy edge to `model_router`); `prompt.txt` `[STUDY MODE]`
> contract added.

---

## 1. Core module inventory

| Folder | Role | Entry points |
|---|---|---|
| `main.py` | The agent. Owns the Live session, the mic/speaker loops, tool dispatch. | `main()`, `class JarvisLive` |
| `ui.py` | PyQt6 HUD window, avatar, settings panels, content panel, camera stream, **Study Station layout switch**. | `class MainWindow` (Qt side), `class JarvisUI` (thread-safe facade) |
| `core/` | Infrastructure: API wrapper, model router, loaders, audio pipeline, vision, safety. | `gemini`, `model_router`, `action_loader`, `plugin_loader`, … |
| `actions/` | Auto-discovered tools, one file = one `TOOL` dict. | `discover_actions()` |
| `plugins/` | Auto-discovered user plugins, one file = one `PLUGIN` dict + `run()`. | `discover_plugins()` |
| `memory/` | Long-term JSON memory + all user-facing config flags. | `memory_manager`, `config_manager` |
| `dashboard/` | Phone/remote web server (FastAPI + WebSocket). | `class DashboardServer` |
| `config/` | OS detection + `api_keys.json` accessor. | `get_os()`, `is_windows()` |
| `runtime/` | Static assets loaded at runtime (not Python). `study_board.html` + `vendor/` (KaTeX, Tailwind, Plotly, filled by `tools/fetch_study_vendor.py`). | read by `core/study_canvas.py` |
| `tools/` | Standalone dev/calibration/setup CLIs (not part of runtime). | `calibrate.py`, `target_debug.py`, `fetch_study_vendor.py` |
| `prompt.txt` | System prompt template (`{assistant_name}`, `{platform}`, `{limits}` filled at startup). `[STUDY MODE]` defines the `screen_process` → `study_mode` contract. | loaded by `main.py` |

### `core/` at a glance

| File | Exports (consumed elsewhere) | Consumed by |
|---|---|---|
| `gemini.py` | `call`, `text`, `as_json`, `api_key`, `client`, `FAST/SMART/SEARCH/LIVE`, `is_*_error` | 13 files (see §3) |
| `model_router.py` | `call`, `as_json`, `status`, `fallback_text`, `DEFAULT_RULES` | `plugins/study_mentor.py` (direct); `core/gemini.py` (lazy: `text()` and the `call()` fallback) |
| `study_guard.py` | `set_study_active`, `study_active`, `camera_locked`, `require_camera`, `CameraLocked`, `CAMERA_REFUSAL` | `main.py`, `ui.py`; imported (unused) by `plugins/study_mentor.py` |
| `study_canvas.py` | `StudyCanvasWidget`, `StudyBridge`, `HAVE_STUDY`, `BOARD_HTML` | `ui.py` (module-top import) |
| `action_loader.py` | `discover_actions`, `ActionRegistry`, `ActionRecord` | `main.py` |
| `plugin_loader.py` | `discover_plugins`, `PluginRegistry`, `PluginRecord` | `main.py` |
| `screen_agent.py` | `run` / agent loop helpers | `actions/computer_control.py` |
| `ui_grounding.py` | element finders (UIA → OCR → vision) | `computer_control`, `screen_agent`, `screen_geometry`, `tools/*` |
| `screen_geometry.py` | `ensure_dpi_awareness`, `describe`, capture helpers | `computer_control`, `screen_agent`, `target_overlay`, `ui_grounding`, `main`, `tools/*` |
| `undo.py` | `push_undo`, `undo_last`, `history` | `computer_settings`, `file_controller` |
| `confirm.py` | confirmation gate | `computer_settings`, `file_access`, `self_dev`, `ui` |
| `audio_devices.py` | `list_devices`, `DEFAULT_LABEL`, `prefetch` | `ui.py` |
| `echo.py` | `EchoGuard` | `main.py` |
| `barge_in.py` | `BargeInDetector` | `main.py` |
| `noise_gate.py` | `NoiseGate` | `main.py` |
| `viseme.py` | `VisemeStream` | `main.py` |
| `wake_word.py` | `WakeWordDetector`, `is_ready`, `install_and_download` | `main.py`, `ui.py` |
| `hotkey.py` | `PushToTalk`, `chord_label` | `main.py`, `ui.py` |
| `avatar.py` / `avatar_mesh.py` | `HoloAvatar`, `get_head_mesh` | `ui.py`; `avatar.py` |
| `target_overlay.py` | `TargetOverlay` | `ui.py`, `tools/calibrate.py` |
| `ui_readability.py` | font/contrast helpers | `ui.py` |
| `stt.py`, `tts.py`, `llm_client.py`, `installer.py` | **Orphaned** — no importers in the tree | — |

---

## 2. The three-layer spine

```
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — AGENT LOGIC            main.py :: class JarvisLive        │
│  • _build_config()   → assembles LiveConnectConfig + tool decls      │
│  • _listen_audio()   → mic → PCM chunks → session.send_realtime_input│
│  • _receive_audio()  → session.receive() → text / tool_call / audio  │
│  • _execute_tool()   → dispatch to inline / actions / plugins        │
│  • _play_audio()     → PCM → speakers, drives visemes + barge-in     │
└───────────────┬───────────────────────────────┬─────────────────────┘
                │ tool_call.function_calls      │ generate / live turns
                ▼                               ▼
┌───────────────────────────────┐   ┌─────────────────────────────────┐
│  LAYER 2 — TOOL HANDLERS      │   │  LAYER 3 — MODEL WRAPPERS       │
│  actions/*.py   (TOOL dict)   │──▶│  core/gemini.py                 │
│  plugins/*.py   (PLUGIN dict) │   │    call() → _LADDERS[FAST|SMART]│
│  inline in main.py            │   │    _live_call() → Live API      │
│                               │──▶│  core/model_router.py           │
│                               │   │    call() → rules[task] chain   │
│                               │   │    openrouter / groq / gemini   │
└───────────────────────────────┘   └─────────────────────────────────┘
```

**Rule of the design:** only tools tied to *live-session state* live inline in
`main.py` (`screen_process`, `close_camera`, `save_memory`, `manage_monitor`,
`shutdown_jarvis`, `system_status`, `recall_memory`, `undo`). Everything else
self-describes and is auto-discovered. `main.py` imports the file-backed ones
only for side-effect helpers it calls directly (`_capture_screen`, `add_monitor`,
`SystemMonitor`, …) — not for tool declaration.

**Two Layer-3 routes.** `core/gemini.py` is the Gemini-first ladder (Live rung,
then pinned REST models, key rotation, cooldowns). `core/model_router.py` is the
provider-neutral task router (OpenRouter / Groq / Gemini, per-task chains,
per-provider key pools). They are connected one way: `gemini` → `model_router`
(lazy), never the reverse. `model_router` talks to `google.genai` directly in
its own `_gemini` adapter, so there is no import cycle.

---

## 3. File-by-file connection detail

### `main.py` — the agent

**Imports (inward):**
- `ui.JarvisUI` — constructs the window, calls `ui.set_state`, `ui.write_log`,
  `ui.show_content`, `ui.start_camera_stream`, `ui.current_file`. Also sets
  `ui.on_text_command = self._on_text_command` (line ~620),
  `ui.get_plugins`, `ui.get_plugin_settings`, `ui.request_say`.
- `memory.memory_manager` → `load_memory, update_memory, format_memory_for_prompt,
  save_session_summary, pop_last_session, search_memory, set_trim_notifier`
  (last two used inline by `recall_memory` / `save_memory`).
- `memory.config_manager` → voice, thinking, turn-tuning, barge-in, wake-word,
  device, brief and media-resolution getters/savers.
- `actions.screen_processor` → `_capture_camera` (imported as
  `_raw_capture_camera`, then wrapped — see below) and `_capture_screen`.
- `actions.system_monitor` → `SystemMonitor`, `get_system_status`.
- `actions.proactive` → `ProactiveEngine`.
- `actions.background_monitor` → `add_monitor, remove_monitor, list_monitors, check_all`.
- `actions.web_search._news` → `_fetch_news_sync` (startup briefing).
- `core.gemini as _gemini` — direct API access for briefings/summaries.
- `core.action_loader.discover_actions`, `core.plugin_loader.discover_plugins`.
- `core.undo as undo_stack`, `core.confirm as confirm_gate`, `core.audio_devices`.
- `core.study_guard` — webcam lock (lines 102–108, 1301–1303).
- `core.echo.EchoGuard`, `core.barge_in.BargeInDetector`, `core.noise_gate.NoiseGate`,
  `core.viseme.VisemeStream`, `core.wake_word.*`, `core.hotkey.PushToTalk`.
- Lazily: `dashboard.server.DashboardServer`, `core.screen_geometry`.

**Study Mode hooks in `main.py`:**
- Module-level `_capture_camera(*a, **k)` wrapper (line ~105) calls
  `study_guard.require_camera()` then `_raw_capture_camera(...)`. Raises
  `CameraLocked` while Study Mode is on.
- `_execute_tool` → `screen_process` branch (line ~1297): if `angle == "camera"`
  and `study_guard.camera_locked()`, returns `study_guard.CAMERA_REFUSAL` instead
  of capturing. `angle="screen"` is unaffected — that is how question papers are read.
- `study_mode` itself is **not** inline: it is a plugin, found by
  `discover_plugins` (lines ~671–679) and run through `_plugin_registry.run`.

**Key methods and what they touch:**

| Method | Calls out to |
|---|---|
| `_build_config()` | `self._action_registry.get_tool_declarations()` + `self._plugin_registry.get_tool_declarations()` → `tools=[{"function_declarations": …}]`; `get_voice()`, `get_thinking_enabled()`, `get_turn_tuning()`, `get_media_resolution()`, `get_proactive_audio_enabled()` |
| `_execute_tool(fc)` | `_action_registry.run(name, args, ctx)`, `_plugin_registry.run(...)`, inline handlers, `loop.run_in_executor`, `asyncio.wait_for(timeout=_TOOL_TIMEOUT_S=180)` |
| `_receive_audio()` | `self.session.receive()`; on `response.tool_call` → `_execute_tool` per `fc` → `session.send_tool_response(...)` → `_flush_pending_vision()` |
| `_listen_audio()` | `EchoGuard`, `BargeInDetector`, `NoiseGate`, `WakeWordDetector` → `session.send_realtime_input` |
| `_play_audio()` | `VisemeStream`, `ui` viseme feed, barge-in interrupt |
| `_on_text_command(text)` (line ~928) | Injects typed / UI-originated text into the Live session as a user turn. Used by the study board's "Explain this step" button. |
| `_send_startup_briefing()` | `_fetch_news_sync`, `_gemini.text`, `get_brief_enabled` |
| `_save_session_summary()` | `_gemini.text` → `save_session_summary` |
| `_process_dashboard_commands()` | `self._dashboard._command_queue` |
| `run()` | starts `DashboardServer`, `set_connect_callback(self._on_phone_connected)`, `serve()`, `_process_dashboard_commands()` |

**Exports consumed elsewhere:** none (top-level executable). `ui.py` does **not**
import `main` — the link is one-way (main → ui), plus the callbacks main assigns
onto the `ui` object.

---

### `ui.py` — the HUD

**Two classes matter:**
- `MainWindow(QMainWindow)` (line 4079) — the Qt window. Owns all widgets and the
  thread-hop signals.
- `JarvisUI` (line 7093) — thread-safe facade over `MainWindow` (`self._win`).
  This is the `player` object tools and plugins receive.

**Imports:** `core.ui_readability`, `core.avatar.HoloAvatar`, `core.audio_devices`,
`core.wake_word.is_ready`, `core.hotkey.chord_label`, `core.target_overlay.TargetOverlay`,
`memory.config_manager` (voice, plugin flags, devices, brief, HUD style),
`memory.memory_manager` (`all_entries_for_ui`, `forget`), `core.confirm`,
**`core.study_guard`** and **`core.study_canvas`** (`StudyCanvasWidget`, `HAVE_STUDY`;
lines 65–66, deliberately at module top — see §6).

**Exports:** `JarvisUI` — the single object the agent drives. It is the *sink*:
the agent pushes state and reads a few fields (`current_file`, `muted`).

**Study Station surface in `ui.py`:**

| Where | What |
|---|---|
| `MainWindow` signals (4100–4101) | `_study_mode_sig(bool)`, `_study_board_sig(str, str)` — thread-safe entry into the GUI thread |
| `_hud_cam_stack` (4332–4342) | Stack index 0 = HUD, 1 = live camera, 2 = video, **3 = `StudyCanvasWidget`** (`_study_idx`) |
| `F8` shortcut (4430) | Toggles `_set_study_mode(not self._study_on)` |
| `_set_study_mode(on)` (4477) | Sets `study_guard` first, stops camera stream, closes video, `canvas.ensure_loaded()`, switches the stack, collapses/expands the left metrics panel |
| `_on_study_board(op, payload)` (4498) | Fans `solution` / `status` / `next` / `clear` out to the canvas |
| `_on_study_event(kind, data)` (4511) | Board button → Python: `exit` → `_set_study_mode(False)`; `explain_step` → `on_text_command(...)` on a daemon thread |
| `_on_cam_stream`, `start_camera_stream`, `_cam_loop` (4521–4552) | Camera never shows over the board; `start_camera_stream` returns early when `camera_locked()`, `_cam_loop` calls `require_camera()` again right before touching hardware |
| video open (≈4595) | Opening a video leaves Study Mode first |
| `JarvisUI` study API (7385–7419) | `study_available`, `study_mode_active` (both properties), `set_study_mode`, `study_solution`, `study_status`, `study_next`, `study_clear` — what `plugins/study_mentor.py` calls |

`JarvisUI.set_study_mode()` takes the webcam lock **synchronously** on the calling
thread (`study_guard.set_study_active`) before emitting `_study_mode_sig`, so there
is no window between "mode on" and "camera refused".

**Note:** `ui.py` imports `core.gemini` in one place (self-dev / settings helper),
so the arrow ui → gemini exists, but it is not part of the runtime hot path.

---

### `core/gemini.py` — the Gemini API wrapper (Layer 3)

**Purpose:** one place that knows about models, keys, quotas, and fallback.

**Imports:** stdlib + `google.genai` **lazily** inside `client()` / `_live_call()`
(so the module imports even without the SDK present). **New:** `core.model_router`,
lazily, in two places.

**Key exports and semantics:**

| Export | Behaviour |
|---|---|
| `call(contents, tier, config, timeout_ms, key)` | Walks `_LADDERS[tier]` (model-outer, key-inner) until a model answers. Returns the raw SDK response, or `None` if all failed. Handles key-death, quota (`_cool`), "gone", "unavailable" with per-model cooldowns. **When every Gemini pair fails** (and the call has no grounding tools and tier is not `SEARCH`), falls back to `model_router.fallback_text` (Groq → OpenRouter) and wraps the string in `_Reply`. |
| `text(...)` | **Routes first, calls second.** If the prompt contains coding keywords (`code`, `python`, `script`, `bug`, `debug`, Bangla `কোড`, …) or work keywords (`file`, `docs`, `sheet`, `update`, `summary`, `draft`, …) **or `tier == SMART`**, it tries `model_router.call(prompt, task="coding"\|"writing")` and returns that if non-empty. Only then does it fall through to `call()` and `.text`. |
| `as_json(...)` | `text()` with fence/prose stripping + `json.loads`, with `default`. Inherits `text()`'s routing. |
| `api_key()`, `api_keys()`, `key_label()` | Read `config/api_keys.json`, rotate keys. |
| `client()` | Builds a `google.genai.Client` (lazy import). |
| `FAST`, `SMART`, `SEARCH`, `LIVE` | Tiers: short classification / reasoning+images / REST-grounded search / Live API. |
| `LIVE_MODELS`, `live_model()`, `live_target()` | The two Live models the conversation may open with, and the (key, model) pair chosen from both ladders. |
| `_live_call()`, `_live_turn()` | One-shot throwaway Live session, gated by `_LIVE_SLOTS` (max 3 concurrent) and `_LIVE_SLOT_WAIT`. |
| `is_quota_error`, `is_unavailable_error`, `is_gone_error`, `is_key_error` | Error classifiers. |

**Consumers (13 files):** `actions/code_helper.py`, `actions/computer_control.py`,
`actions/desktop.py`, `actions/dev_agent.py`, `actions/file_processor.py`,
`actions/flight_finder.py`, `actions/web_search.py`, `actions/youtube_video.py`,
`core/screen_agent.py`, `core/ui_grounding.py`, `main.py`, `plugins/self_dev.py`,
`ui.py`.

**Key detail:** `main.py` talks to Gemini **two ways** —
1. Through the **Live session** (`self.session`), which is the SDK's realtime
   object, *not* `core.gemini`.
2. Through `core.gemini.text/as_json` for one-shot jobs (briefings, summaries,
   vision grounding) — which, per the routing above, may never reach Gemini at
   all if the prompt trips a keyword or uses `SMART`.

---

### `core/model_router.py` — task router + key health engine (Layer 3, second route)

**Purpose:** one-shot text in, text out, across OpenRouter / Groq / Gemini, with
per-task model chains and per-provider key pools. Never imports `main.py`, never
opens a Live session, never touches the Live quota pool. Imports only stdlib
(`google.genai` lazily inside `_gemini`).

**Public API (none raise):**

| Export | Behaviour |
|---|---|
| `call(prompt, task="fast", system="", model=None, timeout=None, budget=None)` | Walks the chain for `task`, one try per key per step, until a non-empty reply. `""` if all failed. `timeout` = seconds per attempt; `budget` = whole-call cap (returns `""` when under 5 s remain). |
| `as_json(prompt, task, system)` | `call` in JSON mode; non-JSON reply counts as failure. `{}` if all failed; a top-level list comes back as `{"items": [...]}`. |
| `status()` | Key health per provider (label, fails, seconds cooling) for UI/debug. |
| `fallback_text(contents, config, raw_cfg, timeout_s)` | Used by `core/gemini.py` when all Gemini pairs fail: Groq `llama-3.3-70b-versatile` → OpenRouter Llama → OpenRouter DeepSeek-R1. |
| `DEFAULT_RULES` | Task → ordered `(provider, model)` steps. Tasks: `coding`, `writing`, `fast`, **`study`**, **`study_fast`**. |

**Task chains (defaults):**

| Task | Chain |
|---|---|
| `coding` | openrouter `deepseek/deepseek-r1:free` → gemini `gemini-2.5-flash` |
| `writing` | groq `llama-3.3-70b-versatile` → openrouter Llama 3.3 70B free → gemini `gemini-2.5-flash` |
| `fast` | gemini `gemini-2.5-flash-lite` → groq `llama-3.1-8b-instant` → openrouter Llama 3.3 70B free |
| `study` | openrouter `deepseek/deepseek-r1:free` → groq `llama-3.3-70b-versatile` → gemini `gemini-2.5-flash` (reasoning first) |
| `study_fast` | groq `llama-3.3-70b-versatile` → gemini `gemini-2.5-flash` → openrouter `deepseek/deepseek-r1:free` |

**Config:** reads `config/api_keys.json` (re-read when its mtime changes, so a pasted
key works without a restart): `gemini_api_key(s)`, `openrouter_api_key(s)`,
`groq_api_key(s)`, and `routing_rules` (per-task override; `"provider:model"` or
`{"provider","model"}` steps).

**Health model:** `_Pool` per provider (least-recently-used key, per-key cooldown:
quota 60 s doubling to 1 h, auth 10 min, transient 30 s); `_resting_models`
sets a missing model aside for 30 min across all keys. `<think>…</think>` blocks
from R1 are stripped in `_openai_compat`.

**Consumers:** `plugins/study_mentor.py` (`call`, tasks `study` / `study_fast`);
`core/gemini.py` (`call` from `text()`, `fallback_text` from `call()`).

---

### `core/study_guard.py` — the webcam lock

Pure Python, Qt-free, one module-level flag guarded by a `threading.Lock`.

| Export | Use |
|---|---|
| `set_study_active(on)` / `study_active()` | Set / read the flag. `JarvisUI.set_study_mode` and `MainWindow._set_study_mode` set it; `JarvisUI.study_mode_active` reads it. |
| `camera_locked()` | Alias of `study_active()`. Used as a cheap gate (`main.py` screen_process branch, `ui.start_camera_stream`). |
| `require_camera()` | Raises `CameraLocked`. Called by `main._capture_camera` wrapper and `ui._cam_loop` right before opening hardware. |
| `CAMERA_REFUSAL` | The tool-result string telling the model not to retry and that the screen can still be read. |

**Consumers:** `main.py`, `ui.py`. `plugins/study_mentor.py` imports it but does not
use it — the lock is taken through `player.set_study_mode`.

---

### `core/study_canvas.py` + `runtime/study_board.html` — the Study Board

**`StudyCanvasWidget(QWidget)`** wraps a `QWebEngineView`. If `PyQt6-WebEngine` is
missing, `HAVE_STUDY = False` and the widget shows an install hint instead of crashing.

| Method / signal | Direction | Behaviour |
|---|---|---|
| `ensure_loaded()` | Python | Loads `runtime/study_board.html` on first use (web engine ≈150 MB, not paid until a study session starts). Resolves the path from `sys.executable` when frozen. |
| `show_solution(title, markdown, subject, reveal)` | Python → board | Posts `{"op": "render", …}` |
| `show_status(text)` / `next_step()` / `clear()` | Python → board | Posts `status` / `next` / `clear` |
| `user_event(type, data)` signal | board → Python | Emitted from `StudyBridge.event` JSON; connected to `MainWindow._on_study_event` |

Thread safety: every public method only emits `_send_sig`; Qt queues it onto the GUI
thread. Messages sent before the page finishes loading are held in `_pending`
(cap 8, oldest dropped) and flushed on `boardReady`.

**`StudyBridge(QObject)`** is the object the page sees as `bridge` over `QWebChannel`:
`toBoard(str)` signal (Python → JS), `boardReady()` slot, `userEvent(str)` slot (JS → Python).

**`study_board.html`** — fully local (no CDN at runtime). Loads
`vendor/katex/*`, `vendor/tailwind/tailwind.js`, `vendor/plotly/plotly.min.js`,
and `qrc:///qtwebchannel/qwebchannel.js`. JS ops: `render` (parses `## ` headings into
step cards, `$…$`/`$$…$$` via KaTeX, ```` ```plot ```` blocks via Plotly, `reveal=all|steps`),
`next`, `status`, `clear`. Buttons: **Next step ▸** (JS-only, no round trip),
**Explain this step** (`explain_step` event), **✕ EXIT** (`exit` event). If KaTeX or
Plotly is missing it shows "Board libraries missing. Run: python tools/fetch_study_vendor.py".
Open it in a browser with `#demo` to preview without Qt.

**`tools/fetch_study_vendor.py`** — one-shot, stdlib-only downloader that fills
`runtime/vendor/` (KaTeX 0.16.11 JS/CSS/auto-render + 20 woff2 fonts, Tailwind, Plotly
2.35.2). Skips files already present. No importers.

---

### `core/action_loader.py` and `core/plugin_loader.py` — discovery

**`action_loader`**
- `discover_actions(actions_dir, reserved_names, logger)` scans `actions/*.py`
  (skips `_`-prefixed), reads the module-level `TOOL` dict, validates it in
  `_validate()`, returns an `ActionRegistry`.
- `ActionRecord` fields: `name, description, parameters, handler, file, valid,
  error, behavior, scheduling`.
- `ActionRegistry` API used by `main.py`:
  - `get_tool_declarations()` → list for `LiveConnectConfig`.
  - `has(name)`, `names()`, `scheduling(name)`.
  - `run(name, parameters, ctx)` → `_call_handler()` passes only the context
    kwargs the handler actually declares (`player`, `speak`, `response`,
    `session_memory`), so signatures stay flexible.

**`plugin_loader`** — same shape, different contract:
- Reads `PLUGIN` dict + a callable `run(parameters, player=, session_memory=)`.
- `discover_plugins(plugins_dir, core_tool_names, …)` — `core_tool_names` lets a
  plugin avoid colliding with a core tool name.
- Optional `PLUGIN_SETTINGS` schema rendered by the settings UI; malformed
  schemas are ignored, never fatal.
- `PluginRegistry.run()` and `get_tool_declarations()` mirror the action registry.
- **Imports** `memory.config_manager.get_plugin_enabled / get_plugin_config` so
  disabled plugins are skipped and per-plugin config is injected.

---

### `actions/` — the tool handlers

Each file exposes a `TOOL` dict. Verified tool names:

| File | `TOOL["name"]` | handler |
|---|---|---|
| `browser_control.py` | `browser_control` | `browser_control` |
| `code_helper.py` | `code_helper` | `code_helper` |
| `computer_control.py` | `computer_control` | `computer_control` |
| `computer_settings.py` | `computer_settings` | `computer_settings` |
| `desktop.py` | `desktop_control` | `desktop_control` |
| `dev_agent.py` | `dev_agent` | `dev_agent` |
| `file_controller.py` | `file_controller` | `file_controller` |
| `file_processor.py` | `file_processor` | `file_processor` |
| `flight_finder.py` | `flight_finder` | `flight_finder` |
| `game_updater.py` | `game_updater` | `game_updater` |
| `google_workspace.py` | `google_workspace` | `google_workspace` |
| `open_app.py` | `open_app` | `open_app` |
| `reminder.py` | `reminder` | `reminder` |
| `send_message.py` | `send_message` | `send_message` |
| `video_player.py` | `video_player` | `video_player` |
| `weather_report.py` | `weather_report` | `weather_action` |
| `web_search.py` | `web_search` | `web_search` |
| `youtube_video.py` | `youtube_video` | `youtube_video` |

**Not tools (helpers, no `TOOL` dict):** `screen_processor.py` (vision capture),
`system_monitor.py`, `proactive.py`, `background_monitor.py` — these are imported
directly by `main.py`.

**Tool → core dependencies:**

| Action | Reaches into core |
|---|---|
| `code_helper`, `dev_agent`, `file_processor`, `flight_finder`, `web_search`, `youtube_video`, `desktop` | `core.gemini` (`text` / `as_json` / `call`) — which may reroute to `core.model_router` (see `gemini.text`) |
| `computer_control` | `core.gemini`, `core.ui_grounding`, `core.screen_geometry`, `core.screen_agent` |
| `computer_settings` | `core.confirm`, `core.undo.push_undo` |
| `file_controller` | `core.undo.push_undo`, `memory.config_manager.load_api_keys` |
| `send_message` | `plugins._whatsapp_core` (lazy) |
| `flight_finder`, `game_updater`, `youtube_video` | `config` (`get_os`, `is_windows`) |
| `background_monitor` | `memory.memory_manager.load_memory`, `actions.web_search._ddg_news` |

**Reverse edge (new):** `actions.web_search._search_sync` is also imported by
`plugins/study_mentor.py` (a plugin reaching into a private `_`-prefixed action
helper; wrapped in `try/except`, so a rename degrades to `web=unavailable`
instead of crashing).

---

### `plugins/` — user plugins

| File | `PLUGIN["name"]` | run signature |
|---|---|---|
| `file_access.py` | `manage_file_access` | `run(parameters, …)` |
| `file_navigator.py` | `file_navigator` | `run(parameters, …)` |
| `self_dev.py` | `jarvis_self_developer` | `run(parameters, response, player, session_memory)` |
| `temp_cleaner.py` | `temp_cleaner` | `run(parameters, …)` |
| `self_modification_system.py` | (writes core files) | `run(parameters, response, player, session_memory)` |
| `study_mentor.py` | `study_mode` | `run(parameters, response, player, session_memory)` |

Plugins reach into `core.confirm`, `core.gemini`, `memory.config_manager`
(`load_api_keys`, `_patch_config`), and — for the self-modification pair —
directly rewrite files in `core/` and `ui.py`.

#### `plugins/study_mentor.py` — Universal Learning Station (`study_mode`)

**Imports:** `core.study_guard` (unused), `core.model_router` (guarded; `None` →
"router not available"), `actions.web_search._search_sync` (guarded; `None` →
`web=unavailable`), stdlib (`re`, `statistics`, `concurrent.futures.ThreadPoolExecutor`).

**Talks to the `player` (= `JarvisUI`) through:** `study_available`,
`study_mode_active`, `set_study_mode`, `study_status`, `study_solution`, `study_next`.
It never touches Qt or the webcam directly.

**Actions:** `enter`, `exit`, `next`, `ask`.

**`ask` parameters:** `question`, `subject`, `kind`, `language`, `reveal`,
`from_screen` (yes/no), `web` (auto/on/off).

**Subjects:** `physics`, `chemistry`, `higher_math`, `biology`, `ict`, `bangla`,
`english`, `general`. Aliases normalised by `_ALIASES`; when none is passed,
`_guess_subject` scores keyword lists and falls back to `general`.

**Kinds:** `numerical`, `derivation`, `concept`, `mcq`, `cq`, `writing`
(`classify_question` detects CQ/MCQ from ক-খ-গ-ঘ / a-d markers, writing from
"write a paragraph/letter…" and Bangla composition words).

**Routing into `model_router`:**

| Condition | Task |
|---|---|
| kind in {numerical, derivation, cq, mcq} **and** subject not in {biology, bangla, english, general} | `study` |
| everything else | `study_fast` |

**Web fallback:** runs when `web=on`, or `web=auto` and `from_screen` is not `yes`.
`_web_context` calls `_search_sync` on a worker thread (10 s cap), flattens the
result (str / list / dict) to ≤3000 chars, and passes it to the solver as an
untrusted `WEB REFERENCE`. Empty/failed search → `web=none`, solve continues.

**Return tags the model sees:** `[STUDY_MODE]` (enter/exit), `[STUDY_BOARD]` (ask/next,
carries `kind=`, `subject=`, `web=used|none|off|unavailable`, plus `FINAL` and the
first 3500 chars of the solution for follow-ups).

**Time budget:** solver `timeout=60`, `budget=150`, plus ≤10 s search → stays under
`main._TOOL_TIMEOUT_S = 180`.

---

### `memory/`

- **`memory_manager.py`** — `long_term.json` under a lock. Exports
  `load_memory, save_memory, update_memory, format_memory_for_prompt,
  search_memory, all_entries_for_ui, remember, forget, save_session_summary,
  pop_last_session, set_trim_notifier`. Imported by `main.py`, `ui.py`,
  `actions/background_monitor.py`, `actions/proactive.py`.
- **`config_manager.py`** — the flag store (`config/api_keys.json`). Every
  getter/setter for voice, devices, wake word, barge-in, HUD style, plugin
  enable/config, brief, grounding layers, agent steps. Imported by `main.py`,
  `ui.py`, `core/plugin_loader.py`, several actions/plugins.

Note: `config/api_keys.json` is now read by three independent readers —
`core/gemini.py` (`_KEY_FILE`, cached), `core/model_router.py` (mtime-refreshed,
also owns `openrouter_*`, `groq_*`, `routing_rules`), and `memory/config_manager.py`.

---

### `dashboard/server.py`

- Exports `DashboardServer`: `new_key`, `get_url`, `get_manual_url`,
  `set_wake_callback`, `set_connect_callback`, `broadcast`, `serve`,
  `_command_queue`, `_phone_audio_queue`.
- Wired from `main.py::run()` (constructed, callback set, `serve()` task,
  `_process_dashboard_commands()` task) and consumed in `_receive_audio()` via
  `broadcast(...)` and in `_relay_phone_audio()`.
- No import back into `main` — it is driven purely through callbacks and queues.

---

## 4. Dependency chains

### 4.1 Full startup / session chain

```
main() 
  → _single_instance_or_exit()
  → JarvisUI()                         [ui.py: window, avatar, settings,
                                         StudyCanvasWidget in HUD stack idx 3]
  → JarvisLive(ui)
       → discover_actions(actions/)    [core/action_loader.py]
             └─ per file: import module → read TOOL → _validate → ActionRecord
       → discover_plugins(plugins/, core_tool_names)
             └─ reads PLUGIN + run(); consults memory.config_manager.get_plugin_enabled
             └─ includes plugins/study_mentor.py → tool "study_mode"
       → _build_config()
             └─ get_tool_declarations()  [actions + plugins]
             └─ memory.config_manager getters (voice/thinking/tuning/…)
             └─ types.LiveConnectConfig(tools=[{"function_declarations": …}])
  → session.connect(config)            [google.genai Live API]
  → asyncio.gather(_listen_audio, _receive_audio, _play_audio, …)
  → DashboardServer().serve()          [dashboard/server.py]
```

### 4.2 The tool-call round trip (the heart of the system)

```
mic ─▶ _listen_audio()
        └─ EchoGuard → BargeInDetector → NoiseGate → WakeWordDetector
        └─ session.send_realtime_input(audio=PCM)
                        │
                        ▼   (Live API decides a tool is needed)
        _receive_audio(): async for response in session.receive()
                        │
             response.tool_call.function_calls = [fc, …]
                        │
                        ▼
        _execute_tool(fc)  ── name/args ──▶
             ├─ inline?  save_memory → memory.update_memory
             │           recall_memory → memory.search_memory
             │           undo → core.undo
             │           system_status → actions.system_monitor
             │           screen_process → study_guard check (camera) →
             │                            actions.screen_processor (_capture_*)
             │           manage_monitor → actions.background_monitor
             │           shutdown_jarvis → _save_session_summary → os._exit
             ├─ action_registry.has(name)?
             │        └─ loop.run_in_executor(_action_registry.run)   [180 s cap]
             │              └─ _call_handler → handler(parameters, player=ui, …)
             │                    └─ e.g. web_search → core.gemini.text
             │                          computer_control → core.ui_grounding
             │                                             → core.screen_agent
             │                                             → core.gemini
             └─ plugin_registry.has(name)?
                      └─ _plugin_registry.run(name, args, player=ui)  [180 s cap]
                           └─ e.g. study_mode → plugins/study_mentor.run (see §4.5)
                        │
                        ▼
        result: str
        _sched = action/plugin scheduling(name)
                        │
                        ▼
        session.send_tool_response(FunctionResponse{result, scheduling})
                        │
                        ▼
        _flush_pending_vision()   (attaches screen/camera image to same exchange)
                        │
                        ▼
        model speaks ─▶ _receive_audio (output_transcription) ─▶ _play_audio()
                        └─ VisemeStream + barge-in interrupt + ui.write_log
```

### 4.3 Vision sub-chain

```
screen_process (inline)
  → angle == "camera" and study_guard.camera_locked()  →  CAMERA_REFUSAL (no capture)
  → actions.screen_processor._capture_screen / _capture_camera
      (camera path goes through main._capture_camera → study_guard.require_camera())
  → self._pending_vision = (img, mime, text, angle)
  → session.send_tool_response(...)
  → _flush_pending_vision() → session.send_client_content(image part)
  → model answers from the image
```
`core/ui_grounding.py` is the *other* vision path — deterministic element
finding (UIA → OCR → model vision) used by `computer_control`/`screen_agent`,
independent of the Live session.

### 4.4 One-shot model sub-chains

```
GEMINI-FIRST (core/gemini.py)
_send_startup_briefing() ─▶ actions.web_search._news ─▶ core.gemini.text
_save_session_summary()  ─▶ core.gemini.text ─▶ memory.save_session_summary
actions/*.py             ─▶ core.gemini.text / as_json / call
   text():  coding/work keyword  OR  tier == SMART
              └─▶ core.model_router.call(task="coding"|"writing")  ── non-empty? return
            else / on empty
              └─▶ call(): _LADDERS[tier] → cooldown checks → client()
                    → models.generate_content (or _live_call)
                    └─ every Gemini (model,key) failed, no tools, tier != SEARCH
                         └─▶ core.model_router.fallback_text (Groq → OpenRouter)

ROUTER-FIRST (core/model_router.py)
plugins/study_mentor ─▶ model_router.call(task="study"|"study_fast")
   └─ _chain(task) → [(provider, model) …]
        └─ per step: _Pool.acquire() key → adapter (_gemini | _openai_compat)
             └─ quota/auth/transient → cool that key, next key
                gone → rest model 30 min, next step
                other → next step
```

### 4.5 Study Station chain

```
VOICE / TEXT                                   prompt.txt [STUDY MODE]
  "solve this"  ──▶ Live model ──▶ (question on screen?)
                                     yes → screen_process(angle='screen') → read text
                                           → study_mode(ask, question, from_screen='yes')
                                     no  → study_mode(ask, question=<as spoken>, from_screen='no')
                                     (never "I can't see the screen"; never angle='camera')
                      │
                      ▼
main._execute_tool ─▶ _plugin_registry.run("study_mode", args, player=ui)   [180 s cap]
                      │
                      ▼
plugins/study_mentor.run(parameters, player=ui)
  ├─ guard: player has set_study_mode / study_available, else bail with message
  ├─ ui.set_study_mode(True)
  │     ├─ study_guard.set_study_active(True)           ← webcam lock, synchronous
  │     └─ MainWindow._study_mode_sig ─▶ _set_study_mode (GUI thread)
  │           ├─ stop_camera_stream(); close video
  │           ├─ StudyCanvasWidget.ensure_loaded() → load runtime/study_board.html
  │           ├─ _hud_cam_stack.setCurrentIndex(3); collapse left panel
  │           └─ log "SYS: Study Station ON - webcam locked off"
  ├─ classify_question → kind;  _pick_subject;  _lang
  ├─ [from_screen != yes, web != off]
  │     └─ ui.study_status("Searching online…")
  │        └─ ThreadPoolExecutor → actions.web_search._search_sync(query)   [10 s]
  ├─ ui.study_status("Solving…")
  ├─ core.model_router.call(user_prompt, task, system, timeout=60, budget=150)
  └─ ui.study_solution(title, markdown, subject, reveal)
        └─ JarvisUI._study_post("solution") ─▶ MainWindow._study_board_sig
              └─ _on_study_board ─▶ StudyCanvasWidget.show_solution
                    └─ _post("render") ─▶ _send_sig ─▶ _deliver (GUI thread)
                          └─ StudyBridge.toBoard ─▶ study_board.html  ops.render
                                └─ cards (## headings), KaTeX maths, Plotly graphs

Tool result back to model: "[STUDY_BOARD] … web=used|none|off|unavailable …"
  → model speaks 1–2 sentences (key idea / final value; never reads steps aloud)

BOARD → PYTHON
  "Next step ▸"        ops.next (JS only)
  "Explain this step"  bridge.userEvent({"type":"explain_step"})
                         └─ StudyBridge.event ─▶ StudyCanvasWidget.user_event
                              └─ MainWindow._on_study_event
                                   └─ thread → ui.on_text_command(msg)
                                        └─ JarvisLive._on_text_command ─▶ Live session turn
  "✕ EXIT" / F8        _set_study_mode(False): study_guard off, stack idx 0, panel reopens

VOICE "next" / "exit"
  study_mode(action='next') ─▶ ui.study_next ─▶ canvas.next_step ─▶ ops.next
  study_mode(action='exit') ─▶ ui.set_study_mode(False)
```

**Webcam lock layers (all keyed on `core/study_guard`):**

| # | Where | Effect |
|---|---|---|
| 1 | `JarvisUI.set_study_mode` / `MainWindow._set_study_mode` | Flag set synchronously before any UI change |
| 2 | `main._execute_tool` → `screen_process` | `angle="camera"` returns `CAMERA_REFUSAL` |
| 3 | `main._capture_camera` wrapper | `require_camera()` before the raw capture |
| 4 | `ui.start_camera_stream` | Returns early when locked |
| 5 | `ui._cam_loop` | `require_camera()` immediately before `cv2` opens the device |
| 6 | `ui._on_cam_stream` | Camera view never replaces the board |

---

## 5. What depends on what (summary table)

| Consumer | Depends on |
|---|---|
| `main.py` | `ui`, `memory.*`, `core.gemini`, `core.action_loader`, `core.plugin_loader`, `core.{undo,confirm,audio_devices,echo,barge_in,noise_gate,viseme,wake_word,hotkey,screen_geometry,study_guard}`, `actions.{screen_processor,system_monitor,proactive,background_monitor,web_search}`, `dashboard.server`, `prompt.txt` |
| `ui.py` | `core.{ui_readability,avatar,audio_devices,wake_word,hotkey,target_overlay,confirm,gemini,study_guard,study_canvas}`, `memory.*` |
| `core/study_canvas.py` | `PyQt6` (+ `QtWebEngine`, `QtWebChannel`, optional), `runtime/study_board.html` |
| `runtime/study_board.html` | `runtime/vendor/{katex,tailwind,plotly}`, `qrc:///qtwebchannel/qwebchannel.js` |
| `core/study_guard.py` | stdlib only (leaf) |
| `core/gemini.py` | `google.genai` (lazy), `core.model_router` (lazy), `config/api_keys.json` |
| `core/model_router.py` | stdlib, `google.genai` (lazy), `config/api_keys.json` (leaf w.r.t. the app) |
| `core/action_loader.py` | `actions/*` (dynamic import) |
| `core/plugin_loader.py` | `plugins/*` (dynamic), `memory.config_manager` |
| `plugins/study_mentor.py` | `core.study_guard` (unused), `core.model_router`, `actions.web_search._search_sync`; drives `JarvisUI` study API via `player` |
| `actions/computer_control.py` | `core.{gemini,ui_grounding,screen_geometry,screen_agent}`, `pyautogui` |
| `actions/*` (Gemini-using) | `core.gemini` |
| `actions/computer_settings.py`, `file_controller.py` | `core.undo`, `core.confirm` |
| `plugins/self_dev.py`, `self_modification_system.py` | `core.{confirm,gemini}`, writes `core/` + `ui.py` |
| `dashboard/server.py` | FastAPI/uvicorn/cryptography (lazy); driven by `main` callbacks |
| `tools/fetch_study_vendor.py` | stdlib only; writes `runtime/vendor/` |
| `tools/*` (calibration) | `core.{screen_geometry,ui_grounding,target_overlay}` (offline CLIs) |

**Orphaned modules (no importers found):** `core/stt.py`, `core/tts.py`,
`core/llm_client.py`, `core/installer.py`. They are self-contained but currently
unreferenced — worth confirming before treating them as dead (they may be
imported dynamically by name in a string somewhere).

---

## 6. Circular / risky edges to watch

- **`main` ↔ `ui`** is one-way (main → ui) but `ui` holds the settings that
  `main` reads back via `memory.config_manager` — the coupling is through the
  config file, not imports. `main` also pushes callbacks onto the `ui` object
  (`on_text_command`, `get_plugins`, `request_say`), which is how the study board's
  "Explain this step" reaches the Live session.
- **`core/gemini.py` is no longer a pure leaf.** It lazily imports `core.model_router`
  (`text()` and the `call()` fallback). No cycle, because `model_router` never
  imports `gemini` (its `_gemini` adapter calls `google.genai` itself).
- **`gemini.text()` reroutes by keyword.** Any prompt containing words like
  `code`, `file`, `update`, `summary`, `draft` (or any `tier == SMART` call) goes to
  `model_router` first. So callers believing they hit the Gemini ladder can end up on
  Groq/OpenRouter, and the Gemini quota/cooldown logic is bypassed for them.
- **`model_router._chain` hijack.** A prompt containing "gemini" / "জেমিনাই"
  is forced onto `gemini-2.5-flash` regardless of task. A study question that merely
  mentions Gemini skips the `study` chain.
- **Import order for Qt WebEngine.** `ui.py` must import `core.study_canvas` at module
  top, before `QApplication` exists. Moving that import breaks the board. If
  `PyQt6-WebEngine` is absent, `HAVE_STUDY` is `False`, `JarvisUI.set_study_mode(True)`
  returns without taking the lock, and `study_mode` replies with the pip hint.
- **Study flag has two owners.** `study_guard._active` is the source of truth;
  `MainWindow._study_on` mirrors it. `JarvisUI.set_study_mode` flips the guard first, then
  the Qt signal, so `_set_study_mode`'s `on == self._study_on` check is about the UI
  state, not the lock. Anything new that opens the webcam must call
  `study_guard.require_camera()` itself or it bypasses the lock.
- **Plugin → private action helper.** `plugins/study_mentor.py` imports
  `actions.web_search._search_sync`. A rename there silently turns the web fallback
  off (`web=unavailable`). Its exact signature/return type is assumed (`_search_sync(query)`
  returning str/list/dict) and flattened defensively.
- **Vendor assets are a runtime precondition.** `runtime/vendor/` is empty until
  `tools/fetch_study_vendor.py` runs. Without it the board shows a "libraries
  missing" status. The script prints "All vendor libraries downloaded successfully"
  even when individual downloads failed.
- **Three readers of `config/api_keys.json`** (`core/gemini.py` cached once,
  `core/model_router.py` mtime-refreshed, `memory/config_manager.py`). A pasted key is
  picked up live by the router but needs `api_keys(refresh=True)` in `gemini.py`.
- **`actions/screen_processor` ↔ `main`**: `main` imports the private
  `_capture_screen` / `_capture_camera` helpers directly (the latter aliased to
  `_raw_capture_camera` and wrapped for the Study lock) — an internal-API edge
  that would break if those names change.
- **`plugins/self_dev.py` and `self_modification_system.py`** write into `core/`
  and `ui.py` at runtime — the only place the graph can rewrite itself. Treat
  those two as the highest-risk nodes. They can now also rewrite `core/study_guard.py`
  (the webcam lock) and `core/model_router.py`.
- **`core/ui_grounding.py`** is imported lazily by `core/screen_geometry.py`
  (line ~846) *and* imports `screen_geometry` at module top — a genuine
  import cycle, broken only by the lazy import inside the function.
- **Dead import:** `plugins/study_mentor.py` imports `core.study_guard` and never uses it.
  Harmless, but it is an edge on the graph that carries no behaviour.
