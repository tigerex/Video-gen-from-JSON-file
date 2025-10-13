#!/usr/bin/env python3
"""
ui_renderer.py — Updated GUI with:
 - Parallel multi-process rendering (user-selectable workers + Auto)
 - Per-scene logs streamed to UI
 - MoviePy/ffmpeg logs captured from child processes
 - Graceful Stop (finish current scenes, cancel pending)
 - SCRAM (hard emergency kill) — immediately kills all child processes and resets UI
 - Improved error handling for resolution mismatch: child wrapper will log detailed info,
   and on a broadcasting ValueError will produce a safe fallback blank video for that scene
   so the overall render process can continue for demo purposes.

Notes:
 - Keeps using final_solution.render_scene as the canonical renderer. No changes required
   to final_solution.py for the UI to work. However, for a permanent fix to broadcast errors,
   patch final_solution.render_scene to ensure each clip is resized to (width, height).
 - Save next to your final_solution.py and scene JSON files.
"""

import os
import sys
import threading
import queue
import time
import math
import json
import shutil
import traceback
from datetime import datetime
from pathlib import Path

# GUI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Image thumbnails
from PIL import Image, ImageTk

# Audio preview (optional)
try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:
    PYGAME_AVAILABLE = False

# System info and process control
import psutil

# Parallel futures
from concurrent.futures import ProcessPoolExecutor, as_completed, CancelledError

# MoviePy for final concatenation (main process)
from moviepy import VideoFileClip, concatenate_videoclips, ColorClip

# Dotenv (for fonts API key)
from dotenv import load_dotenv
load_dotenv()

# Try to import backend functions from final_solution.py
try:
    from final_solution import (
        load_project_from_json,
        parallel_download_assets,
        render_scene,            # used inside child processes
        get_local_asset_path,
        ASSET_DIRS,
    )
    BACKEND_AVAILABLE = True
except Exception as e:
    print("⚠️ Could not import final_solution backend:", e)
    BACKEND_AVAILABLE = False

# Global queues for logs and UI events
LOG_QUEUE = queue.Queue()
UI_QUEUE = queue.Queue()

# Application state dictionary
app_state = {
    "project": None,
    "json_path": None,
    "assets_ready": False,
    "render_thread": None,
    "render_cancel": False,
    "executor": None,
    "temp_dir": None,
    "scene_outputs": [],
    "render_progress": {
        "completed": 0,
        "total": 0,
        "scene_times": [],
        "start_time": None
    }
}


# -----------------------------
# Helpers: logging & UI events
# -----------------------------
def now_ts():
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str):
    """Push a message into the LOG_QUEUE for main thread to display."""
    LOG_QUEUE.put(f"[{now_ts()}] {msg}")


def ui_put(evt: str, payload):
    """Queue a UI event for main thread to handle."""
    UI_QUEUE.put((evt, payload))


# -----------------------------
# Audio (pygame) helpers
# -----------------------------
def ensure_pygame():
    if not PYGAME_AVAILABLE:
        return False
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return True
    except Exception as e:
        log(f"⚠️ pygame init failed: {e}")
        return False


def play_audio_file(path: str):
    if not ensure_pygame():
        log("Audio playback unavailable (pygame).")
        return
    try:
        pygame.mixer.music.stop()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        log(f"▶ Playing audio {os.path.basename(path)}")
    except Exception as e:
        log(f"⚠️ Error playing audio: {e}")


def stop_audio_playback():
    if PYGAME_AVAILABLE and pygame.mixer.get_init():
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass


