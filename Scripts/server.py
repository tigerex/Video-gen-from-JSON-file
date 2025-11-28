import os
import csv
import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict

from fastapi import FastAPI, UploadFile, Form
from pydantic import BaseModel

import upload_to_drive

# ---------------------------
# Directories
# ---------------------------
INPUT_DIR = "../Input"
OUTPUT_DIR = "../utput"
LOG_DIR = "../serverLogs"
RENDER_LOG = os.path.join(LOG_DIR, "renderHistory.log")

# make sure folders existed
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ---------------------------
# Global State
# ---------------------------
JOB_QUEUE: List[Dict] = []
STATE = {
    "status": "idle",        # idle | working
    "current_job": None,
    "process": None          # internal handle
}
QUEUE_PROCESSOR_TASK: Optional[asyncio.Task] = None

# ---------------------------
# FastAPI App
# ---------------------------
app = FastAPI(title="Render Server", version="3.3")

# ---------------------------
# Utility - for debugging
# ---------------------------
def append_render_history(record: Dict):
    timestamp = datetime.utcnow().isoformat() + "Z"
    record["logged_at"] = timestamp
    with open(RENDER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

# ---------------------------
# Render Worker
# ---------------------------
async def run_render(job: Dict):
    start_time = datetime.utcnow() # Start time at UTC(0) which is slower then Vietnamese time zone 7 hours
    input_path = job["path"]
    filename = job["filename"]

    json_path = input_path
    if json_path.lower().endswith(".json") and os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            metadata_title = data.get("videoMetadata", {}).get("title", "").strip()
        except:
            metadata_title = ""
    else:
        metadata_title = ""

    # Sanitize title for folder naming - make sure name only contain a-z, 0-9, no space no special characters
    if metadata_title:
        # lower case
        sanitized = metadata_title.lower()

        # replace spaces with hyphen
        sanitized = sanitized.replace(" ", "-")

        # keep only a-z, 0-9, and hyphens
        safe_title = "".join(c for c in sanitized if c.isalnum() or c == "-")

        # avoid empty string
        if not safe_title:
            safe_title = "output"
    else:
        safe_title = "output"

    print(f"\n========== Starting job: {filename} (ID: {job['id']}) ==========\n") # Debug purpose

    job["status"] = "working"
    STATE["current_job"] = job

    log_file = os.path.join(LOG_DIR, f"{filename}.render.log")

    # Actual call to render script
    try:
        log_handle = open(log_file, "wb")

        proc = await asyncio.create_subprocess_exec(
            "python3", "final_solution_ver3.py", input_path,
            stdout=log_handle,
            stderr=log_handle
        )

        # Monitor process with .log files 
        STATE["process"] = proc
        await proc.wait()
        log_handle.close()
        STATE["process"] = None

        outputs = sorted(
            [os.path.join(OUTPUT_DIR, f) for f in os.listdir(OUTPUT_DIR)
             if os.path.isdir(os.path.join(OUTPUT_DIR, f))],
            key=os.path.getmtime,
        )
        latest_output = outputs[-1] if outputs else None

        # Using new name to upload to drive
        if latest_output:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
            new_name = f"{safe_title}_{timestamp}"
            new_output_path = os.path.join(OUTPUT_DIR, new_name)
            try:
                os.rename(latest_output, new_output_path)
                latest_output = new_output_path   # update pointer for uploading
                print(f"Renamed output to: {new_name}")
            except Exception as e:
                print(f"Folder rename failed: {e}")

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        success = latest_output is not None
        status_txt = "SUCCESS" if success else "FAIL"

        print(f"\n=== Render finished for {filename} → {status_txt}\n")

        append_render_history({
            "job_id": job["id"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "input_file": input_path,
            "output_folder": latest_output,
            "status": status_txt.lower(),
            "error": None if success else "No output folder created"
        })

        # Remove .log file only if process succeeded - save storage usage
        if success and os.path.exists(log_file):
            try:
                os.remove(log_file)
                print(f"Deleted log file: {log_file}")
            except Exception as e:
                print(f"Failed to delete log file: {e}")

        # Uploading to Drive here using module upload_to_drive.py
        if success and job.get("drive_folder"):
            print(f"Uploading output for {filename}...")
            try:
                upload_to_drive.upload_file(
                    latest_output,
                    folder_input=job.get("drive_folder")
                )
                print(f"Upload complete. Deleting folder: {latest_output}")

                # Delete local output folder after successful upload
                import shutil
                shutil.rmtree(latest_output, ignore_errors=True)

            except Exception as e:
                print(f"Upload failed: {e}")

    except Exception as e:
        print(f"\n=== Render crashed for {filename} → ERROR\n{e}\n")
        STATE["process"] = None
        append_render_history({
            "job_id": job["id"],
            "start_time": start_time.isoformat(),
            "end_time": datetime.utcnow().isoformat(),
            "duration_seconds": 0,
            "input_file": input_path,
            "output_folder": None,
            "status": "error",
            "error": str(e)
        })

    # Delete input JSON file after rendering is finished - save storage useage
    try:
        if os.path.exists(input_path):
            os.remove(input_path)
            print(f"Deleted input file: {input_path}")
    except Exception as e:
        print(f"Failed to delete input JSON: {e}")

    STATE["current_job"] = None
    job["status"] = "done"

# ---------------------------
# Queue Processor - Helper that check and work the queue
# ---------------------------
async def process_queue():
    STATE["status"] = "working"
    while JOB_QUEUE:
        job = JOB_QUEUE.pop(0)
        # print(f"\n--- Starting next job in queue: {job['filename']} (ID: {job['id']}) ---\n") # debug purpose
        await run_render(job)
        await asyncio.sleep(1)
    STATE["status"] = "idle"
    print("\n========== Queue empty — State set to IDLE ==========\n")

# ---------------------------
# General Endpoints
# ---------------------------
# For testing connection
@app.get("/hello")
def hello():
    return {"message": "Server online - by Minhhu"}

# Current server status
@app.get("/status")
def status():
    job = STATE["current_job"]
    return {
        "status": STATE["status"],
        "current_job": {
            "id": job["id"],
            "filename": job["filename"],
            "status": job["status"]
        } if job else None,
        "queue_length": len(JOB_QUEUE)
    }

# Show the queue
@app.get("/queue")
def queue_view():
    if not JOB_QUEUE:
        return {"message": "Queue is empty!!!"}
    return [
        {
            "id": job["id"],
            "filename": job["filename"],
            "status": job["status"],
            "drive_folder": job.get("drive_folder"),
            "position": idx + 1
        }
        for idx, job in enumerate(JOB_QUEUE)
    ]

# ---------------------------
# TERMINATE ENDPOINT - Unfinished, untested, use as your own cost.
# ---------------------------
# The point of this endpoint is to terminate the on going job not removing from queue - use /remove for that
@app.post("/terminate")
async def terminate():
    proc = STATE.get("process")
    job = STATE.get("current_job")

    if proc is None:
        return {"message": "No active job to terminate"}

    print("\n!!!!!!!!!!! TERMINATE REQUEST RECEIVED !!!!!!!!!!!\n")

    # Corrupts files so there is a time gap before running next jobs
    try:
        proc.terminate() 
        await asyncio.sleep(0.5)
        if proc.returncode is None:
            proc.kill()
        STATE["process"] = None
        if job:
            job["status"] = "terminated"
        print("\n!!!!! Current job terminated successfully !!!!!\n")
    except Exception as e:
        print(f"Terminate error: {e}")

    STATE["current_job"] = None
    STATE["status"] = "idle"

    # Check queue and start next job
    global QUEUE_PROCESSOR_TASK
    if JOB_QUEUE:
        print("~~~ Restarting queue after termination")
        await asyncio.sleep(2)
        QUEUE_PROCESSOR_TASK = asyncio.create_task(process_queue())

    return {"message": "Job terminated and server reset"}

# ---------------------------
# RENDER ENDPOINT
# ---------------------------
@app.post("/render")
async def render_endpoint(
    file: UploadFile, # The JSON file from Mr.Duc Agents
    drive_folder: Optional[str] = Form(None) # The full url to a folder that the Google Service Account has the permission
):
    # Unoptimized - the JSON file should be remove after rendering - NOT DONE
    save_path = os.path.join(INPUT_DIR, file.filename)
    with open(save_path, "wb") as f:
        f.write(await file.read())

    job_id = str(uuid.uuid4())  # add a unique ID to job - used by /move /remove and future endpoints

    print(f"\n--- Received file: {file.filename} (ID: {job_id})")
    print(f"--- Drive folder: {drive_folder}\n")

    # Job class or object or whatever I don't remember
    job = {
        "id": job_id,
        "filename": file.filename,
        "path": save_path,
        "status": "queued",
        "drive_folder": drive_folder
    }

    JOB_QUEUE.append(job) # Add job to queue

    # Start job and return return answers here
    global QUEUE_PROCESSOR_TASK
    if QUEUE_PROCESSOR_TASK is None or QUEUE_PROCESSOR_TASK.done():
        QUEUE_PROCESSOR_TASK = asyncio.create_task(process_queue())
        return {
            "message": "Server Ready - Job started",
            "id": job_id,
            "filename": file.filename,
            "drive_folder": drive_folder
        }

    return {
        "message": "Server Busy - Job queued",
        "id": job_id,
        "filename": file.filename,
        "drive_folder": drive_folder,
        "queue_position": len(JOB_QUEUE)
    }

# ---------------------------
# /REMOVE endpoint - Unfinished, untested, use as your own cost.
# ---------------------------
@app.post("/remove")
async def remove_job(job_id: str = Form(...)):
    global JOB_QUEUE
    # Find job using UID
    for idx, job in enumerate(JOB_QUEUE):
        if job["id"] == job_id:
            JOB_QUEUE.pop(idx) # Remove from queue - no I am typing these comments by hands, not AI. I do use AI tho if you are asking!
            return {"message": f"Job '{job['filename']}' removed from queue."}
    return {"message": f"Job ID '{job_id}' not found in queue."}

# ---------------------------
# /MOVE endpoint - Unfinished, untested, use as your own cost.
# ---------------------------
@app.post("/move")
async def move_job(job_id: str = Form(...), position: int = Form(...)):
    global JOB_QUEUE
    if position < 1 or position > len(JOB_QUEUE):
        return {"message": f"Invalid position {position}, must be between 1 and {len(JOB_QUEUE)}."}

    # Find job using UID
    for idx, job in enumerate(JOB_QUEUE):
        if job["id"] == job_id:
            JOB_QUEUE.pop(idx) # take out of queue
            JOB_QUEUE.insert(position - 1, job) # add into this position
            return {"message": f"Job '{job['filename']}' moved to position {position}."}
    return {"message": f"Job ID '{job_id}' not found in queue."}
