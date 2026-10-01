"""
Run once from the JARVIS folder:   python apply_noise_settings.py
Optional:                          python apply_noise_settings.py --ptt     (also turn on push-to-talk)
                                   python apply_noise_settings.py --undo    (restore the backup)

Edits config/api_keys.json (your API key and other settings are left alone) so
JARVIS copes with a noisy room:
  * noise_gate        on, medium   - room noise is replaced with silence (core/noise_gate.py)
  * proactive_audio   off          - otherwise the model may decide your voice "wasn't meant for it"
  * turn_tuning       on           - ignore faint starts, end your turn quickly once you stop
"""
import json
import shutil
import sys
from pathlib import Path

CFG = Path(__file__).resolve().parent / "config" / "api_keys.json"
BAK = CFG.with_suffix(".json.bak")

if "--undo" in sys.argv:
    if BAK.exists():
        shutil.copy2(BAK, CFG)
        print("Restored", CFG)
    else:
        print("No backup found.")
    sys.exit(0)

data = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {}
shutil.copy2(CFG, BAK) if CFG.exists() else None

data["noise_gate"] = {"enabled": True, "strength": "medium"}
data["proactive_audio"] = False
data["turn_tuning"] = {
    "enabled": True,
    "silence_ms": 700,
    "prefix_ms": 200,
    "start_sensitivity": "low",
    "end_sensitivity": "high",
}
if "--ptt" in sys.argv:
    data["push_to_talk_enabled"] = True

CFG.write_text(json.dumps(data, indent=4), encoding="utf-8")
print("Updated", CFG, "(backup:", BAK.name + ")")
print("Restart JARVIS. If noise still gets through, set noise_gate.strength to \"strong\".")