# -----------------------------
# Child wrapper (picklable top-level function)
# -----------------------------
def _child_render_wrapper(scene, width, height, api_key, temp_dir, scene_log_path):
    """
    Executed in a child process. Redirects stdout/stderr to scene_log_path so ffmpeg/moviepy Child
    output is captured. Calls final_solution.render_scene(scene, width, height, api_key, temp_dir).
    If render_scene raises a ValueError related to broadcasting shapes, we log and create
    a safe blank fallback video for that scene to keep the pipeline moving (demo-friendly).
    Returns dict: {"scene_id", "out_path", "log_path"} on success, or raises on fatal error.
    """
    import sys
    import traceback

    # Ensure log dir exists
    os.makedirs(os.path.dirname(scene_log_path), exist_ok=True)

    def write_log_line(s):
        try:
            with open(scene_log_path, "a", encoding="utf-8", errors="replace") as lf:
                lf.write(f"{s}\n")
        except Exception:
            pass

    start_msg = f"--- Child render start: scene {scene.scene_id} | target {width}x{height} ---"
    write_log_line(start_msg)

    # Redirect stdout/stderr in child to scene_log_path
    try:
        with open(scene_log_path, "a", encoding="utf-8", errors="replace") as lf:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = lf, lf
            try:
                # Call backend renderer (this may call MoviePy/ffmpeg)
                out_path = render_scene(scene, width, height, api_key, temp_dir)
            finally:
                # flush and restore
                try:
                    sys.stdout.flush()
                    sys.stderr.flush()
                except Exception:
                    pass
                sys.stdout, sys.stderr = old_out, old_err

        # If we get here, render_scene succeeded
        write_log_line(f"--- Child render completed: scene {scene.scene_id} -> {out_path} ---")
        return {"scene_id": scene.scene_id, "out_path": out_path, "log_path": scene_log_path}

    except Exception as exc:
        # Record the exception and traceback into child log
        tb = traceback.format_exc()
        write_log_line("\n--- EXCEPTION IN CHILD ---")
        write_log_line(str(exc))
        write_log_line(tb)

        # If it's a broadcasting ValueError, create a safe fallback to avoid whole-pipeline death.
        msg = str(exc).lower()
        if isinstance(exc, ValueError) and ("broadcast" in msg or "could not be broadcast" in msg or "shapes" in msg):
            write_log_line("--- Detected broadcasting ValueError — creating fallback blank scene to continue demo ---")
            try:
                # Create a safe blank clip (duration from scene.audioDuration_sec if present)
                dur = getattr(scene, "audioDuration_sec", None) or 3.0
                fallback_path = os.path.join(temp_dir, f"scene_{scene.scene_id}_fallback.mp4")
                # Use ColorClip to create a single-frame-safe mp4
                color_clip = ColorClip(size=(width, height), color=(0, 0, 0)).with_duration(dur)
                # write_videofile inside child process — capture any messages to the log file
                color_clip.write_videofile(fallback_path, codec="libx264", fps=24, audio=False, threads=1)
                write_log_line(f"--- Fallback scene created at {fallback_path} ---")
                return {"scene_id": scene.scene_id, "out_path": fallback_path, "log_path": scene_log_path}
            except Exception as fallback_exc:
                write_log_line(f"--- Fallback creation failed: {fallback_exc} ---")
                # re-raise original exception after writing logs
                raise

        # Not a broadcasting ValueError (or fallback failed) => re-raise so parent can handle abort
        raise


# -----------------------------
# UI helpers: Scrollable frame
# -----------------------------
class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        frame = ttk.Frame(canvas)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        self.frame = frame
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))


