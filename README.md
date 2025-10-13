# 🎬 JSON to VIDEO — Renderer (MoviePy + Tkinter)

**A JSON-driven video composition and rendering pipeline built with MoviePy (v2) and a Tkinter UI.**  
This project converts scene descriptions (JSON) into stitched videos, with per-scene parallel rendering, asset management, font fetching, and a simple GUI for previewing and launching renders.

---

## 🚀 Project Overview

`JSON to VIDEO` consumes a scene composition JSON file and produces a finished video by:
1. Downloading required assets (images, audio, fonts).
2. Rendering each scene as an independent video clip (parallelizable).
3. Concatenating scene clips into a final video.
4. Providing a Tkinter-based UI (`UI_moviePy.py`) to preview, configure, and run renders, plus per-scene logging and emergency controls (SCRAM).

This repository uses **MoviePy 2.x** APIs and aims to be robust against partial failures (fallback scenes, logging) while keeping a simple workflow for non-technical users.

---

## ✨ Features

- JSON-driven scene specification (layers, animations, timings).
- Parallel scene rendering using `ProcessPoolExecutor` to leverage multi-core CPUs.
- Asset caching and download index for Google Drive links (via `gdown`).
- Google Fonts integration (optional) with fallback font handling.
- Tkinter UI for importing projects, previewing scenes, downloading assets, and launching renders.
- Per-scene logs captured from child render processes; visible in the UI.
- Graceful Stop (finish current scene) and SCRAM (immediate hard kill) controls.
- Safe fallbacks for missing assets or rendering broadcast errors (blank scene fallback).

---

## ⚙️ Requirements & Recommendations (Windows)

- **OS:** Windows 10 / 11 recommended.
- **Python:** 3.10 — 3.12 (use latest stable within this range).
- **FFmpeg:** Required and must be on `PATH`. Download: https://ffmpeg.org/download.html
  - After installing, ensure the `ffmpeg` executable is available in the Command Prompt.
  - Optional: If you have an NVIDIA GPU and want faster encoding, install the appropriate NVENC-enabled ffmpeg build and make sure your GPU drivers are current.
- **CPU / RAM:** Multi-core CPU recommended for parallel rendering; available RAM affects the number of simultaneous processes.

---

## ⚡ Setup (Windows)

1. **Clone repository** (or download and extract ZIP):
   ```bash
   git clone https://github.com/votuduc/mcp_Agents.git
   ```

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv .venv   # Create
   ```
   ```bash
   .\.venv\Scripts\Activate.ps1   # Activate
   ```

3. **Upgrade pip (optional but recommended):**
   ```bash
   python -m pip install --upgrade pip
   ```

4. **Install dependencies** using the provided `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```

5. **Install FFmpeg** and add it to your PATH (see official download page). Confirm installation:
   ```bash
   ffmpeg -version
   ```

6. **Google Fonts API (optional but recommended for custom fonts)**:
   - Get an API key from Google Fonts Developer API.
   - Create a file named `.env` (in the project root) containing:
     ```text
     GOOGLE_FONTS_API_KEY=your_api_key_here
     ```

7. **(Optional) Allow executable permissions** for scripts if required by your environment.

---

## 🏃 How to run

### GUI (recommended)
Run the Tkinter UI which is the main user-facing entry point:
```bash
python UI_moviePy.py
```
Use the UI to import your JSON (default file `scene_composition_agent_output.json`), download assets, tweak resolution/fps, and start rendering. You can view per-scene logs in the UI and use **Stop** or **SCRAM** controls as needed.

### CLI (developer)
There is also a CLI entry point in `final_solution.py` (single-file runner):
```bash
python final_solution.py path/to/project.json
```
> Note: The UI currently depends on `final_solution` functions for backend orchestration. If you prefer CLI-only workflows, `final_solution.py` contains the core pipeline functions (download, render scenes, concatenate).

---

## 📁 Project Structure

```
├─ /.venv/                      # optional virtual env (gitignored)
├─ /assets/                     # downloaded images/audio/fonts cache
│   ├─ audio/
│   ├─ images/
│   └─ fonts/
├─ /results/                    # rendered final videos and logs
├─ /temp/                       # temporary scene outputs (auto-clean recommended)
├─ UI_moviePy.py                # Tkinter-based UI (main entrypoint for now)
├─ final_solution.py            # Core rendering backend used by UI and CLI
├─ scene_composition_agent_output.json  # example/default JSON input
├─ requirements.txt             # Python package dependencies
└─ README.md                    # (this file)
```

---

## 🔁 Workflow Summary

1. Author a scene JSON describing `videoMetadata` and `scenes[]` (layers, audioUrl, animations).
2. Open `UI_moviePy.py` and **Import JSON**. Review scenes in the Preview tab.
3. Click **Download Assets** to fetch images, audio and fonts. These are cached under `/assets/` and tracked in `download_index.json`.
4. Configure resolution/fps if needed on the Preview tab. Press **Start Rendering** in the Render tab.
5. Each scene is rendered in a separate worker process (parallel). Per-scene logs are created (e.g., `logs/scene_1.log`).
6. On completion, scene MP4s are concatenated into a final video in `/results/` and a JSON log summarizing the render is saved (includes timing and system info).

---

## 🛠 Troubleshooting & Tips (Windows)

- **`ffmpeg` not found**: Ensure ffmpeg is installed and added to PATH. Restart your terminal if newly installed.
- **Fonts rendering oddly or missing glyphs**: Verify your `GOOGLE_FONTS_API_KEY` in `.env` and ensure fonts downloaded into `/assets/fonts/`. If fonts fail, the fallback `DejaVuSans.ttf` is used.
- **Text clipped / wrong position**: Try enabling `"method": "caption"` for text layers in JSON or increase canvas height/vertical padding.
- **Slow concatenation on many short scenes**: See `DEVELOPMENT_NOTES.md` — consider using ffmpeg concat demuxer or batching concatenation.
- **Child process crashes**: Check per-scene log files in `/results/` or `temp/` to see MoviePy / ffmpeg output. Use SCRAM to force-kill hung processes and inspect logs.
- **Audio desync or truncation**: Make sure audio durations are accurately specified in JSON and the scene duration field; backend subclips audio to scene safe duration before attach.

---

## 🧭 Development Notes & Roadmap

See `DEVELOPMENT_NOTES.md` for a comprehensive list of known issues, suggested fixes, and the priority roadmap. Key short-term items include improving text layout, speeding up concatenation (ffmpeg), and expanding animation options.

---

## 🧪 Testing & Contribution

- Add unit tests for JSON parsing and small scene render smoke tests (can be in a `tests/` folder).
- When contributing: branch from `main`, open a PR, include a short description and link to any rendered example videos if possible.
- Follow coding style PEP8/flake8 for new Python code.

---

## 🙋 Need help?

Me too 😭!
