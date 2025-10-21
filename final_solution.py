# Parallel MoviePy renderer with local asset caching and cleanup.
import os
import sys
import json
import re
import shutil
import tempfile
import argparse
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

# For logging
import psutil
import time
import platform
import subprocess
from datetime import datetime

# MoviePy 2.0 imports
from moviepy import (
    ImageClip,
    AudioFileClip,
    ColorClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    VideoFileClip,
)
from moviepy.video.fx.FadeIn import FadeIn
from moviepy.video.fx.FadeOut import FadeOut

import gdown
import requests
from dotenv import load_dotenv

# ===============================
# Data model
# ===============================
@dataclass
class Animation:
    type: str
    startTime_sec: Optional[float] = None
    duration_sec: Optional[float] = None
    start_zoom: Optional[float] = None
    end_zoom: Optional[float] = None
    direction: Optional[str] = None

@dataclass
class Position:
    x: int
    y: int
    anchor: str

@dataclass
class Layer:
    layer_id: str
    type: str
    content: Optional[str] = None
    url: Optional[str] = None
    font: Optional[str] = None
    size: Optional[int] = None
    color: Optional[str] = None
    position: Optional[Position] = None
    animation: Optional[Animation] = None

@dataclass
class Scene:
    scene_id: int
    slide_id: int
    audioUrl: Optional[str]
    audioDuration_sec: float
    layers: List[Layer] = field(default_factory=list)

@dataclass
class VideoMetadata:
    title: str
    resolution: str
    fps: int

@dataclass
class VideoProject:
    metadata: VideoMetadata
    scenes: List[Scene]

# ===============================
# Asset handling & index
# ===============================
ASSET_ROOT = os.path.join(os.getcwd(), "assets")
ASSET_DIRS = {
    "audio": os.path.join(ASSET_ROOT, "audio"),
    "images": os.path.join(ASSET_ROOT, "images"),
    "fonts": os.path.join(ASSET_ROOT, "fonts"),
}
DOWNLOAD_INDEX_PATH = os.path.join(ASSET_ROOT, "download_index.json")
_INDEX_LOCK = threading.Lock()  # used only in the main process / threads

def ensure_asset_dirs():
    for p in ASSET_DIRS.values():
        os.makedirs(p, exist_ok=True)
    # ensure index file exists (but don't clobber it if present)
    if not os.path.exists(DOWNLOAD_INDEX_PATH):
        try:
            os.makedirs(os.path.dirname(DOWNLOAD_INDEX_PATH), exist_ok=True)
            with open(DOWNLOAD_INDEX_PATH, "w") as f:
                json.dump({}, f)
        except Exception:
            pass

