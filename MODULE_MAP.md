# JARVIS — Module-to-Module Connection Map

A dependency map of the JARVIS codebase: what each file imports, what it exports,
who consumes those exports, and how data flows from the agent loop through the
tool handlers to the Gemini API wrapper.

> Line numbers reference the tree as of 2026-10-12. Root: `D:\Claude Project\JARVIS`.

---

## 1. Core module inventory

| Folder | Role | Entry points |
|---|---|---|
| `main.py` | The agent. Owns the Live session, the mic/speaker loops, tool dispatch. | `main()`, `class JarvisLive` |
| `ui.py` | PyQt6 HUD window, avatar, settings panels, content panel, camera stream. | `class JarvisUI` |
| `core/` | Infrastructure: API wrapper, loaders, audio pipeline, vision, safety. | `gemini`, `action_loader`, `plugin_loader`, … |
| `actions/` | Auto-discovered tools, one file = one `TOOL` dict. | `discover_actions()` |
| `plugins/` | Auto-discovered user plugins, one file = one `PLUGIN` dict + `run()`. | `discover_plugins()` |
| `memory/` | Long-term JSON memory + all user-facing config flags. | `memory_manager`, `config_manager` |
| `dashboard/` | Phone/remote web server (FastAPI + WebSocket). | `class DashboardServer` |
| `config/` | OS detection + `api_keys.json` accessor. | `get_os()`, `is_windows()` |
| `tools/` | Standalone dev/calibration CLIs (not part of runtime). | `calibrate.py`, `target_debug.py` |

### `core/` at a glance

