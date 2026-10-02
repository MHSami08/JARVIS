import os
import io
import re
import sys
from pathlib import Path

# Fixes the "core not found" error by ensuring the root directory is recognized
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core import confirm, gemini
from google.genai import types as gtypes

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = _base_dir()
PLUGINS_DIR = BASE_DIR / "plugins"

def _clean_code(text: str) -> str:
    """Removes markdown formatting if Gemini accidentally includes it."""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()

# Renamed the main function to "run"
def run(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower()

    # -------------------------------------------------------------------------
    # ACTION 1: ANALYZE UI (Vision)
    # -------------------------------------------------------------------------
    if action == "analyze_ui":
        try:
            import pyautogui
            if player: player.write_log("SYS: Taking screenshot for UI analysis...")
            
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_bytes = buf.getvalue()

            prompt = (
                "You are an expert Python UI/UX developer. Look at this screenshot of my interface. "
                "Identify any visual bugs, alignment issues, color clashes, or areas for improvement. "
                "Provide a short summary of what is wrong, and explicitly tell me what specific Python "
                "code I need to change in my codebase (like ui.py) to fix it."
            )

            res = gemini.call(
                [gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
                tier=gemini.SMART, 
                timeout_ms=45_000
            )
            return getattr(res, "text", "Analysis failed.") if res else "Failed to reach Vision model."
        except ImportError:
            return "Missing pyautogui module. Please install it."
        except Exception as e:
            return f"UI Analysis failed: {e}"

    # -------------------------------------------------------------------------
    # ACTION 2: UPDATE OWN CODE (With Permission)
    # -------------------------------------------------------------------------
    elif action == "update_code":
        file_name = parameters.get("file_name", "")
        instruction = parameters.get("instruction", "")
        file_path = BASE_DIR / file_name

        if not file_path.exists():
            return f"Cannot update. File '{file_name}' does not exist in my root directory {BASE_DIR}."

        if player: player.write_log(f"SYS: Drafting updates for {file_name}...")

        current_code = file_path.read_text(encoding="utf-8")
        prompt = (
            f"You are an expert Python developer. Apply the following instruction to the code below.\n"
            f"Instruction: {instruction}\n\n"
            f"CRITICAL: Return ONLY the raw, complete, updated python code. Do not include markdown backticks. "
            f"Do not truncate. Ensure the file works perfectly.\n\nCode:\n{current_code}"
        )

        res = gemini.text(prompt, tier=gemini.SMART, timeout_ms=60_000)
        if not res:
            return "Failed to generate updated code."

        new_code = _clean_code(res)

        def apply_update():
            file_path.write_text(new_code, encoding="utf-8")
            return f"Code updated successfully in {file_name}! You may need to restart me to see the changes."

        if confirm.pending_title():
            return "There is already a confirmation waiting on screen."
        
        return confirm.request(
            key="update_core_code",
            title=f"⚠️ PERMISSION TO UPDATE {file_name.upper()}",
            detail=f"I want to modify my core file: {file_name}\nChange requested: {instruction}\n\nDo you allow this core system update?",
            run=apply_update
        )

    # -------------------------------------------------------------------------
    # ACTION 3: CREATE NEW PLUGIN (With Permission)
    # -------------------------------------------------------------------------
    elif action == "create_plugin":
        plugin_name = parameters.get("plugin_name", "").replace(" ", "_").lower()
        if not plugin_name.endswith(".py"):
            plugin_name += ".py"
        description = parameters.get("instruction", "")
        
        if player: player.write_log(f"SYS: Writing new plugin: {plugin_name}...")

        prompt = (
            f"Write a complete, working Python plugin for my JARVIS assistant named '{plugin_name}'.\n"
            f"Purpose: {description}\n\n"
            f"Rules:\n"
            f"1. It must contain a 'run' function taking (parameters, response=None, player=None, session_memory=None).\n"
            f"2. It must contain a PLUGIN dictionary at the bottom defining 'name', 'description', 'parameters', and 'run'.\n"
            f"3. Return ONLY the raw python code. No markdown formatting or explanations."
        )

        res = gemini.text(prompt, tier=gemini.SMART, timeout_ms=45_000)
        if not res:
            return "Failed to generate plugin code."

        new_plugin_code = _clean_code(res)
        file_path = PLUGINS_DIR / plugin_name

        def apply_plugin():
            file_path.write_text(new_plugin_code, encoding="utf-8")
            return f"Plugin '{plugin_name}' created successfully in the plugins folder! I will load it automatically on my next boot."

        if confirm.pending_title():
            return "There is already a confirmation waiting on screen."

        return confirm.request(
            key="create_new_plugin",
            title="🧩 PERMISSION TO CREATE PLUGIN",
            detail=f"I want to create a new capability: {plugin_name}\nPurpose: {description}\n\nDo you allow me to write this file to the plugins directory?",
            run=apply_plugin
        )

    return f"Unknown self-dev action: {action}"

# ── Plugin Declaration ──────────────────────────────────────────────────────────
PLUGIN = {
    "name": "jarvis_self_developer",
    "description": "CRITICAL: Use THIS tool (not dev_agent) when the user asks you to update your OWN UI, edit your OWN codebase, or create new JARVIS plugins for yourself. Use 'analyze_ui' to take a screenshot and find visual/UI bugs. Use 'update_code' to apply fixes to core files like 'ui.py'. Use 'create_plugin' to build brand new JARVIS plugins.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Must be exactly one of: analyze_ui | update_code | create_plugin"
            },
            "file_name": {
                "type": "STRING",
                "description": "The exact core file to edit (e.g. 'ui.py', 'main.py'). Only needed for update_code."
            },
            "plugin_name": {
                "type": "STRING",
                "description": "The desired file name for the new plugin (e.g. 'weather_tool.py'). Only needed for create_plugin."
            },
            "instruction": {
                "type": "STRING",
                "description": "What exact code changes to make, or what the new plugin should do."
            }
        },
        "required": ["action"]
    },
    "run": run,  # Mapped to "run" as required by the plugin loader
}