def _load_download_index():
    try:
        if os.path.exists(DOWNLOAD_INDEX_PATH):
            with open(DOWNLOAD_INDEX_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_download_index(index: dict):
    # atomic write
    tmp = DOWNLOAD_INDEX_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(index, f)
    os.replace(tmp, DOWNLOAD_INDEX_PATH)

def extract_file_id(drive_url: str) -> Optional[str]:
    if not drive_url:
        return None
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", drive_url)
    return match.group(1) if match else None

def download_asset(url: str, kind: str) -> Optional[str]:
    """
    Downloads a Google Drive asset letting gdown pick the filename/extension,
    then moves it into ./assets/{kind}/ and records the mapping (file_id -> path).
    Thread-safe for main-thread downloads (uses _INDEX_LOCK).
    """
    ensure_asset_dirs()
    file_id = extract_file_id(url)
    if not file_id:
        print(f"⚠️ download_asset: invalid drive url: {url}")
        return None

    # quick check: index -> existing file
    with _INDEX_LOCK:
        idx = _load_download_index()
        mapped = idx.get(file_id)
        if mapped and os.path.exists(mapped):
            return mapped

    # Let gdown decide filename by not passing an explicit output filename.
    uc_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        downloaded_path = gdown.download(uc_url, output=None, quiet=False)
    except Exception as e:
        print(f"⚠️ gdown failed for {url}: {e}")
        downloaded_path = None

    if not downloaded_path or not os.path.exists(downloaded_path):
        print(f"⚠️ download_asset: gdown didn't return a valid file for {url}")
        return None

    filename = os.path.basename(downloaded_path)
    dest_dir = ASSET_DIRS.get(kind, ASSET_ROOT)
    dest_path = os.path.join(dest_dir, filename)

    # If dest exists, make a unique name (preserve extension)
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(dest_path):
        dest_filename = f"{base}_{counter}{ext}"
        dest_path = os.path.join(dest_dir, dest_filename)
        counter += 1

    try:
        # If gdown already saved into the assets folder (unlikely since output=None),
        # move may be a no-op; shutil.move handles same-source -> dest behavior.
        shutil.move(downloaded_path, dest_path)
    except Exception as e:
        # fallback: try copying then removing
        try:
            shutil.copy2(downloaded_path, dest_path)
            os.remove(downloaded_path)
        except Exception as ee:
            print(f"⚠️ Could not move/copy downloaded file: {downloaded_path} -> {dest_path}: {ee}")
            return None

    # update index
    with _INDEX_LOCK:
        idx = _load_download_index()
        idx[file_id] = dest_path
        try:
            _save_download_index(idx)
        except Exception as e:
            print(f"⚠️ Failed to update download index: {e}")

    print(f"📥 Downloaded {kind}: {dest_path}")
    return dest_path

def get_local_asset_path(url: str, kind: str) -> Optional[str]:
    """
    Look up the already-downloaded path for a drive URL (by file_id).
    Returns None if not found.
    """
    file_id = extract_file_id(url)
    if not file_id:
        return None
    idx = _load_download_index()
    path = idx.get(file_id)
    if path and os.path.exists(path):
        return path
    # last-chance: search folder for files that include the file_id in the name
    folder = ASSET_DIRS.get(kind, ASSET_ROOT)
    if os.path.isdir(folder):
        for fn in os.listdir(folder):
            if file_id in fn:
                candidate = os.path.join(folder, fn)
                if os.path.exists(candidate):
                    return candidate
    return None

# Fonts
def fetch_fallback_font(api_key: str) -> str:
    ensure_asset_dirs()
    fallback_path = os.path.join(ASSET_DIRS["fonts"], "Open_Sans.ttf")
    # if not os.path.exists(fallback_path):
    #     print("Downloading fallback font Open_Sans...")
    #     r = requests.get(url)
    #     if r.status_code == 200:
    #         with open(fallback_path, "wb") as f:
    #             f.write(r.content)
    return fallback_path

def fetch_google_font_via_api(font_name: str, api_key: str) -> str:
    ensure_asset_dirs()
    api_url = f"https://www.googleapis.com/webfonts/v1/webfonts?key={api_key}"
    try:
        r = requests.get(api_url)
        if r.status_code != 200:
            return fetch_fallback_font(api_key)
        data = r.json()
        family_entry = next((f for f in data.get("items", []) if f["family"].lower() == font_name.lower()), None)
        if not family_entry:
            return fetch_fallback_font(api_key)
        font_url = family_entry["files"].get("regular")
        if not font_url:
            return fetch_fallback_font(api_key)
        font_path = os.path.join(ASSET_DIRS["fonts"], f"{font_name.replace(' ', '_')}.ttf")
        if not os.path.exists(font_path):
            resp = requests.get(font_url)
            if resp.status_code == 200:
                with open(font_path, "wb") as f:
                    f.write(resp.content)
                print(f"📥 Downloaded font: {font_path}")
        return font_path
    except Exception as e:
        print(f"⚠️ Error fetching font {font_name}: {e}")
        return fetch_fallback_font(api_key)

def get_font_path(font_name: Optional[str], api_key: str) -> str:
    return fetch_google_font_via_api(font_name, api_key) if font_name else fetch_fallback_font(api_key)

# ===============================
# Animation helpers
# ===============================
def apply_animation_to_clip(clip, layer: Layer, safe_duration: float, canvas_size: Tuple[int, int]):
    if not layer.animation:
        return clip.with_duration(safe_duration)
    anim = layer.animation
    start = anim.startTime_sec or 0.0
    effect_duration = float(anim.duration_sec) if anim.duration_sec else 0.0
    clip = clip.with_start(start).with_duration(safe_duration - start)
    anim_type = (anim.type or "").lower()
    if anim_type == "fadein":
        clip = clip.with_effects([FadeIn(duration=effect_duration)])
    elif anim_type == "fadeout":
        clip = clip.with_effects([FadeOut(duration=effect_duration)])
    elif anim_type == "slideinfromleft":
        canvas_w, canvas_h = canvas_size

        # --- FIX: Handle case where clip.w might be None (e.g., failed TextClip) ---
        clip_w = clip.w if clip.w is not None else 0
        clip_h = clip.h if clip.h is not None else 0

        # Use the fixed clip_w and clip_h here
        final_x = layer.position.x if layer.position else (canvas_w - clip_w) / 2
        final_y = layer.position.y if layer.position else (canvas_h - clip_h) / 2
        start_x = -clip_w
        def pos_fn(t):
            progress = min(max(t / effect_duration, 0.0), 1.0) if effect_duration > 0 else 1.0
            x = start_x + progress * (final_x - start_x)
            return (x, final_y)
        clip = clip.with_position(pos_fn)
    return clip

def apply_kenburns_to_image(clip, anim: Animation, safe_duration: float):
    start_zoom = anim.start_zoom or 1.0
    end_zoom = anim.end_zoom or 1.1
    def scale_fn(t):
        progress = min(max(t / safe_duration, 0.0), 1.0)
        return start_zoom + (end_zoom - start_zoom) * progress
    return clip.resized(scale_fn)

# ===============================
# JSON loader
# ===============================
def load_project_from_json(json_path: str) -> VideoProject:
    with open(json_path, "r") as f:
        data = json.load(f)
    metadata = VideoMetadata(**data["videoMetadata"])
    scenes = []
    for s in data["scenes"]:
        layers = []
        for l in s["layers"]:
            position = Position(**l["position"]) if "position" in l else None
            animation = Animation(**l["animation"]) if "animation" in l else None
            # create Layer with proper nested objects
            layer_dict = {**l}
            layer_dict["position"] = position
            layer_dict["animation"] = animation
            layers.append(Layer(**layer_dict))
        scenes.append(Scene(**{**s, "layers": layers}))
    return VideoProject(metadata=metadata, scenes=scenes)

# ===============================
# Parallel asset download (main-thread)
# ===============================
def parallel_download_assets(project: VideoProject, api_key: str):
    ensure_asset_dirs()
    tasks = []
    results = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for scene in project.scenes:
            if scene.audioUrl:
                tasks.append(executor.submit(download_asset, scene.audioUrl, "audio"))
            for layer in scene.layers:
                if layer.type == "image" and layer.url:
                    tasks.append(executor.submit(download_asset, layer.url, "images"))
                elif layer.type == "text" and layer.font:
                    # fonts are downloaded differently
                    tasks.append(executor.submit(fetch_google_font_via_api, layer.font, api_key))
        for f in as_completed(tasks):
            try:
                path = f.result()
                if path:
                    results[path] = True
            except Exception as e:
                print(f"⚠️ Asset download failed: {e}")
    print(f"✅ {len(results)} assets ready in {ASSET_ROOT}")
    return results

# ===============================
# Scene rendering (worker processes)
# ===============================
def render_scene(scene: Scene, width: int, height: int, api_key: str, temp_dir: str):
    import os
    from moviepy import CompositeVideoClip, ImageClip, AudioFileClip, TextClip, ColorClip

    # ---- Determine audio and safe duration ----
    scene_duration = scene.audioDuration_sec
    audio_clip = None

    if scene.audioUrl:
        audio_path = get_local_asset_path(scene.audioUrl, "audio") or download_asset(scene.audioUrl, "audio")
        if audio_path:
            try:
                audio_clip = AudioFileClip(audio_path)
                scene_duration = min(scene_duration, audio_clip.duration)
            except Exception as e:
                print(f"[Warning] Could not load audio for scene {scene.scene_id}: {e}")

    EPSILON = 0.02
    safe_duration = max(0, scene_duration - EPSILON)
    layer_clips = []

    # ---- Build visual layers ----
    for layer in scene.layers:
        try:
            clip_to_add = None 
            
            # 1️⃣ IMAGE LAYERS
            if layer.type == "image" and layer.url:
                img_path = get_local_asset_path(layer.url, "images") or download_asset(layer.url, "images")
                if img_path:
                    img_clip = ImageClip(img_path).resized((width, height))
                    if layer.animation and (layer.animation.type or "").lower() == "kenburns":
                        img_clip = apply_kenburns_to_image(img_clip, layer.animation, safe_duration)
                    clip_to_add = img_clip

            # 2️⃣ SOLID COLOR BACKGROUND
            elif layer.type == "color" and layer.color:
                rgb = tuple(int(layer.color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
                clip_to_add = ColorClip(size=(width, height), color=rgb)

            # 3️⃣ TEXT LAYERS
            elif layer.type == "text" and (layer.content or "").strip():
                font_path = get_font_path(layer.font, api_key)
                try:
                    # --- Step 1: Create the TextClip ---
                    text_color = layer.color or "white"
                    txt_clip = TextClip(
                        text=layer.content,
                        font=font_path,
                        font_size=layer.size or 40,
                        color=text_color,
                        # --- ADDED: Fixes Clipping Issue ---
                        stroke_color=text_color,
                        # stroke_width=1, # Set a small stroke width (1-2 is usually enough)
                        # -----------------------------------
                        size=(width, None), # Allow horizontal wrapping
                        method="caption",
                    )
                    
                    # --- Step 2: Calculate Position Manually ---
                    if layer.position:
                        # Get the actual rendered size of the text clip
                        clip_w, clip_h = txt_clip.size
                        
                        # Start with the user's desired coordinates
                        pos_x, pos_y = layer.position.x, layer.position.y
                        anchor = (layer.position.anchor or "top_left").lower()

                        # Adjust coordinates based on the anchor
                        # Horizontal adjustment
                        if "center" in anchor:
                            pos_x -= clip_w / 2
                        elif "right" in anchor:
                            pos_x -= clip_w
                        
                        # Vertical adjustment
                        if "center" in anchor and "top" not in anchor and "bottom" not in anchor: # Middle-center
                             pos_y -= clip_h / 2
                        elif "bottom" in anchor:
                            pos_y -= clip_h

                        # --- Step 3: Apply the final calculated position ---
                        txt_clip = txt_clip.with_position((pos_x, pos_y))

                    clip_to_add = txt_clip

                except Exception as e:
                    print(f"[Warning] TextClip creation failed for '{layer.content[:30]}': {e}")
                    continue

            # Apply animations and add the final clip to the list
            if clip_to_add:
                final_layer_clip = apply_animation_to_clip(clip_to_add, layer, safe_duration, (width, height))
                layer_clips.append(final_layer_clip)

        except Exception as e:
            print(f"[Warning] Skipped layer due to error in scene {scene.scene_id}: {e}")

    # ---- Final Composition & Export ----
    if not layer_clips:
        print(f"[Warning] Scene {scene.scene_id} has no valid visual layers. Using blank background.")
        layer_clips = [ColorClip(size=(width, height), color=(0, 0, 0)).with_duration(safe_duration)]
    
    scene_clip = CompositeVideoClip(layer_clips, size=(width, height)).with_duration(safe_duration)

    if audio_clip:
        scene_clip = scene_clip.with_audio(audio_clip.subclipped(0, safe_duration))

    scene_out = os.path.join(temp_dir, f"scene_{scene.scene_id}.mp4")
    try:
        scene_clip.write_videofile(scene_out, fps=30, codec="libx264", audio_codec="aac")
    except Exception as e:
        print(f"[Error] Failed to render scene {scene.scene_id}: {e}")
        raise
    finally:
        scene_clip.close()
        if audio_clip:
            audio_clip.close()

    return scene_out

# ===============================
# Build video (parallel)
# ===============================
def build_video_from_project_parallel(project: VideoProject, api_key: str):
    width, height = map(int, project.metadata.resolution.split("x"))

    # Workspace folders
    temp_dir = os.path.join(os.getcwd(), "temp")
    result_dir = os.path.join(os.getcwd(), "results")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)

    # Timestamp for file naming
    start_time = datetime.now()
    timestamp_str = start_time.strftime("%Y-%m-%d_%H-%M-%S")

    # Log data initialization
    log_data = {
        "start_time": start_time.isoformat(),
        "system": platform.platform(),
        "cpu_count": os.cpu_count(),
        "status": "started",
        "errors": [],
        "warnings": [],
        "scenes": {},
    }

    print("🧩 Downloading all assets to ./assets/ ...")
    assets = parallel_download_assets(project, api_key)
    log_data["asset_count"] = len(assets)

    # Start timing
    start_perf = time.perf_counter()

    print(f"🎨 Rendering scenes in parallel (temp files in {temp_dir})...")
    scene_outputs = []
    scene_times = []

    with ProcessPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
        futures = {executor.submit(render_scene, s, width, height, api_key, temp_dir): s for s in project.scenes}
        for f in as_completed(futures):
            scene = futures[f]
            scene_id = scene.scene_id
            scene_start = time.perf_counter()
            try:
                out_path = f.result()
                elapsed_scene = time.perf_counter() - scene_start
                scene_times.append(elapsed_scene)
                scene_outputs.append(out_path)
                log_data["scenes"][f"scene_{scene_id}"] = {
                    "slide_id": scene.slide_id,
                    "duration_sec": scene.audioDuration_sec,
                    "elapsed_sec": round(elapsed_scene, 2),
                    "status": "completed"
                }
                print(f"✅ Finished scene {scene_id}: {os.path.basename(out_path)} ({elapsed_scene:.2f}s)")
            except Exception as e:
                log_data["scenes"][f"scene_{scene_id}"] = {
                    "slide_id": scene.slide_id,
                    "duration_sec": scene.audioDuration_sec,
                    "elapsed_sec": None,
                    "status": "failed",
                    "error": str(e)
                }
                log_data["errors"].append(f"Scene {scene_id}: {e}")
                print(f"⚠️ Scene {scene_id} failed: {e}")

    # In build_video_from_project_parallel function
    print("🎞️ Concatenating scenes...")
    final_clips = [] # Initialize empty list
    try:
        final_clips = [VideoFileClip(p) for p in sorted(scene_outputs)]
        final = concatenate_videoclips(final_clips, method="compose")

        temp_final_path = os.path.join(temp_dir, "final_temp.mp4")
        final.write_videofile(
            temp_final_path,
            codec="libx264",
            fps=project.metadata.fps,
            audio_codec="aac" # Removed threads="auto"
        )
        final.close() # Close the concatenated clip
    finally:
        # Ensure all intermediate clips are closed
        for clip in final_clips:
            clip.close()

    # Move final output into results/
    output_path = os.path.join(result_dir, f"final_output_{timestamp_str}.mp4")
    shutil.move(temp_final_path, output_path)

    # Cleanup temp + partial asset folders
    print("🧹 Cleaning up temporary folders (keeping fonts)...")
    for subfolder in ("audio", "images"):
        folder_path = ASSET_DIRS.get(subfolder)
        if folder_path and os.path.isdir(folder_path):
            try:
                shutil.rmtree(folder_path, ignore_errors=True)
                print(f"   Removed {folder_path}")
            except Exception as e:
                log_data["warnings"].append(f"Could not remove {folder_path}: {e}")

    if os.path.isdir(temp_dir):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"   Removed {temp_dir}")
        except Exception as e:
            log_data["warnings"].append(f"Could not remove {temp_dir}: {e}")

    # Collect system/hardware info
    end_time = datetime.now()
    end_perf = time.perf_counter()
    elapsed_total = end_perf - start_perf

    cpu_percent = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    gpu_info = None
    try:
        gpu_info = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
    except Exception:
        gpu_info = "No GPU info (nvidia-smi not found)"

    avg_scene_time = sum(scene_times) / len(scene_times) if scene_times else 0

    # Finalize log
    log_data.update({
        "end_time": end_time.isoformat(),
        "elapsed_seconds": round(elapsed_total, 2),
        "avg_scene_seconds": round(avg_scene_time, 2),
        "video_metadata": {
            "title": project.metadata.title,
            "resolution": project.metadata.resolution,
            "fps": project.metadata.fps,
            "scene_count": len(project.scenes)
        },
        "hardware": {
            "cpu_percent": cpu_percent,
            "memory_used_mb": round(mem.used / 1_048_576, 2),
            "memory_total_mb": round(mem.total / 1_048_576, 2),
            "gpu_info": gpu_info
        },
        "status": "completed",
        "final_video_path": output_path
    })

    # Save log file with timestamp
    log_path = os.path.join(result_dir, f"render_log_{timestamp_str}.json")
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=4)

    print("✅ Kept ./assets/fonts and ./assets/download_index.json for reuse.")
    print(f"🎬 Final video saved to: {output_path}")
    print(f"📝 Render log saved to: {log_path}")
    return output_path

# ===============================
# Main
# ===============================
def main():
    parser = argparse.ArgumentParser(description="Render video from JSON (parallel by default).")
    parser.add_argument("json_path", nargs="?", default="sorten_to_test_output10.json")
    parser.add_argument("--no-parallel", action="store_true", help="Disable parallel mode.")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("GOOGLE_FONTS_API_KEY")
    if not api_key:
        raise ValueError("Missing GOOGLE_FONTS_API_KEY in .env")

    project = load_project_from_json(args.json_path)
    print("⚙️ Running in parallel mode..." if not args.no_parallel else "⚙️ Running single-threaded.")
    # currently parallel mode is default; single-thread fallback could be implemented separately
    output = build_video_from_project_parallel(project, api_key)
    print(f"🎬 Done! Saved to {output}")

if __name__ == "__main__":
    main()
