# Setting up Rosie on Windows

About 30 minutes, most of it downloading the model. Do this **after your exams**.
Everything goes on the `D:` drive so `C:` stays clean.

Run the commands in **PowerShell** (Start menu -> "PowerShell").

## 1. Install the tools

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
winget install -e --id Ollama.Ollama
```

Close and reopen PowerShell afterwards so the new commands are found.
Check: `python --version` shows 3.12, `git --version` and `ollama --version` print versions.

## 2. Keep the model on D:

Ollama stores models in your user folder on `C:` by default (several GB). Move it:

```powershell
setx OLLAMA_MODELS "D:\Rosie\ollama-models"
```

Quit Ollama from the tray icon and start it again, then pull Rosie's brain (about 5 GB):

```powershell
ollama pull qwen3:8b
ollama run qwen3:8b "Say hi in five words"
```

16 GB RAM runs it fine. If it is slow, `ollama pull qwen3:4b` and set `model: "qwen3:4b"`
in step 4.

## 3. Get Rosie

**Quick way**: clone, then let the installer do steps 3 to 5 (it never overwrites your
config or `.env`, so it's safe to run again after an update):

```powershell
mkdir D:\Rosie
git clone https://github.com/renissshh/rosie.git D:\Rosie\app
cd D:\Rosie\app
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
# add -Voice for the microphone and voices, -Orb to build the orb app (needs Rust + Node)
```

It creates `.venv`, `config\rosie.yaml` (data on `D:\Rosie`) and `.env`, sets two user
environment variables (`ROSIE_CONFIG`, `ROSIE_CORE`) so the orb can start Rosie at login,
sets up rosie-vault and runs `rosie doctor`. No admin rights needed.

**By hand**, if you prefer:

```powershell
mkdir D:\Rosie
cd D:\Rosie
git clone https://github.com/renissshh/rosie.git app
cd app
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

If PowerShell refuses to run scripts later, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 4. Configure

```powershell
copy config\rosie.example.yaml config\rosie.yaml
copy .env.example .env
notepad config\rosie.yaml
```

In `rosie.yaml`, set `user_vault_dir` to your Obsidian vault, for example
`user_vault_dir: "D:/Obsidian/MyVault"` (forward slashes are fine). Rosie only reads it.
Leave `.env` empty for now; keys are only needed for the optional cloud fallback.

## 5. Check and talk

```powershell
.venv\Scripts\rosie doctor
.venv\Scripts\rosie chat
```

`doctor` should print `All good`. Each `[fail]` line says what to fix, for example
`run ollama serve` or `run ollama pull qwen3:8b`.

Try: "what day is it?", "what's in my DBMS note?". Type `/exit` to leave.

## 6. Voice (optional, Sprint 4)

```powershell
.venv\Scripts\python -m pip install -e ".[voice]"
```

To check speech-to-text speed, record a few short sentences as 16 kHz mono WAV files
(Audacity: Project Rate 16000, Tracks -> Mix -> Mono, export WAV) into a folder, with
a `.txt` next to each holding what you said (`remind.wav` + `remind.txt`). Then:

```powershell
.venv\Scripts\rosie stt-bench D:\Rosie\samples
```

It downloads the model once into `D:\Rosie\models` and saves a report to
`D:\Rosie\logs\stt-bench.md`. Under ~1.5 s per sentence feels conversational.

Hear Rosie's voices (`rosie voices` lists them) and keep the one you like as `voice:` in
`config\rosie.yaml`:

```powershell
.venv\Scripts\rosie say "Good evening, VinsmokE. Your DBMS exam is in 16 days." --voice kokoro-george
```

## Where things live

| Path | What |
| --- | --- |
| `D:\Rosie\app` | Rosie's code (this repo) |
| `D:\Rosie\rosie-vault` | Rosie's own notes: daily, tasks, memory, logs (`rosie vault` creates it) |
| `D:\Rosie\index` | Search index, memory index and scheduled jobs (safe to delete except `scheduler.db`) |
| `D:\Rosie\logs` | `rosie.log` and `tool_calls.jsonl` (every action she took) |
| `D:\Rosie\SOUL.md` | Optional: your own edit of her personality (copy `config\SOUL.md`) |
| `D:\Rosie\ollama-models` | The downloaded LLM |
| `D:\Rosie\models` | Speech models (Sprint 4) |