| File | Exports (consumed elsewhere) | Consumed by |
|---|---|---|
| `gemini.py` | `call`, `text`, `as_json`, `api_key`, `client`, `FAST/SMART/SEARCH/LIVE`, `is_*_error` | 13 files (see §4) |
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
│  LAYER 2 — TOOL HANDLERS      │   │  LAYER 3 — GEMINI WRAPPER       │
│  actions/*.py   (TOOL dict)   │──▶│  core/gemini.py                 │
│  plugins/*.py   (PLUGIN dict) │   │  call() → _LADDERS[FAST|SMART]  │
│  inline in main.py            │   │  _live_call() → Live API        │
└───────────────────────────────┘   └─────────────────────────────────┘
```

**Rule of the design:** only tools tied to *live-session state* live inline in
`main.py` (`screen_process`, `close_camera`, `save_memory`, `manage_monitor`,
`shutdown_jarvis`, `system_status`, `recall_memory`, `undo`). Everything else
self-describes and is auto-discovered. `main.py` imports the file-backed ones
only for side-effect helpers it calls directly (`_capture_screen`, `add_monitor`,
`SystemMonitor`, …) — not for tool declaration.

---

## 3. File-by-file connection detail

### `main.py` — the agent

**Imports (inward):**
- `ui.JarvisUI` — constructs the window, calls `ui.set_state`, `ui.write_log`,
  `ui.show_content`, `ui.start_camera_stream`, `ui.current_file`.
- `memory.memory_manager` → `load_memory, update_memory, format_memory_for_prompt,
  save_session_summary, pop_last_session, search_memory, set_trim_notifier`
  (last two used inline by `recall_memory` / `save_memory`).
- `memory.config_manager` → voice, thinking, turn-tuning, barge-in, wake-word,
  device, brief and media-resolution getters/savers.
- `actions.screen_processor` → `_capture_camera`, `_capture_screen` (vision).
- `actions.system_monitor` → `SystemMonitor`, `get_system_status`.
- `actions.proactive` → `ProactiveEngine`.
- `actions.background_monitor` → `add_monitor, remove_monitor, list_monitors, check_all`.
- `actions.web_search._news` → `_fetch_news_sync` (startup briefing).
- `core.gemini as _gemini` — direct API access for briefings/summaries.
- `core.action_loader.discover_actions`, `core.plugin_loader.discover_plugins`.
- `core.undo as undo_stack`, `core.confirm as confirm_gate`, `core.audio_devices`.
- `core.echo.EchoGuard`, `core.barge_in.BargeInDetector`, `core.noise_gate.NoiseGate`,
  `core.viseme.VisemeStream`, `core.wake_word.*`, `core.hotkey.PushToTalk`.
- Lazily: `dashboard.server.DashboardServer`, `core.screen_geometry`.

**Key methods and what they touch:**

| Method | Calls out to |
|---|---|
| `_build_config()` | `self._action_registry.get_tool_declarations()` + `self._plugin_registry.get_tool_declarations()` → `tools=[{"function_declarations": …}]`; `get_voice()`, `get_thinking_enabled()`, `get_turn_tuning()`, `get_media_resolution()`, `get_proactive_audio_enabled()` |
| `_execute_tool(fc)` | `_action_registry.run(name, args, ctx)`, `_plugin_registry.run(...)`, inline handlers, `loop.run_in_executor`, `asyncio.wait_for(timeout=_TOOL_TIMEOUT_S=180)` |
| `_receive_audio()` | `self.session.receive()`; on `response.tool_call` → `_execute_tool` per `fc` → `session.send_tool_response(...)` → `_flush_pending_vision()` |
| `_listen_audio()` | `EchoGuard`, `BargeInDetector`, `NoiseGate`, `WakeWordDetector` → `session.send_realtime_input` |
| `_play_audio()` | `VisemeStream`, `ui` viseme feed, barge-in interrupt |
| `_send_startup_briefing()` | `_fetch_news_sync`, `_gemini.text`, `get_brief_enabled` |
| `_save_session_summary()` | `_gemini.text` → `save_session_summary` |
| `_process_dashboard_commands()` | `self._dashboard._command_queue` |
| `run()` | starts `DashboardServer`, `set_connect_callback(self._on_phone_connected)`, `serve()`, `_process_dashboard_commands()` |

**Exports consumed elsewhere:** none (top-level executable). `ui.py` does **not**
import `main` — the link is one-way (main → ui).

---

### `ui.py` — the HUD

**Imports:** `core.ui_readability`, `core.avatar.HoloAvatar`, `core.audio_devices`,
`core.wake_word.is_ready`, `core.hotkey.chord_label`, `core.target_overlay.TargetOverlay`,
`memory.config_manager` (voice, plugin flags, devices, brief, HUD style),
`memory.memory_manager` (`all_entries_for_ui`, `forget`), `core.confirm`.

**Exports:** `JarvisUI` — the single object the agent drives. It is the *sink*:
the agent pushes state and reads a few fields (`current_file`, `muted`).

**Note:** `ui.py` imports `core.gemini` in one place (self-dev / settings helper),
so the arrow ui → gemini exists, but it is not part of the runtime hot path.

---

### `core/gemini.py` — the Gemini API wrapper (Layer 3)

**Purpose:** one place that knows about models, keys, quotas, and fallback.

**Imports:** stdlib + `google.genai` **lazily** inside `client()` / `_live_call()`
(so the module imports even without the SDK present).

**Key exports and semantics:**

| Export | Behaviour |
|---|---|
| `call(contents, tier, config, timeout_ms, key)` | Walks `_LADDERS[tier]` until a model answers. Returns the raw SDK response, or `None` if all failed. Handles key-death, quota (`_cool`), "gone", "unavailable" with per-model cooldowns. |
| `text(...)` | `call()` reduced to `.text`, with `default`. |
| `as_json(...)` | `text()` with fence/prose stripping + `json.loads`, with `default`. |
| `api_key()`, `api_keys()`, `key_label()` | Read `config/api_keys.json`, rotate keys. |
| `client()` | Builds a `google.genai.Client` (lazy import). |
| `FAST`, `SMART`, `SEARCH`, `LIVE` | Tiers: short classification / reasoning+images / REST-grounded search / Live API. |
| `_live_call()`, `_live_turn()`, `live_target()` | The Live-API path, gated by `_LIVE_SLOTS` (max 3 concurrent) and `_LIVE_SLOT_WAIT`. |
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
   vision grounding).

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
| `code_helper`, `dev_agent`, `file_processor`, `flight_finder`, `web_search`, `youtube_video`, `desktop` | `core.gemini` (`text` / `as_json` / `call`) |
| `computer_control` | `core.gemini`, `core.ui_grounding`, `core.screen_geometry`, `core.screen_agent` |
| `computer_settings` | `core.confirm`, `core.undo.push_undo` |
| `file_controller` | `core.undo.push_undo`, `memory.config_manager.load_api_keys` |
| `send_message` | `plugins._whatsapp_core` (lazy) |
| `flight_finder`, `game_updater`, `youtube_video` | `config` (`get_os`, `is_windows`) |
| `background_monitor` | `memory.memory_manager.load_memory`, `actions.web_search._ddg_news` |

---

### `plugins/` — user plugins

| File | `PLUGIN["name"]` | run signature |
|---|---|---|
| `file_access.py` | `manage_file_access` | `run(parameters, …)` |
| `file_navigator.py` | `file_navigator` | `run(parameters, …)` |
| `temp_cleaner.py` | `temp_cleaner` | `run(parameters, …)` |

Plugins reach into `core.confirm`, `core.gemini`, `memory.config_manager`
(`load_api_keys`, `_patch_config`), and — for the self-modification pair —
directly rewrite files in `core/` and `ui.py`.

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
  → JarvisUI()                         [ui.py: window, avatar, settings]
  → JarvisLive(ui)
       → discover_actions(actions/)    [core/action_loader.py]
             └─ per file: import module → read TOOL → _validate → ActionRecord
       → discover_plugins(plugins/, core_tool_names)
             └─ reads PLUGIN + run(); consults memory.config_manager.get_plugin_enabled
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
             │           screen_process → actions.screen_processor (_capture_*)
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
  → actions.screen_processor._capture_screen / _capture_camera
  → self._pending_vision = (img, mime, text, angle)
  → session.send_tool_response(...)
  → _flush_pending_vision() → session.send_client_content(image part)
  → model answers from the image
```
`core/ui_grounding.py` is the *other* vision path — deterministic element
finding (UIA → OCR → model vision) used by `computer_control`/`screen_agent`,
independent of the Live session.

### 4.4 Gemini one-shot sub-chain

```
_send_startup_briefing() ─▶ actions.web_search._news ─▶ core.gemini.text
_save_session_summary()  ─▶ core.gemini.text ─▶ memory.save_session_summary
actions/*.py             ─▶ core.gemini.text / as_json / call
                             └─ _LADDERS[tier] → cooldown checks → client()
                                → models.generate_content (or _live_call)
```

---

## 5. What depends on what (summary table)

| Consumer | Depends on |
|---|---|
| `main.py` | `ui`, `memory.*`, `core.gemini`, `core.action_loader`, `core.plugin_loader`, `core.{undo,confirm,audio_devices,echo,barge_in,noise_gate,viseme,wake_word,hotkey,screen_geometry}`, `actions.{screen_processor,system_monitor,proactive,background_monitor,web_search}`, `dashboard.server` |
| `ui.py` | `core.{ui_readability,avatar,audio_devices,wake_word,hotkey,target_overlay,confirm,gemini}`, `memory.*` |
| `core/gemini.py` | `google.genai` (lazy), `config/api_keys.json` |
| `core/action_loader.py` | `actions/*` (dynamic import) |
| `core/plugin_loader.py` | `plugins/*` (dynamic), `memory.config_manager` |
| `actions/computer_control.py` | `core.{gemini,ui_grounding,screen_geometry,screen_agent}`, `pyautogui` |
| `actions/*` (Gemini-using) | `core.gemini` |
| `actions/computer_settings.py`, `file_controller.py` | `core.undo`, `core.confirm` |
| `plugins/self_dev.py`, `self_modification_system.py` | `core.{confirm,gemini}`, writes `core/` + `ui.py` |
| `dashboard/server.py` | FastAPI/uvicorn/cryptography (lazy); driven by `main` callbacks |
| `tools/*` | `core.{screen_geometry,ui_grounding,target_overlay}` (offline CLIs) |

**Orphaned modules (no importers found):** `core/stt.py`, `core/tts.py`,
`core/llm_client.py`, `core/installer.py`. They are self-contained but currently
unreferenced — worth confirming before treating them as dead (they may be
imported dynamically by name in a string somewhere).

---

## 6. Circular / risky edges to watch

- **`main` ↔ `ui`** is one-way (main → ui) but `ui` holds the settings that
  `main` reads back via `memory.config_manager` — the coupling is through the
  config file, not imports.
- **`core/gemini.py` ↔ callers**: gemini imports nothing from the app, so it is
  a clean leaf. Good.
- **`actions/screen_processor` ↔ `main`**: `main` imports the private
  `_capture_screen` / `_capture_camera` helpers directly — an internal-API edge
  that would break if those names change.
- **`plugins/self_dev.py` and `self_modification_system.py`** write into `core/`
  and `ui.py` at runtime — the only place the graph can rewrite itself. Treat
  those two as the highest-risk nodes.
- **`core/ui_grounding.py`** is imported lazily by `core/screen_geometry.py`
  (line ~846) *and* imports `screen_geometry` at module top — a genuine
  import cycle, broken only by the lazy import inside the function.
