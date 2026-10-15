<div align="center">

# ⚙️ MARK LV (55)

### 🤖 The Ultimate Cross-Platform Personal AI Assistant

**Hear • See • Speak • Control your computer — on any OS**

![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-blue?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.12-yellow?style=for-the-badge&logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Powered%20by-Gemini%20Live%20API-8E75B2?style=for-the-badge&logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-CC%20BY--NC%204.0-green?style=for-the-badge)

<br>

### 👑 Original Developer: [FatihMakes](https://www.youtube.com/@FatihMakes)
### 🛠️ Modified by: **MH SAMI**

<br>

[![YouTube](https://img.shields.io/badge/YouTube-@FatihMakes-red?style=for-the-badge&logo=youtube&logoColor=white)](https://www.youtube.com/@FatihMakes)
[![Instagram](https://img.shields.io/badge/Instagram-@fatihmakes-E4405F?style=for-the-badge&logo=instagram&logoColor=white)](https://www.instagram.com/fatihmakes)

</div>

---

> 💎 **Credit:** এই প্রজেক্টের মূল ডেভেলপার ও নির্মাতা **FatihMakes**। সব কৃতিত্ব তাঁর।
> এই সংস্করণে ইনস্টলেশন গাইড সহজ করা ও কিছু পরিবর্তন করেছেন **MH SAMI**।

---

## 📑 সূচিপত্র (Table of Contents)

| # | বিষয় |
|---|---|
| 1 | [🚀 ইনস্টলেশন গাইড (নতুনদের জন্য)](#install) |
| 2 | [🛠️ কোনো সমস্যা হলে (Troubleshooting)](#troubleshooting) |
| 3 | [✨ Capabilities](#capabilities) |
| 4 | [🆕 What's New in Mark LV](#whats-new) |
| 5 | [🔄 The Foundation Update](#foundation) |
| 6 | [🗺️ Roadmap](#roadmap) |
| 7 | [📋 Requirements](#requirements) |
| 8 | [🗂️ Project Structure](#structure) |
| 9 | [🔒 Your Data](#data) |
| 10 | [⚠️ License & Credits](#license) |

---

<a id="install"></a>
## 🚀 ইনস্টলেশন গাইড — একদম নতুনদের জন্য (Easy Setup Guide)

> 😊 **কোডিং বা টার্মিনাল না জানলেও সমস্যা নেই!**
> নিচের ধাপগুলো হুবহু অনুসরণ করুন। শুধু **কপি-পেস্ট** করেই পুরো JARVIS সেটআপ হয়ে যাবে।
> 💡 প্রতিটি কোড বক্সের ডান কোণায় একটি **Copy বাটন** পাবেন। সেটি চাপলেই কোড কপি হয়ে যাবে।

### 📂 ধাপ ১: প্রজেক্ট ডাউনলোড ও টার্মিনাল (PowerShell) ওপেন করা

**১. ডাউনলোড করুন** (যেকোনো একটি পদ্ধতি):

| পদ্ধতি | কীভাবে |
|---|---|
| 📦 **ZIP ডাউনলোড (সবচেয়ে সহজ)** | এই পেজের উপরে সবুজ **`<> Code`** বাটনে ক্লিক করুন, তারপর **Download ZIP** চাপুন |
| 🧑‍💻 **Git দিয়ে** | নিচের কমান্ড টার্মিনালে পেস্ট করুন |

```bash
git clone https://github.com/MHSami08/JARVIS-MARK-LV.git
cd Mark-LV
```

**২.** ZIP নিলে ফাইলটি **আনজিপ (Extract)** করুন।

**৩.** আনজিপ করা ফোল্ডারে ঢুকুন (যেখানে `main.py` ও `setup.py` ফাইল আছে)।

**৪.** ফোল্ডারের ভেতরে যেকোনো **ফাঁকা জায়গায়** কিবোর্ডের **`Shift`** চেপে ধরে মাউসের **Right Click** করুন।

**৫.** মেনু থেকে **"Open PowerShell window here"** অথবা **"Open in Terminal"** এ ক্লিক করুন।

> 🖥️ একটি নীল বা কালো স্ক্রিন ওপেন হবে। এটিই **টার্মিনাল / PowerShell**।

---

### 🐍 ধাপ ২: স্বয়ংক্রিয়ভাবে Python 3.12 ইনস্টল করা

JARVIS চালাতে কম্পিউটারে **Python 3.12** থাকতে হবে। ওয়েবসাইটে খোঁজাখুঁজি লাগবে না। নিচের কোডটি টার্মিনালে **কপি → পেস্ট → Enter** করুন:

```powershell
winget install -e --id Python.Python.3.12
```

> ⏳ স্ক্রিনে **"Successfully installed"** লেখা আসা পর্যন্ত অপেক্ষা করুন।

> [!IMPORTANT]
> ### ⚠️ খুবই জরুরি
> ইনস্টল শেষ হলে বর্তমান টার্মিনাল উইন্ডোটি **বন্ধ (Close) করুন**।
> তারপর **ধাপ ১-এর নিয়মে** ফোল্ডারে গিয়ে **নতুন করে আবার একটি টার্মিনাল ওপেন করুন**।

নতুন টার্মিনালে নিচের কোড পেস্ট করে **Enter** দিন:

```powershell
python --version
```

✅ যদি **`Python 3.12.x`** লেখা আসে, তাহলে Python সফলভাবে ইনস্টল হয়েছে!

---

### ⚙️ ধাপ ৩: অটোমেটিক সেটআপ (All-in-One Command)

আলাদা আলাদা করে কিছু করতে হবে না। **নিচের পুরো বক্সটি একসাথে কপি** করে টার্মিনালে পেস্ট করুন এবং **Enter** চাপুন:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python setup.py
```

<details>
<summary><b>🔍 এটি দিলে কী কী হবে? (ক্লিক করে দেখুন)</b></summary>

<br>

1. 🛡️ প্রথমে আপনার প্রজেক্টের জন্য একটি **আলাদা ও নিরাপদ জায়গা (Virtual Environment)** তৈরি হবে।
2. ✅ তারপর সেটি **অ্যাক্টিভ** হবে (টার্মিনালের শুরুতে `(.venv)` লেখা আসবে)।
3. 📦 এরপর JARVIS-এর জন্য প্রয়োজনীয় **সবকিছু স্বয়ংক্রিয়ভাবে ইনস্টল** হবে।

⏳ এই ধাপে কিছুটা সময় লাগবে এবং স্ক্রিনে অনেক লেখা আসবে। **ভয়ের কিছু নেই!**

</details>

🎉 সবশেষে **`✅ Setup complete!`** লেখা এলে বুঝবেন কাজ শেষ!

---

### 🎙️ ধাপ ৪: JARVIS চালু করুন!

সবকিছু সেটআপ শেষ! এবার টার্মিনালে শুধু এটি লিখে **Enter** দিন:

```powershell
python main.py
```

> 🔑 **প্রথমবার** চালু করলে স্ক্রিনে **Gemini API Key** দিতে বলা হবে। সেটি দিলেই আপনার নিজস্ব AI অ্যাসিস্ট্যান্ট ব্যবহারের জন্য তৈরি!
>
> 🆓 ফ্রি API Key এখান থেকে নিন: **[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)**

---

### ⚡ পরের বার থেকে JARVIS চালানোর সংক্ষিপ্ত নিয়ম

একবার সেটআপ হয়ে গেলে পরের বার শুধু ফোল্ডারে টার্মিনাল ওপেন করে এই দুটি কমান্ড দিলেই হবে:

```powershell
.\.venv\Scripts\activate
python main.py
```

---

<a id="troubleshooting"></a>
## 🛠️ কোনো সমস্যা হলে (Troubleshooting)

<details>
<summary><b>❌ <code>python</code> is not recognized / python চিনতে পারছে না</b></summary>

<br>

Python ইনস্টলের পর **পুরোনো টার্মিনাল বন্ধ করে নতুন টার্মিনাল** খুলেছেন কি? না খুললে এই সমস্যা হয়। নতুন টার্মিনালে আবার `python --version` দিন।

</details>

<details>
<summary><b>❌ <code>winget</code> is not recognized</b></summary>

<br>

আপনার Windows পুরোনো হতে পারে। সেক্ষেত্রে [python.org/downloads](https://www.python.org/downloads/) থেকে **Python 3.12** ডাউনলোড করে ইনস্টল করুন। ইনস্টলের সময় অবশ্যই **"Add Python to PATH"** টিক দিন।

</details>

<details>
<summary><b>❌ PowerShell-এ "running scripts is disabled" এরর আসছে</b></summary>

<br>

নিচের কমান্ডটি চালিয়ে আবার চেষ্টা করুন:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

</details>

<details>
<summary><b>❌ <code>ModuleNotFoundError</code> আসছে</b></summary>

<br>

যে মডিউলের নাম এরর-এ দেখাচ্ছে সেটি ইনস্টল করুন:

```powershell
pip install <module_name>
```

অথবা সব একসাথে:

```powershell
pip install -r requirements.txt
```

</details>

<details>
<summary><b>🍎 macOS / 🐧 Linux ব্যবহারকারীদের জন্য</b></summary>

<br>

```bash
python3 -m venv .venv
source .venv/bin/activate
python setup.py
python main.py
```

</details>

---

<a id="capabilities"></a>
## ✨ Capabilities

### Core Features
| Feature | Description |
|---|---|
| 🧑‍🎤 Holographic Avatar | An animated human head in the HUD — real facial geometry, lit and drawn in software, no GPU or extra packages |
| 👄 Real Lip-Sync | ~50 mouth shapes a second from the audio's formants **and** the transcript — closures, spreads and rounds, not a volume meter |
| 🌍 Language-Free Mouth | Articulation is derived by Unicode reduction, so Latin, Cyrillic and Greek scripts all work from one rule set — and scripts that hide pronunciation fall back cleanly |
| 🙂 Facial Acting | Brows track the phrase, gaze saccades between fixations, natural blinking, a small nod on stressed syllables |
| 😐 Face as Status | Looks away while thinking, meets your eyes while listening, lids fall while asleep, glances down at new content |
| 🎚️ Push-to-Talk | Hold **Ctrl+Space** and the mic opens — closed the rest of the time. Truly global on Windows, window-scoped elsewhere |
| 🔇 Self-Echo Guard | Never answers its own last sentence: the tail of its own voice is recognised and dropped without muting you |
| 🪪 Runtime Self-Knowledge | Name, OS, abilities **and limits** are generated from the live system each session — rename it or add a plugin and it knows |
| 🎙️ Wake Word | Local **"Hey Jarvis"** detection — sleeps until called, auto-sleeps after 2 min of silence, and never streams audio while asleep |
| ⚡ Instant Acknowledgment | Speaks a short, context-aware reply in **your language** the instant a longer task starts — no more silent waiting |
| 🚀 Faster Live Engine | Runs on **Gemini 3.1 Flash Live** — roughly 2× faster time-to-first-word than the previous model |
| 🧩 Self-Describing Skills | Every bundled skill declares its own `TOOL` dict + handler and is auto-discovered at launch — adding one is a single file |
| 🧠 Recallable Memory | No size limit and nothing silently forgotten — the prompt carries what fits, the rest is looked up on demand from a local search |
| 👁️ Memory Panel | See every fact JARVIS has stored about you, when it learned it, and delete any of it in one click |
| ↩️ Undo | Take back what the assistant did — files it moved, renamed, created or wrote, and settings it changed |
| ⚠️ Real Confirmation | Shutdown, restart and WiFi wait for a button **you** press — the model cannot confirm its own irreversible actions |
| 🎧 Audio Device Picker | Choose the microphone and speakers by name, filtered to the short list your OS shows — and measured, so every entry actually works |
| 🔗 Session Continuity | A dropped connection, a voice change or a device change no longer wipes the conversation |
| 🧩 Plugin System | Drop a single `.py` file into `plugins/` — JARVIS learns a new skill on next launch |
| 📺 Video on the HUD | Plays YouTube, a local file or any video URL **where the avatar sits** — starts muted, sound on request |
| 🪜 Model Ladder | Nine Gemini models in one measured order — a quota, a timeout or an outage steps to the next rung instead of failing |
| 🎙️ Real-time Voice | Ultra-low latency conversation in any language via Gemini Live API |
| 🎨 Live Theming | Recolour the entire HUD from a hue wheel or hex — the avatar retints with it |
| 〰️ Reactive HUD | Waveform pulses to real audio — your mic while listening, JARVIS while speaking |
| 🎙️ Voice Picker | Choose from 5 native Gemini voices and switch live from the UI — no restart |
| ♾️ Unlimited Sessions | Sliding-window context compression — one conversation can last for hours |
| 🖥️ System Control | Launch apps, adjust volume/brightness, WiFi, shortcuts, power — all by voice |
| 🧩 Autonomous Tasks | High-level planning for complex multi-step goals via agent mode |
| 👁️ Visual Awareness | Screen capture and webcam vision piped into your main Gemini session, labelled by source |
| 🧠 Persistent Memory | Deeply remembers projects, preferences, and personal context across sessions |
| ⌨️ Hybrid Input | Seamlessly switch between keyboard typing and voice commands |
| 🌅 Morning Briefing | On first boot: greets you, reads the time, recaps yesterday, and fetches live news |
| 🔔 Proactive 2.0 | Time-aware, context-aware check-ins — knows the time of day, your projects, and what you've been discussing |
| 🗓️ Session Memory | Summarises each conversation and mentions it naturally next morning — consumed after use, never repeats |
| 👁️‍🗨️ Background Monitoring | User-configured topic watching — checks for new headlines once a day and alerts naturally |
| 📊 Hardware Monitoring | Continuous CPU, RAM, GPU and temperature telemetry with localized voice alerts |
| 🌤️ Weather Report | Live weather data for your city, personalized from memory |
| 🗺️ Dynamic Content Panel | Scrollable display layer beneath the HUD that renders web results, news, and search data |
| 🔍 Multi-Mode Web Search | `news` / `research` / `price` / `compare` / `search` — Gemini Grounded first, DDG fallback |
| ⏰ Smart Reminders | OS-native scheduled notifications (Windows Task Scheduler / macOS LaunchAgent / Linux systemd) |
| 📂 File Processor | Read, summarize, and answer questions about local files |
| 🌐 Browser Control | Open URLs, navigate tabs, and interact with the browser by voice |
| 📨 Send Message | Compose and send messages through WhatsApp, Telegram, and more |
| 🖱️ Desktop Control | Taskbar, window management, and desktop-level operations |
| 🧑‍💻 Silent Language Memory | Detects spoken language on first use — all future sessions adapt automatically |
| 📱 Remote Dashboard | Control the assistant from your phone via QR code pairing |
| ⚡ Auto-Start on Boot | Registers with the OS startup system (registry / LaunchAgent / .desktop) |
| 📋 Clipboard Intelligence | Copy any text → floating panel with Translate / Summarise / Explain / Fix |
| 🪪 Assistant Customization | Change the assistant name, your name, voice, and colour from the UI — takes effect immediately |

---

<a id="whats-new"></a>
## 🆕 What's New in Mark LV

One new dependency for the whole release — `yt-dlp`, and only to turn a YouTube page into something Qt can play.

### The display

#### 📺 Video where the face is
The HUD already had a surface that takes the centre of the screen and gives it back: the camera. Video shares that same stack, so the avatar, the live camera and a video can never be on screen at once — and a video always lands exactly where you are already looking.

It accepts **a local file, a direct media URL, a YouTube link, or just a description** ("play the new Dune trailer") and searches for it. It **starts muted every time**, because a soundtrack talking over the assistant is the one way this feature could make JARVIS worse rather than better. You turn the sound on by asking, or from the button in the video header.

**It answers before it opens.** Resolving what to play takes seconds nothing can remove — measured at 2.0s for a link and 3.3s for a spoken phrase, plus buffering. Restricting yt-dlp to a lighter client was tried and made it worse: the fast clients came back with zero usable formats. So the seconds stay, and what changed is where you spend them — listening to JARVIS say it is coming, instead of watching nothing happen. Say "stop" during those seconds and the video is cancelled before it ever reaches the screen.

#### 🔀 Two streams, one picture
The first version asked YouTube for a format carrying both picture and sound and got *"Requested format is not available"*. That was not a bad selector; it was a wrong assumption. Checked against three videos — including the oldest upload on the site — **every one offered zero combined formats.** Picture and sound are separate streams now.

So there are two players running together, with a timer that corrects any drift over 300 ms. And the audio track is chosen on **language first, bitrate second** — because YouTube auto-dubs a great many videos and ships every dub at the *same* bitrate as the original: measured on one video, English at 129.483 and Arabic, Bangla, German, Spanish, French, Hindi and Indonesian all at 129.482. Sorting on bitrate alone came down to a thousandth of a kilobit, so the same video would play in Arabic one time and English the next for no reason you could see. It now reads YouTube's own original-track marker first.

#### 🔇 It stopped hearing the film
The microphone is open while a video plays, so the moment you turn the sound on, JARVIS starts answering the film. The mic now mutes itself when the video's sound goes on and unmutes when it goes off — and it says so in the activity log rather than going deaf silently.

#### 🎛 Two drawers instead of one
⚙ **SETUP** holds the things you set once — remote control, desktop shortcut, auto-start and customisation. 🎛 **CONTROLS** holds the switches you flick daily — fullscreen, morning brief, wake word, sleep, push-to-talk, HUD style. Only one is open at a time, and each sits under its own header button.

The panel used to stutter when it opened, and the obvious explanation — too many buttons — was wrong. Measured, the **first** wake-word state check took **2.104 seconds**, because it imported `openwakeword` on the UI thread the moment the drawer was built. That import now happens off-thread at boot, and the drawer opens instantly whether it has six buttons or sixteen.

> The drawer also used to vanish *behind* the video. `QVideoWidget` creates a native child window, and no Qt overlay can be drawn on top of one. The video is now a `QGraphicsVideoItem` inside a graphics view — same picture, and the interface stays where it belongs.

### Staying up

#### 🪜 Every Gemini model, in one ladder
Every one-shot Gemini call in the app now goes through `core/gemini.py`. Before this, **sixteen files named their own model — twenty-six times — and not one of them set a timeout.** When a single alias went unwell, the call did not fail; it hung.

The ladder is nine models deep, ordered by **measurement rather than guesswork**:

| Model | Measured | Model | Measured |
|---|---|---|---|
| `gemini-3.5-flash-lite` | 0.56s | `gemini-2.5-flash` | 0.67s |
| `gemini-3.1-flash-lite` | 0.60s | `gemini-2.5-flash-lite` | 0.74s |
| `gemini-flash-lite-latest` | 0.60s | `gemini-3.5-flash` | 1.13s |
| `gemini-3-flash-preview` | 504 after 14.7s | `gemini-3.6-flash` | 504 after 12.0s |
| `gemini-flash-latest` | 503 UNAVAILABLE | | |

The three that fail were **not deleted** — a model that is unwell today is a real rung tomorrow. They sit at the bottom, and a **cooldown** decides how long a failure is believed:

| What happened | Rested for | Why |
|---|---|---|
| Quota exhausted (429) | 5 minutes | Quotas refill |
| No answer (503 / 504 / DEADLINE_EXCEEDED) | 30 minutes | An outage outlasts a retry |
| Not found, or no access (404) | 6 hours | Your key does not have it, and won't in a minute |

That middle row is where the time was going. Only quota and 404 used to be cooled, so the 14-second wait on a dead model was paid **on every single call**. Measured after the fix: first call 13.15s, second 1.98s, third 1.16s — **11.2 seconds saved on every call from then on.**

**The Live model is deliberately not on this ladder.** Live models are not drop-in replacements for one another; they accept different config fields, and the same API key also exposes transcribe-live, live-translate and robotics-streaming models that will happily connect and then not behave like an assistant. So Live has exactly **two** rungs — the current model, and the one this project used before it — and it steps only on quota or loss of access. Never on a network blip or a bad key, which would otherwise walk the whole list into the same wall.

### The shape

#### 🧩 Everything bundled drives the computer
The bundled skill list had grown to seventeen, and some of it was nobody's business but its author's. **Not everyone updates games; everyone opens applications.**

Mark LV trims it to **twelve**, and every one of them does the same kind of thing: drive this machine. Applications, the browser, files, the desktop, the screen, the clock, the weather, the display. The rule is written into the project tree, so the next skill lands in the right folder without anyone having to ask.

This is not only tidiness. Every bundled skill is declared to the model on **every** connection, whether you ever use it or not. The declarations sent at startup dropped from **16,827 characters to 12,907** — roughly a thousand tokens off every session, and five fewer wrong tools for the model to reach for.

### 🩹 Fixes
* An unanswering model was retried on **every call**, at 12–15 seconds a time, because only quota and 404 failures were ever cooled down. 503/504 now rest for 30 minutes — **11.2 seconds saved per call**.
* One-shot Gemini calls had **no timeout anywhere**, in any of the sixteen files that made them. Every call now carries a deadline of at least 10 seconds.
* YouTube playback failed outright with *"Requested format is not available"* — it was asking for a combined stream that no longer exists.
* Videos played in a **random language**, because YouTube's auto-dubs carry the same bitrate as the original track.
* The settings drawer **stuttered on first open** — a 2.1-second `openwakeword` import on the UI thread, not the button count it looked like.
* The settings drawer opened **underneath the video**, because `QVideoWidget` creates a native window.
* JARVIS **answered the video's soundtrack.** The microphone now follows the video's sound.
* Qt's multimedia backend printed an ffmpeg banner to the console on every play, containing the **signed streaming URL with the viewer's IP address in it**. Silenced at startup.
* **Every launch paid 201 ms for a plugin nobody had asked to use.** Discovery executes every file in `plugins/`, and `youtube_video` imported `requests` and `youtube_transcript_api` at module scope. Deferring one of them would have saved nothing — the transcript library imports `requests` itself. Both are now checked with `find_spec`, which answers "is it installed?" without executing anything, and loaded on first use: **plugin discovery 211 ms → 39 ms**.
* A plugin that needed a file from a **newer Mark** was rejected with *"pip install core"*. The loader could not tell this project's own packages from a third-party one, so it told people to install a same-named stranger from an index — wrong, and a supply-chain hazard dressed up as a fix. First-party names now say the app is behind the plugin and that there is nothing to install.

> Built on the Mark LI–LIV foundation: the **🧑‍🎤 Holographic Avatar**, **👄 Lip-Sync**, **🎚️ Push-to-Talk**, **🔇 Self-Echo Guard**, **🧩 Plugin System**, **♾️ Unlimited Sessions**, **🎨 Live Theming** and **🎙️ Wake Word** are all still here.

---

<a id="foundation"></a>
## 🔄 The Foundation Update — in every Mark from LII

These four landed across **Mark LII, LIII, LIV and LV at the same time**, after each of those releases had already shipped. They are not what any one of those versions originally introduced; they are the floor all of them now stand on, so moving up a Mark never costs you something the one below it had.

No new dependencies. No bundled asset files. No hardcoded language, and nothing that assumes one operating system.

### 🧠 A memory that actually remembers

The store was capped at **2,200 characters — the whole memory, not per entry** — because all of it was pasted into the system prompt on every connect, so growing the memory grew every request. When it filled, the oldest entries were deleted and one line was printed to a console nobody reads. An assistant advertised as remembering "projects, preferences and personal context" was in practice a two-page notepad that quietly forgot your sister's name after a few weeks.

Storage and prompt budget are now separate problems:

* **Nothing is deleted.** The cap is a runaway guard normal use never approaches, and if it is ever hit it says so in the activity log instead of on stdout.
* **The prompt carries a core, not a dump.** Identity in full, then the most recently updated facts, budgeted — measured at **971 characters on a memory holding 62 stored facts.** That is *smaller* than the old whole-store cap, so sessions now connect with fewer tokens than before.
* **The rest is fetched on demand.** A `recall_memory` tool searches the full store locally — no network, no second model, well under a millisecond.

The part that is easy to get wrong: **a model cannot look something up if it doesn't know the thing exists.** So the prompt also carries an **index of the keys** it had no room for. Without it, "who is Ayşe?" gets "I don't know" while `ayse_sister` sits on disk unread. That index interleaves categories rather than sorting by recency — sorted like the core, a memory with forty preferences pushed the one entry the index existed for off the end.

⚙ → **🧠 MEMORY** shows every stored fact, when it was learned, and a ✕ to forget it. Everything stays in `memory/long_term.json` on your machine.

### ↩️ Undo — it can take back what it did

JARVIS moves files, renames them, writes to them and changes your settings. None of that had a way back; if it misheard you, the only remedy was to fix it by hand.

Say **"undo"** — in any language — and it reverses its own last action:

| | |
|---|---|
| **Files** | move · rename · create · copy · write · delete · organize desktop |
| **Settings** | volume · brightness · dark mode |

Three things it deliberately does *not* do:

* **It does not guess.** Settings undo reads the current value *before* changing it. Where a platform won't report that value, nothing is registered — an undo that restores a guess is worse than no undo.
* **It does not hoard.** Undoing a write means keeping the old contents in memory, so files over 1 MB are excluded and it says so rather than holding a 200 MB log for the session.
* **It does not delete your files to undo a copy.** The reverse of a copy is removing the copy; the reverse of "create a folder" is removing it *only while it's still empty*.

`organize_desktop` gets special treatment — one command that moves dozens of files, which made it the least reversible thing the assistant could do. It journals every move and puts all of them back in one go, cleaning up the folders it created if they're still empty.

**Undo costs nothing at runtime.** It appends a closure to a list; nothing in it runs unless you ask.

### ⚠️ A confirmation the model can't forge

The old gate read like this:

```python
if action in _DANGEROUS_ACTIONS:            # {"restart", "shutdown"}
    confirmed = str(params.get("confirmed", "")).lower()
```

`confirmed` is a **tool parameter, which means the model fills it in.** Nothing stopped it sending `confirmed=yes` on the first call and nothing checked that a human was ever involved. It was a convention, not a gate. And its coverage was two actions — so `toggle_wifi`, which cuts the assistant's own connection to the Live API and therefore *cannot be asked to undo itself*, went through with no gate at all.

The token is now issued by the interface. Shutdown, restart and WiFi put a banner on the HUD and **return immediately**; the action runs only if you press CONFIRM. Nothing blocks — JARVIS keeps talking while the banner is up — so this is **cheaper than the old gate**, which burned two tool round trips on every power command.

> The split between the two mechanisms is about reversibility, not about how alarming a word sounds. Anything undoable is done at once; only the genuinely irreversible asks. An assistant that checks with you before turning the volume down is one you stop talking to.

### 🎧 It finally asks which microphone

Both audio streams opened with no device argument at all, so they always took whatever the OS called "default" — and on Windows that *moves on its own* the moment you plug a headset in. "JARVIS can't hear me" almost always meant "JARVIS is listening to the webcam".

⚙ → **🎧 AUDIO DEVICES** lets you pick the microphone and the speakers by name. Two things matter more than the dropdown:

**The list is short.** `query_devices()` returns one entry per *device × host API*, not per device — measured on an ordinary Windows machine, **41 entries for what the sound settings show as 4 microphones and 4 speakers.** The same microphone appears four times, under MME, DirectSound, WASAPI and WDM-KS, with nothing to say which is which. That is not a choice, it's a quiz. The picker takes one host API per direction, drops the "Sound Mapper" and "Primary Sound Driver" pseudo-devices that just mean "default", and deduplicates. **41 → 8.**

**Every entry has been measured, not assumed.** The obvious approach is to pick the host API with the nicest names — WASAPI on Windows, which in shared mode **doesn't resample**, so with 16 kHz in and 24 kHz out against 48 kHz hardware every open failed. Adding a rate check and moving to DirectSound passes that test on both sides, and PortAudio's DirectSound **output is a silent sink**: the stream opens, every write returns success in ~0 ms, and not one sample reaches the speakers.

| | write(2.0 s) took | |
|---|---|---|
| MME | **2.02 s** | consumed in real time |
| DirectSound | **0.00 s** | swallowed instantly |

No capability flag reports that. So the app measures it — once per host API per direction, on a background thread at startup, using silence. Two consequences worth stating plainly:

* **Each direction picks its own host API.** On Windows this lands on DirectSound for the microphone and MME for the speakers — a split no amount of reasoning would have produced.
* **The probe runs in the mode the app actually ships.** DirectSound input passes a callback stream and fails a blocking read; probing the wrong mode rejected a microphone that works perfectly.

Your choice is stored **by name, not by index** — indices shift whenever something is plugged in. If the saved device is gone, it falls back to the system default and says so in the log rather than failing to start.

### 🔗 It stops forgetting the conversation when the connection drops

`session_resumption` was switched on in the config and the handle the server sent back was **never read** — so every reconnect started an empty session. A dropped packet, or simply changing the voice, wiped the conversation. "Unlimited sessions" leaked through exactly this hole.

The handle is captured and replayed now. A network blip, or switching your microphone, keeps the conversation intact.

It is held in memory only, deliberately: writing it to disk would make a fresh launch continue yesterday's chat, which sounds appealing but breaks the session-summary flow — a conversation that never ends never produces a summary, and the "yesterday we talked about…" line in the morning briefing silently disappears. Changing the **voice** also starts clean on purpose, since resuming restores the server's session state and would likely bring the old voice back with it.

### 🩹 Fixes that came with it

* **The assistant could die on a log line.** Status lines carry emoji and arrows (`📤 file_controller → Moved: a.txt → Documents/`). On a non-UTF-8 console — cp1254 on a Turkish Windows, cp1251 on a Russian one, cp932 on a Japanese one — printing one raises `UnicodeEncodeError`, and because that print sits *after* the tool's own `try/except`, it escaped into the receive loop and took the session down.
* **Every computer command paid for two model round trips.** `computer_settings` made an *entire second Gemini call, inside the tool*, purely to translate the request into one of its own action names — because the declaration only said "The action to perform", so the model rarely filled it in. When that second call failed, the fallback was `description.lower().replace(" ", "_")`, which turns the Turkish for "turn it down" into `sesi_kis` and straight into "Unknown action". The declaration now names all 56 actions and the rest is spelling tolerance handled locally by `difflib` in microseconds. When nothing matches it suggests real action names instead of dead-ending.
* An unresolvable saved audio device, or one the driver refuses to open, falls back to the system default and says so — on both the microphone and the speakers.
* A rejected session-resumption handle is dropped after one attempt, so an expired handle can never be replayed on every retry and prevent the reconnect it exists to protect.

---

<a id="roadmap"></a>
## 🗺️ Mark Roadmap

| Mark | Focus |
|---|---|
| **XLIX** | Auto-start · clipboard intelligence · assistant customization |
| **L** | Session memory · background monitoring · proactive 2.0 · instant vision |
| **LI** | Plugin system · affective dialog · proactive audio · unlimited sessions |
| **LII** | Voice picker · live theming · reactive HUD · recallable memory · undo · real confirmation · audio device picker · session continuity |
| **LIII** | Wake word · Gemini 3.1 Flash Live · instant acknowledgment · self-describing action/plugin architecture |
| **LIV** | Holographic avatar · viseme lip-sync · facial acting · face-as-status · push-to-talk · self-echo guard · runtime self-knowledge & limits |
| **LV** | Video on the HUD · model ladder with measured fallback · split settings drawers · trimmed bundled skill list |
| *shared* | The last five above also shipped to LIII, LIV and LV at the same time — moving up a Mark never loses them |
| **LVI+** | Interrupt by voice · conversation history · Telegram remote · full file access · security camera · Obsidian |

---

<a id="requirements"></a>
## 📋 Requirements

| Requirement | Details |
| --- | --- |
| **OS** | Windows 10/11, macOS, or Linux |
| **Python** | 3.11, 3.12 or 3.13 |
| **Microphone** | Required for voice interaction (and for the "Hey Jarvis" wake word) |
| **Speakers** | Required for voice replies |
| **API Key** | Free Gemini API key (entered on first launch → `config/api_keys.json`) |
| **GPU** | **Not required.** The avatar is rendered in software, and so is HUD video |
| **YouTube on the HUD** | `yt-dlp`, installed by `setup.py`. Without it, local files and direct URLs still play and YouTube links open in the browser with an explanation |
| **Wake word** *(optional)* | One-click download from ⚙ → WAKE WORD (`openwakeword`, a few MB, fully local) |

> `setup.py` only ever installs what your operating system needs — the Windows-only libraries are skipped automatically on macOS and Linux, and vice-versa. It also checks your Python version up front, so a wrong interpreter fails with a sentence instead of a wall of pip output. Prefer to do it by hand? `pip install -r requirements.txt` works too.
>
> The optional **wake word** engine is *not* installed by setup — grab it in one click from **⚙ → WAKE WORD** inside the app.

---

<a id="structure"></a>
## 🗂️ Project Structure

```
Mark LV/
├── main.py                   # Core loop — Gemini Live session, audio I/O, viseme extraction, tool dispatch
├── ui.py                     # PyQt6 HUD — avatar canvas, waveform, log panel, settings drawer, camera feed
├── setup.py                  # OS-aware installer (skips wrong-OS dependencies, checks your Python)
├── .gitignore                # Keeps your API key, TLS key and memories out of the repository
├── plugins/
│   └── _template.py          # Copy this to write a new skill — one file, drop in, done
├── actions/                  # Bundled skills — each self-describes via a TOOL dict + handler
│                             #   Everything here drives the COMPUTER, which is what decides
│                             #   whether a new skill belongs in this folder at all.
│   ├── web_search.py         # Gemini + DDG parallel search (news, research, price, compare)
│   ├── screen_processor.py   # Screen & webcam capture for vision
│   ├── background_monitor.py # User-configured topic watching — daily DDG check
│   ├── proactive.py          # Proactive 2.0 — time/context/rotation-aware check-ins
│   ├── reminder.py           # OS-native scheduled notifications
│   ├── system_monitor.py     # CPU / RAM / GPU / temperature telemetry
│   ├── computer_settings.py  # Volume, brightness, WiFi, power (per-OS)
│   ├── computer_control.py   # Keyboard shortcuts, mouse, window management
│   ├── open_app.py           # Application launcher (per-OS name map)
│   ├── browser_control.py    # Web browser control
│   ├── file_controller.py    # File system operations
│   ├── file_processor.py     # Document reading and summarization
│   ├── send_message.py       # Messaging integration
│   ├── weather_report.py     # Live weather data
│   ├── video_player.py       # Plays video on the HUD, where the avatar normally is
│   └── desktop.py            # Desktop and taskbar control
├── memory/
│   ├── memory_manager.py     # Load/save long_term.json — sessions, monitors, identity
│   ├── config_manager.py     # api_keys.json access — key, OS, name, voice, colour, toggles
│   └── long_term.json        # Persistent store — created on first run
├── core/
│   ├── gemini.py             # One place for every one-shot Gemini call — model ladder, timeouts, cooldowns
│   ├── prompt.txt            # All prompt wording — {tokens} are filled from the live system at startup
│   ├── avatar.py             # Avatar renderer — lighting, pose, expression, mouth (QPainter)
│   ├── avatar_mesh.py        # Head geometry — loads the face, generates skull/neck/rigs
│   ├── face_model.obj        # The face itself (MediaPipe canonical model, Apache-2.0, 25 KB)
│   ├── viseme.py             # Transcript → mouth shapes, fused with the audio's timing
│   ├── echo.py               # Tells your voice from the assistant's own echo; self-calibrating
│   ├── hotkey.py             # Push-to-talk chord — global on Windows, windowed fallback elsewhere
│   ├── undo.py               # One shared undo stack — actions register how to reverse themselves
│   ├── confirm.py            # Irreversible-action gate — the token is issued by the UI, not the model
│   ├── audio_devices.py      # Microphone / speaker list — filtered, measured, resolved by name
│   ├── plugin_loader.py      # Plugin engine — discovery, validation, crash isolation
│   ├── action_loader.py      # Bundled-action engine — the built-in twin of plugin_loader
│   └── wake_word.py          # Local "Hey Jarvis" detector — own thread, offline, opt-in
└── config/
    ├── api_keys.json         # API key, name, voice, colour, toggles — created on first launch (git-ignored)
    └── certs/                # Self-signed TLS pair for the phone dashboard — generated locally (git-ignored)
```

---

## 🙏 Third-Party Assets

| Asset | Source | Licence |
| --- | --- | --- |
| `core/face_model.obj` | [MediaPipe](https://github.com/google-ai-edge/mediapipe) canonical face model — 468 vertices of measured human face geometry | Apache License 2.0 |

---

<a id="data"></a>
## 🔒 Your Data

Everything stays on your machine. There is no MARK server, no telemetry and no account.

| What | Where | Notes |
|---|---|---|
| Gemini API key, plugin credentials | `config/api_keys.json` | **Plaintext.** Anyone with your user account can read it. Treat it like a password file. |
| Dashboard TLS certificate + private key | `config/certs/` | Generated locally, self-signed, never leaves the machine. |
| What the assistant remembers about you | `memory/long_term.json` | Delete the file to make it forget everything. |

All three are listed in `.gitignore`, so a fork or a pull request cannot leak them by accident. **If you have already committed `config/api_keys.json` anywhere public, revoke that key** at [aistudio.google.com](https://aistudio.google.com/app/apikey) and generate a new one — removing the file in a later commit does not remove it from the history.

Your voice is streamed to Google's Gemini Live API while a session is open; that is the one thing that leaves your computer, and it stops when you mute or close the app.

---

<a id="license"></a>
## ⚠️ License

Personal and non-commercial use only.
Licensed under **[Creative Commons BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)**.

---

## 👤 Credits

<div align="center">

### 👑 Original Creator & Main Developer — **FatihMakes**
*Engineered by a developer building a real-world JARVIS-style assistant.*

| Platform | Link |
| --- | --- |
| 📺 YouTube | [@FatihMakes](https://www.youtube.com/@FatihMakes) |
| 📸 Instagram | [@fatihmakes](https://www.instagram.com/fatihmakes) |

### 🛠️ Modified by — **MH SAMI**
*Simplified installation guide & documentation improvements.*

<br>

⭐ **ভালো লাগলে Repository-তে একটি Star দিন এবং মূল নির্মাতাকে সাপোর্ট করুন!** ⭐

*Star the repository to support the journey to Mark 100.*

</div>