# -----------------------------
# Main Tk app
# -----------------------------
class UIRendererApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("JSON → VIDEO — Preview & Parallel Render (SCRAM included)")
        self.geometry("1180x800")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Keep references to PhotoImage to avoid GC
        self._thumb_refs = {}

        # Notebook tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.preview_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.preview_tab, text="Preview")

        self.render_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.render_tab, text="Render")

        self._build_preview_tab()
        self._build_render_tab()

        # Periodic tasks
        self.after(200, self._periodic_tasks)

        # Default output name
        self._set_default_output_filename()

    # -----------------------------
    # Build Preview tab
    # -----------------------------
    def _build_preview_tab(self):
        top = ttk.Frame(self.preview_tab, padding=6)
        top.pack(fill="x")
        self.btn_import = ttk.Button(top, text="Import JSON", command=self._on_import_json)
        self.btn_import.pack(side="left")
        self.btn_remove = ttk.Button(top, text="Remove Project", command=self._on_remove_project, state="disabled")
        self.btn_remove.pack(side="left", padx=(6, 0))
        self.btn_download_assets = ttk.Button(top, text="Download All Assets", command=self._on_download_assets, state="disabled")
        self.btn_download_assets.pack(side="left", padx=(6, 0))

        meta = ttk.LabelFrame(self.preview_tab, text="Video Metadata (editable before render)", padding=8)
        meta.pack(fill="x", padx=8, pady=6)

        self.lbl_title = ttk.Label(meta, text="Title: —")
        self.lbl_title.grid(row=0, column=0, sticky="w")

        # Resolution dropdown (includes down to 360p)
        ttk.Label(meta, text="Resolution:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.resolutions = ["3840x2160", "2560x1440", "1920x1080", "1600x900", "1280x720", "854x480", "640x360"]
        self.res_var = tk.StringVar(value=self.resolutions[2])
        self.res_menu = ttk.Combobox(meta, textvariable=self.res_var, values=self.resolutions, state="readonly", width=20)
        self.res_menu.grid(row=1, column=1, sticky="w", padx=(6, 0))

        # FPS
        ttk.Label(meta, text="FPS:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.fps_options = [24, 25, 30, 50, 60]
        self.fps_var = tk.IntVar(value=30)
        self.fps_menu = ttk.Combobox(meta, textvariable=self.fps_var, values=self.fps_options, state="readonly", width=10)
        self.fps_menu.grid(row=2, column=1, sticky="w", padx=(6, 0))

        # Output filename
        ttk.Label(meta, text="Output filename:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.output_var = tk.StringVar()
        self.output_entry = ttk.Entry(meta, textvariable=self.output_var, width=50)
        self.output_entry.grid(row=3, column=1, sticky="w", padx=(6, 0))

        # Worker selection (Auto or specific counts)
        ttk.Label(meta, text="Workers:").grid(row=4, column=0, sticky="w", pady=(6, 0))
        cpu_count = max(1, os.cpu_count() or 1)
        worker_choices = ["Auto (cpu-1)"] + [str(i) for i in range(1, min(16, cpu_count + 1))]
        self.worker_var = tk.StringVar(value=worker_choices[0])
        self.worker_menu = ttk.Combobox(meta, textvariable=self.worker_var, values=worker_choices, state="readonly", width=16)
        self.worker_menu.grid(row=4, column=1, sticky="w", padx=(6, 0))

        # Scenes area
        scenes_frame = ttk.LabelFrame(self.preview_tab, text="Scenes", padding=6)
        scenes_frame.pack(fill="both", expand=True, padx=8, pady=6)
        self.scenes_scroll = ScrollableFrame(scenes_frame)
        self.scenes_scroll.pack(fill="both", expand=True)

        bottom = ttk.Frame(self.preview_tab, padding=6)
        bottom.pack(fill="x")
        self.download_status = ttk.Label(bottom, text="Assets: —")
        self.download_status.pack(side="left")

    # -----------------------------
    # Build Render tab
    # -----------------------------
    def _build_render_tab(self):
        top = ttk.Frame(self.render_tab, padding=6)
        top.pack(fill="x")
        self.btn_start_render = ttk.Button(top, text="Start Rendering", command=self._on_start_render, state="disabled")
        self.btn_start_render.pack(side="left")
        self.btn_stop_render = ttk.Button(top, text="Stop Rendering", command=self._on_stop_render, state="disabled")
        self.btn_stop_render.pack(side="left", padx=(6, 0))
        # SCRAM button (hard kill)
        self.btn_scram = ttk.Button(top, text="SCRAM ⚠️", command=self._on_scram_pressed, state="disabled")
        self.btn_scram.pack(side="left", padx=(6, 0))

        self.lbl_render_status = ttk.Label(top, text="Status: Idle")
        self.lbl_render_status.pack(side="left", padx=(12, 0))

        # Progress and percentage
        progress_frame = ttk.Frame(self.render_tab, padding=6)
        progress_frame.pack(fill="x")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progressbar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100.0)
        self.progressbar.pack(fill="x", expand=True, side="left")
        self.lbl_progress_text = ttk.Label(progress_frame, text="0%")
        self.lbl_progress_text.pack(side="left", padx=(8, 0))

        # Scene & ETA
        info_frame = ttk.Frame(self.render_tab, padding=6)
        info_frame.pack(fill="x")
        self.lbl_scene_progress = ttk.Label(info_frame, text="Scene: 0/0")
        self.lbl_scene_progress.pack(side="left")
        self.lbl_eta = ttk.Label(info_frame, text="ETA: —")
        self.lbl_eta.pack(side="left", padx=(12, 0))

        # Hardware info
        hw_frame = ttk.Frame(self.render_tab, padding=6)
        hw_frame.pack(fill="x")
        self.lbl_cpu = ttk.Label(hw_frame, text="CPU: —")
        self.lbl_cpu.pack(side="left")
        self.lbl_mem = ttk.Label(hw_frame, text="Memory: —")
        self.lbl_mem.pack(side="left", padx=(12, 0))

        # Console log
        log_frame = ttk.LabelFrame(self.render_tab, text="Console Log", padding=4)
        log_frame.pack(fill="both", expand=True, padx=8, pady=6)
        self.txt_log = tk.Text(log_frame, height=22, state="disabled", wrap="none")
        self.txt_log.pack(fill="both", expand=True)
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview)
        log_vsb.pack(side="right", fill="y")
        self.txt_log.configure(yscrollcommand=log_vsb.set)

    # -----------------------------
    # Import / preview handlers
    # -----------------------------
    def _on_import_json(self):
        path = filedialog.askopenfilename(title="Open Project JSON", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            project = load_project_from_json(path) if BACKEND_AVAILABLE else None
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load JSON: {e}")
            return
        app_state["project"] = project
        app_state["json_path"] = path
        app_state["assets_ready"] = False
        self._refresh_preview_ui()
        self.btn_remove.config(state="normal")
        self.btn_download_assets.config(state="normal")
        self.btn_start_render.config(state="normal")
        log(f"Loaded project {os.path.basename(path)}")

    def _on_remove_project(self):
        if not messagebox.askyesno("Remove project", "Remove current project from UI? (This does not delete downloaded assets)"):
            return
        stop_audio_playback()
        app_state["project"] = None
        app_state["json_path"] = None
        app_state["assets_ready"] = False
        app_state["scene_outputs"] = []
        self._clear_preview_ui()
        self.btn_remove.config(state="disabled")
        self.btn_download_assets.config(state="disabled")
        self.btn_start_render.config(state="disabled")
        self.lbl_title.config(text="Title: —")
        self.download_status.config(text="Assets: —")
        self._set_default_output_filename()
        log("Project removed from UI")

    def _on_download_assets(self):
        if not BACKEND_AVAILABLE or not app_state.get("project"):
            messagebox.showwarning("Unavailable", "Backend not available or no project loaded.")
            return
        self.btn_download_assets.config(state="disabled")
        self.download_status.config(text="Assets: downloading...")
        def dl():
            try:
                parallel_download_assets(app_state["project"], os.getenv("GOOGLE_FONTS_API_KEY"))
                app_state["assets_ready"] = True
                ui_put("download_complete", None)
                log("✅ Asset download complete")
            except Exception as e:
                log(f"⚠️ Asset download failed: {e}")
                ui_put("download_failed", str(e))
        threading.Thread(target=dl, daemon=True).start()

    def _clear_preview_ui(self):
        for child in list(self.scenes_scroll.frame.winfo_children()):
            child.destroy()
        self._thumb_refs.clear()

    def _refresh_preview_ui(self):
        self._clear_preview_ui()
        project = app_state.get("project")
        if not project:
            return
        self.lbl_title.config(text=f"Title: {project.metadata.title}")
        # Set resolution/fps from project if available
        try:
            self.res_var.set(project.metadata.resolution)
        except Exception:
            pass
        try:
            self.fps_var.set(project.metadata.fps)
        except Exception:
            pass

        # Build scene cards
        for scene in project.scenes:
            card = ttk.Frame(self.scenes_scroll.frame, padding=6, relief="groove")
            card.pack(fill="x", padx=6, pady=6)
            thumb_label = ttk.Label(card, text="[no image]", width=40)
            thumb_label.pack(side="left", padx=(0, 8))
            thumb_path = None
            for layer in scene.layers:
                if layer.type == "image" and getattr(layer, "url", None):
                    thumb_path = get_local_asset_path(layer.url, "images") if BACKEND_AVAILABLE else None
                    break
            if thumb_path and os.path.exists(thumb_path):
                try:
                    img = Image.open(thumb_path)
                    img.thumbnail((360, 202))
                    photo = ImageTk.PhotoImage(img)
                    thumb_label.configure(image=photo, text="")
                    self._thumb_refs[f"scene_{scene.scene_id}"] = photo
                except Exception as e:
                    log(f"⚠️ Thumbnail load error: {e}")
                    thumb_label.configure(text="[thumbnail error]")
            else:
                thumb_label.configure(text="[image not downloaded]")

            info = ttk.Frame(card)
            info.pack(side="left", fill="both", expand=True)
            ttk.Label(info, text=f"Scene {scene.scene_id} (slide {scene.slide_id})").pack(anchor="w")
            ttk.Label(info, text=f"Audio (declared duration): {scene.audioDuration_sec}s").pack(anchor="w")
            # Expandable details
            det_btn = ttk.Button(info, text="Details ▼")
            det_btn.pack(anchor="w", pady=(6, 0))
            det_panel = ttk.Frame(info)
            det_panel.pack(fill="x", pady=(6, 0))
            det_panel.pack_forget()
            def toggle(panel=det_panel, btn=det_btn):
                if panel.winfo_ismapped():
                    panel.pack_forget(); btn.config(text="Details ▼")
                else:
                    panel.pack(fill="x", pady=(6, 0)); btn.config(text="Details ▲")
            det_btn.config(command=toggle)
            for layer in scene.layers:
                if layer.type == "text":
                    txt = f"Text: {layer.content} (font={layer.font}, size={layer.size}, color={layer.color})"
                    ttk.Label(det_panel, text=txt, wraplength=700, justify="left").pack(anchor="w")
                    if layer.animation:
                        anim = f"Animation: {layer.animation.type} start={layer.animation.startTime_sec} dur={layer.animation.duration_sec}"
                        ttk.Label(det_panel, text=anim).pack(anchor="w")
            # Audio preview
            right = ttk.Frame(card)
            right.pack(side="right", padx=6)
            btn_audio = ttk.Button(right, text="Play ▶", width=12)
            def on_audio(s=scene, btn=btn_audio):
                if not PYGAME_AVAILABLE:
                    messagebox.showwarning("Playback unavailable", "pygame not installed; audio preview disabled.")
                    return
                audio_path = get_local_asset_path(s.audioUrl, "audio") if BACKEND_AVAILABLE and getattr(s, "audioUrl", None) else None
                if not audio_path or not os.path.exists(audio_path):
                    messagebox.showinfo("No audio", "Audio not downloaded. Use 'Download All Assets' first.")
                    return
                if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                    stop_audio_playback()
                    btn.config(text="Play ▶")
                else:
                    play_audio_file(audio_path)
                    btn.config(text="Stop ■")
            btn_audio.config(command=on_audio)
            btn_audio.pack(padx=4, pady=4)

        self._set_default_output_filename()

    # -----------------------------
    # Start / Stop / SCRAM logic
    # -----------------------------
    def _set_default_output_filename(self):
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default = f"final_output_{ts}.mp4"
        self.output_var.set(default)

    def _on_start_render(self):
        if not BACKEND_AVAILABLE or not app_state.get("project"):
            messagebox.showwarning("Unavailable", "Backend not available or no project loaded.")
            return
        if not messagebox.askyesno("Start Rendering", "Start rendering? This will lock UI until finished or stopped (or SCRAM)."):
            return

        # Update project metadata from UI
        project = app_state["project"]
        try:
            project.metadata.resolution = self.res_var.get()
            project.metadata.fps = int(self.fps_var.get())
        except Exception:
            pass

        output_filename = self.output_var.get().strip()
        if not output_filename:
            messagebox.showwarning("Invalid filename", "Please specify an output filename.")
            return
        if not output_filename.lower().endswith(".mp4"):
            output_filename += ".mp4"

        # Lock UI and initialize progress
        self._set_ui_locked(True)
        app_state["render_cancel"] = False
        app_state["scene_outputs"] = []
        app_state["render_progress"] = {"completed": 0, "total": len(project.scenes), "scene_times": [], "start_time": time.perf_counter()}
        self.progress_var.set(0.0)
        self.lbl_progress_text.config(text="0%")
        self.lbl_scene_progress.config(text=f"Scene: 0/{len(project.scenes)}")
        self.lbl_eta.config(text="ETA: —")
        self.lbl_render_status.config(text="Status: Rendering...")

        # Start background thread that drives parallel executor
        t = threading.Thread(target=self._render_worker_parallel, args=(output_filename,), daemon=True)
        app_state["render_thread"] = t
        t.start()

    def _on_stop_render(self):
        """Graceful stop: request cancel and shutdown executor to cancel unstarted futures."""
        if not app_state.get("render_thread") or not app_state["render_thread"].is_alive():
            return
        app_state["render_cancel"] = True
        exec_ref = app_state.get("executor")
        if exec_ref:
            try:
                exec_ref.shutdown(cancel_futures=True)
                log("Requested executor.shutdown(cancel_futures=True) — pending scenes cancelled.")
            except Exception as e:
                log(f"⚠️ Error shutting down executor: {e}")
        self.btn_stop_render.config(state="disabled")
        self.lbl_render_status.config(text="Status: Stop requested...")

    def _on_scram_pressed(self):
        """Hard emergency kill: terminate all child processes (ffmpeg/moviepy) immediately and reset UI."""
        if not messagebox.askyesno("SCRAM", "Emergency SCRAM will forcefully kill all render processes. Proceed?"):
            return
        log("[SCRAM] Emergency shutdown triggered — killing all child processes.")
        self.lbl_render_status.config(text="Status: SCRAM in progress...")
        app_state["render_cancel"] = True

        # Attempt to kill all child processes of current process
        try:
            parent = psutil.Process(os.getpid())
            children = parent.children(recursive=True)
            for c in children:
                try:
                    c.kill()
                    log(f"[SCRAM] Killed PID {c.pid} ({' '.join(c.cmdline()) if c.cmdline() else c.name()})")
                except Exception as e:
                    log(f"[SCRAM] Failed to kill PID {c.pid}: {e}")
        except Exception as e:
            log(f"[SCRAM] Could not enumerate child processes: {e}")

        # Shutdown executor if present
        exec_ref = app_state.get("executor")
        if exec_ref:
            try:
                exec_ref.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            app_state["executor"] = None

        # Clear temp dir if we created one
        temp_dir = app_state.get("temp_dir")
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                log(f"[SCRAM] Removed temp dir: {temp_dir}")
            except Exception as e:
                log(f"[SCRAM] Failed to remove temp dir: {e}")

        # Reset state and UI
        app_state["render_thread"] = None
        app_state["scene_outputs"] = []
        app_state["temp_dir"] = None
        app_state["render_cancel"] = False
        self._set_ui_locked(False)
        self.btn_stop_render.config(state="disabled")
        self.btn_scram.config(state="disabled")
        self.lbl_render_status.config(text="Status: SCRAM triggered — all processes killed.")
        log("[SCRAM] Completed — UI reset to ready state.")

    def _set_ui_locked(self, locked: bool):
        """Enable/disable interactive widgets while rendering."""
        state = "disabled" if locked else "normal"
        # Preview tab
        self.btn_import.config(state=state if not locked else "disabled")
        self.btn_remove.config(state=state if not locked else "disabled")
        self.btn_download_assets.config(state=state if not locked else "disabled")
        self.res_menu.config(state=state)
        self.fps_menu.config(state=state)
        self.output_entry.config(state=state)
        self.worker_menu.config(state=state)
        # Render tab
        self.btn_start_render.config(state="disabled" if locked else ("normal" if app_state.get("project") else "disabled"))
        self.btn_stop_render.config(state=("normal" if locked else "disabled"))
        self.btn_scram.config(state=("normal" if locked else "disabled"))
        if locked:
            try:
                self.notebook.select(self.render_tab)
            except Exception:
                pass

    # -----------------------------
    # Parallel render orchestration
    # -----------------------------
    def _render_worker_parallel(self, output_filename):
        project = app_state.get("project")
        if not project:
            ui_put("render_finished", {"success": False, "error": "No project loaded."})
            return

        cwd = os.getcwd()
        temp_dir = os.path.join(cwd, "temp_parallel_ui")
        result_dir = os.path.join(cwd, "results")
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(result_dir, exist_ok=True)
        app_state["temp_dir"] = temp_dir

        # Compute worker count
        worker_choice = self.worker_var.get()
        cpu_count = max(1, os.cpu_count() or 1)
        if worker_choice.startswith("Auto"):
            max_workers = max(1, cpu_count - 1)
        else:
            try:
                max_workers = int(worker_choice)
            except Exception:
                max_workers = max(1, cpu_count - 1)

        log(f"Starting parallel render: workers={max_workers}, scenes={len(project.scenes)}")
        ui_put("render_started", None)

        futures_map = {}
        scene_logs = {}
        scene_outputs = []

        api_key = os.getenv("GOOGLE_FONTS_API_KEY")
        try:
            width, height = map(int, self.res_var.get().split("x"))
        except Exception:
            width, height = (1920, 1080)

        # Submit all scenes to ProcessPoolExecutor
        executor = ProcessPoolExecutor(max_workers=max_workers)
        app_state["executor"] = executor
        try:
            for scene in project.scenes:
                scene_log_path = os.path.join(temp_dir, f"scene_{scene.scene_id}_log.txt")
                fut = executor.submit(_child_render_wrapper, scene, width, height, api_key, temp_dir, scene_log_path)
                futures_map[fut] = scene
                scene_logs[scene.scene_id] = scene_log_path

            total = len(project.scenes)
            completed = 0
            start_time = time.perf_counter()
            app_state["render_progress"]["start_time"] = start_time

            # Collect completed futures as they finish
            for fut in as_completed(list(futures_map.keys())):
                scene = futures_map.get(fut)
                sid = getattr(scene, "scene_id", None)
                try:
                    result = fut.result()
                except CancelledError:
                    log(f"⏹️ Scene {sid} was cancelled before start.")
                    ui_put("scene_cancelled", {"scene_id": sid})
                    continue
                except Exception as e:
                    # Child raised — stream its log if available and abort
                    log(f"⚠️ Scene {sid} failed in child process: {e}")
                    log_path = scene_logs.get(sid)
                    if log_path and os.path.exists(log_path):
                        self._stream_file_to_log(log_path)
                    # Attempt to cancel remaining futures
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                    ui_put("render_finished", {"success": False, "error": f"Scene {sid} failed: {e}"})
                    return

                # Success: read per-scene log
                out_path = result.get("out_path")
                log_path = result.get("log_path")
                if log_path and os.path.exists(log_path):
                    self._stream_file_to_log(log_path)

                if out_path and os.path.exists(out_path):
                    scene_outputs.append(out_path)
                    log(f"✅ Scene {sid} output: {os.path.basename(out_path)}")
                else:
                    log(f"⚠️ Scene {sid} reported success but output missing at {out_path}")

                # Update progress
                completed += 1
                elapsed = time.perf_counter() - start_time
                app_state["render_progress"]["completed"] = completed
                avg_scene = elapsed / completed if completed else 0.0
                remaining = total - completed
                eta_seconds = int(avg_scene * remaining)
                percent = (completed / total) * 100.0 if total else 100.0
                ui_put("scene_completed", {"completed": completed, "total": total, "percent": percent, "eta": seconds_to_hms(eta_seconds), "scene_id": sid})

                # If user requested cancellation, attempt to shutdown executor to cancel remaining tasks
                if app_state["render_cancel"]:
                    log("Stop requested: attempting to cancel pending scenes...")
                    try:
                        executor.shutdown(cancel_futures=True)
                        log("Pending scenes cancelled.")
                    except Exception as e:
                        log(f"⚠️ Failed to cancel pending futures: {e}")
                    # continue processing already-running futures

        finally:
            # Ensure executor cleaned up
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass
            app_state["executor"] = None

        # Concatenate if we have outputs and not cancelled
        if scene_outputs and (not app_state["render_cancel"]):
            try:
                ui_put("concat_started", None)
                log("Concatenating final video...")
                # sort outputs by scene number in filename
                def scene_key(p):
                    import re
                    m = re.search(r"scene_(\d+)", os.path.basename(p))
                    return int(m.group(1)) if m else p
                scene_outputs_sorted = sorted(scene_outputs, key=scene_key)
                clips = [VideoFileClip(p) for p in scene_outputs_sorted]
                final_clip = concatenate_videoclips(clips, method="compose")
                final_out_path = os.path.join(result_dir, output_filename)
                final_clip.write_videofile(final_out_path, codec="libx264", fps=project.metadata.fps, audio_codec="aac", threads="auto")
                log(f"🎬 Final video saved to: {final_out_path}")
                ui_put("render_finished", {"success": True, "path": final_out_path})
            except Exception as e:
                tb = traceback.format_exc()
                log(f"⚠️ Concatenation failed: {e}\n{tb}")
                ui_put("render_finished", {"success": False, "error": str(e)})
        else:
            if app_state["render_cancel"]:
                log("Render cancelled by user (graceful).")
                ui_put("render_finished", {"success": False, "cancelled": True})
            else:
                log("Render finished but no final video produced.")
                ui_put("render_finished", {"success": False, "error": "No scene outputs."})

        # Cleanup temp
        try:
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                log(f"Removed temp dir: {temp_dir}")
        except Exception:
            pass

    # -----------------------------
    # Stream per-scene log file into UI log
    # -----------------------------
    def _stream_file_to_log(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                LOG_QUEUE.put(f"[child log start] {os.path.basename(path)}")
                for line in f:
                    line = line.rstrip("\n")
                    if line:
                        LOG_QUEUE.put(f"[child] {line}")
                LOG_QUEUE.put(f"[child log end] {os.path.basename(path)}")
        except Exception as e:
            log(f"⚠️ Could not read scene log {path}: {e}")

    # -----------------------------
    # Periodic tasks: drain queues and update HW info
    # -----------------------------
    def _periodic_tasks(self):
        # Drain LOG_QUEUE
        while not LOG_QUEUE.empty():
            try:
                line = LOG_QUEUE.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)

        # Drain UI_QUEUE
        while not UI_QUEUE.empty():
            try:
                evt, payload = UI_QUEUE.get_nowait()
            except queue.Empty:
                break
            self._handle_ui_event(evt, payload)

        # Update hardware info
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            self.lbl_cpu.config(text=f"CPU: {cpu}%")
            self.lbl_mem.config(text=f"Memory: {mem.percent}% ({int(mem.used/1024**2)}MB/{int(mem.total/1024**2)}MB)")
        except Exception:
            pass

        # schedule next poll
        self.after(200, self._periodic_tasks)

    def _append_log(self, text: str):
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", text + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    # -----------------------------
    # UI event handling
    # -----------------------------
    def _handle_ui_event(self, evt, payload):
        if evt == "download_complete":
            self.download_status.config(text="Assets: downloaded")
            self.btn_download_assets.config(state="normal")
            self._refresh_preview_ui()
        elif evt == "download_failed":
            self.download_status.config(text="Assets: failed")
            self.btn_download_assets.config(state="normal")
            messagebox.showwarning("Download failed", f"{payload}")
        elif evt == "scene_completed":
            completed = payload.get("completed")
            total = payload.get("total")
            percent = payload.get("percent", 0.0)
            eta = payload.get("eta", "—")
            scene_id = payload.get("scene_id")
            self.progress_var.set(percent)
            self.lbl_progress_text.config(text=f"{int(percent)}%")
            self.lbl_scene_progress.config(text=f"Scene: {completed}/{total}")
            self.lbl_eta.config(text=f"ETA: {eta}")
            self.lbl_render_status.config(text=f"Status: Completed scene {scene_id} ({completed}/{total})")
        elif evt == "render_finished":
            success = payload.get("success", False)
            cancelled = payload.get("cancelled", False)
            error = payload.get("error")
            path = payload.get("path")
            if success:
                self.lbl_render_status.config(text=f"Status: Completed — {os.path.basename(path)}")
                messagebox.showinfo("Render complete", f"Final video saved to:\n{path}")
            elif cancelled:
                self.lbl_render_status.config(text="Status: Cancelled")
                messagebox.showinfo("Render cancelled", "Render was cancelled gracefully.")
            else:
                self.lbl_render_status.config(text="Status: Failed")
                messagebox.showerror("Render failed", f"Error: {error}")
            # Unlock UI
            self._set_ui_locked(False)
            self.btn_stop_render.config(state="disabled")
            self.btn_scram.config(state="disabled")
            app_state["render_thread"] = None
            app_state["render_cancel"] = False
        elif evt == "render_started":
            self.lbl_render_status.config(text="Status: Rendering...")
        elif evt == "concat_started":
            self.lbl_render_status.config(text="Status: Concatenating...")

    # -----------------------------
    # Close handler
    # -----------------------------
    def on_close(self):
        if app_state.get("render_thread") and app_state["render_thread"].is_alive():
            if not messagebox.askyesno("Quit", "A render is in progress. Quit and SCRAM (kill) render?"):
                return
            # Perform SCRAM-like shutdown
            app_state["render_cancel"] = True
            exec_ref = app_state.get("executor")
            if exec_ref:
                try:
                    exec_ref.shutdown(cancel_futures=True)
                except Exception:
                    pass
            # kill children
            try:
                parent = psutil.Process(os.getpid())
                for c in parent.children(recursive=True):
                    try:
                        c.kill()
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(0.5)
        stop_audio_playback()
        self.destroy()


# -----------------------------
# Utilities
# -----------------------------
def seconds_to_hms(seconds: int) -> str:
    if seconds < 0:
        return "00:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# -----------------------------
# Entry point
# -----------------------------
def main():
    if PYGAME_AVAILABLE:
        try:
            pygame.mixer.init()
        except Exception:
            pass
    app = UIRendererApp()
    app.mainloop()


if __name__ == "__main__":
    main()
