# 🧭 Development Notes & Outstanding Issues

### ⚙️ Rendering & Performance

| Issue | Description | Suggested Solution |
|-------|--------------|--------------------|
| **1. Final concatenation is single-threaded** | Each scene is rendered in parallel (via `ProcessPoolExecutor`), but `concatenate_videoclips()` still runs in the main process — causing a bottleneck, especially for many short clips. | • Replace MoviePy concatenation with **ffmpeg concat demuxer** (direct stream copy).<br>• Use MoviePy’s `concatenate_videoclips(method="chain")` if no composition overlap is needed.<br>• Optionally parallelize concatenation in batches then merge the batches. |
| **2. Scene render startup overhead** | For many short scenes, process startup costs dominate rendering time. | • Use a persistent pool with **warm worker processes** to reuse imports.<br>• Reduce worker count for small projects (`max_workers=min(len(scenes), os.cpu_count())`). |
| **3. Logging overhead** | Each process writes verbose logs to disk (`scene_X.log`), which slows IO. | • Add verbosity levels (INFO/WARN/ERROR).<br>• Stream to memory queue for UI in real time, writing only on completion. |
| **4. GUI responsiveness** | Tkinter remains responsive but freezes occasionally during large file writes. | • Move file concatenation into a thread (similar to scene rendering).<br>• Consider switching to **async Tk loops** or PySide2 if GUI complexity grows. |

---

### 🖋️ Text Rendering & Typography

| Issue | Description | Suggested Solution |
|-------|--------------|--------------------|
| **1. Text clipping / cutoff** | Text layers (`TextClip`) sometimes lose ascenders (tops of “T”, “h”) or descenders (bottoms of “g”, “y”). | • Use `method="caption"` with vertical padding or `size=(width, None)` + `align='center'`. <br>• Apply `.resize(newsize=(width, None))` *after* setting duration to preserve font box. |
| **2. Off-centered or truncated captions** | Center alignment varies by font metrics and image scaling. | • Use anchor-based positioning (`position.anchor='center'`), or dynamically compute `(canvas_w - text.w)/2` and `(canvas_h - text.h)/2`. <br>• Measure text bounding box after creation for precise placement. |
| **3. Font fallback inconsistency** | Missing fonts cause silent fallback to DejaVuSans with different spacing. | • Cache verified Google Fonts per project.<br>• Log font substitutions clearly. |
| **4. Multi-line wrapping limits** | Long text lines overflow at smaller resolutions. | • Enable dynamic font resizing: detect text width and reduce `font_size` accordingly.<br>• Add auto word-wrapping for long captions. |

---

### 🎞️ Animation & Visual Layer Effects

| Issue | Description | Suggested Solution |
|-------|--------------|--------------------|
| **1. Limited animation types** | Currently supports basic `fadein`, `fadeout`, `slideinfromleft`, `kenburns`. | • Add: `slideinfromright`, `slideup`, `slidedown`, `zoom`, `rotate`, `pulse`, `pan`. <br>• Define animation presets in JSON (`"animation": {"type": "slideup", "easing": "easeInOut"}`). |
| **2. Easing and timing** | All motion is linear and abrupt. | • Use easing functions (e.g., `tween` or custom lambda easing curves).<br>• Add `startDelay`, `repeat`, `bounce` options in `Animation` dataclass. |
| **3. Layer ordering ambiguity** | Layers are rendered in listed order; missing `z-index` control may cause unexpected overlaps. | • Add `z_index` to `Layer` class.<br>• Sort layers before composition: `sorted(scene.layers, key=lambda l: l.z_index)`. |
| **4. Transition between scenes** | Scene-to-scene transitions are abrupt cuts. | • Add crossfade between final seconds of scene N and start of scene N+1.<br>• Implement via MoviePy `concatenate_videoclips(..., method="compose", padding=-fade_duration)`. |

---

### 🔊 Audio Handling

| Issue | Description | Suggested Solution |
|-------|--------------|--------------------|
| **1. Mismatched audio duration** | Some audio clips are slightly longer than their scene video duration, causing truncation warnings. | • Always call `.subclipped(0, safe_duration)` or `.audio.set_duration(scene_duration)` before attach. |
| **2. No background music or crossfade** | Each scene uses only its voice/audio layer. | • Add an optional global background track with fade in/out per scene. |
| **3. Missing normalization** | Audio levels vary drastically between scenes. | • Normalize RMS before concatenation using `AudioClip.volumex()` or ffmpeg filters. |

---

### 🧩 Asset Management & Robustness

| Issue | Description | Suggested Solution |
|-------|--------------|--------------------|
| **1. Asset index concurrency** | Multiple threads write to `download_index.json` simultaneously. | • Use file lock or `threading.Lock()` around `_save_download_index()` (partial fix exists).<br>• Consider `sqlite` or `tinydb` for safe concurrent access. |
| **2. Temp directory persistence** | Old temp files not cleaned after crash. | • Auto-clean `temp/` and `results/` folders on startup. |
| **3. Missing asset verification** | Broken Google Drive links crash silently. | • Validate URLs before download; mark missing ones in log but continue rendering with placeholder color clip. |

---

### 🧰 Code Quality & Maintainability

| Issue | Description | Suggested Solution |
|-------|--------------|--------------------|
| **1. Hard-coded constants** | FPS, codec, fade duration, etc. are scattered across functions. | • Move to `config.py` or top-level constants. |
| **2. Mixed MoviePy v1/v2 APIs** | Some functions use old `clip.set_duration` or `.fx()` signatures. | • Standardize to MoviePy v2 methods (`with_duration`, `with_effects`). |
| **3. Error handling duplication** | Many similar try/except blocks in rendering logic. | • Refactor into decorators (`@safe_render`) or helper for consistent logging. |
| **4. UI-logic coupling** | Tkinter class manages both UI and backend orchestration. | • Split into `render_controller.py` (backend thread manager) and `ui_renderer.py` (pure GUI). |
| **5. Lack of tests** | No automated verification for JSON parsing or rendering correctness. | • Add lightweight pytest suite for JSON→Video pipeline sanity checks. |

---

### 🧠 Other Observations

| Area | Suggestion |
|-------|-------------|
| **Font downloading** | Add caching + checksum validation for downloaded fonts. |
| **Hardware utilization** | Investigate using GPU-accelerated ffmpeg if available (`h264_nvenc`). |
| **Progress reporting** | Stream render times per scene + total ETA to UI in real time. |
| **Cross-platform** | Test on macOS & Linux; file paths and ffmpeg binary may differ. |
| **User experience** | Add “Render Summary” dialog after completion (show duration, errors, output path). |

---

### ✅ Summary: Priority Roadmap

1. **High impact / low effort**
   - Fix text clipping & centering.
   - Switch to ffmpeg concat for faster merging.
   - Add safe asset fallback and cleanup.

2. **Medium effort**
   - Expand animation variety & transitions.
   - Improve SCRAM/Stop recovery flow.

3. **Long-term**
   - Decouple UI logic.
   - Implement async progress API.
   - Add GPU encoding & robust testing.
