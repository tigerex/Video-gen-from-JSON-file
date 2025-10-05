# 🎬 Automated Video Composition Project

This project automates **video creation from structured JSON scene data** — transforming text, images, and audio into a rendered video using Python.  
It is designed for dynamic marketing, tutorials, or AI-generated content pipelines.

---

## 📁 Project Overview

The system reads a JSON file (`scene_composition_agent_output.json`) describing:
- 🎞️ **Scenes**: Each with background image/video, text layers, and animations  
- 🔊 **Audio narration**: One per scene  
- ✍️ **Typography & layout info**: Fonts, positions, transitions  

The output is an automatically composed video rendered with animations and synced audio.

---

## 🧰 Features

- Load multi-scene compositions from JSON  
- Add background images, text overlays, and Ken Burns-style animations  
- Fade, slide, and zoom transitions  
- Combine with scene-specific audio  
- Use **Google Fonts API** to dynamically fetch fonts  
- Output customizable by **resolution** (360p → Full HD) and **FPS (30/60)**  

---

## 🚀 Setup Instructions

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/votuduc/mcp_Agents.git
```

---

### 2️⃣ Create and Activate a Virtual Environment

#### macOS / Linux
```bash
python3 -m venv venv
source venv/bin/activate
```

#### Windows (PowerShell)
```bash
python -m venv venv
venv\Scripts\activate
```

---

### 3️⃣ Install Dependencies

Make sure you have `pip` up to date, then install all requirements:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 4️⃣ Get a Google Fonts API Key (Unfinished Documenting)

1. Visit: [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials)
2. Enable the **Google Fonts Developer API**
3. Create an **API key**
4. Store it locally in a `.env` file at the project root:

```
GOOGLE_FONTS_API_KEY=your_api_key_here
```

---

### 5️⃣ Prepare Your Input JSON

Your input should follow the format of `scene_composition_agent_output.json`, e.g.:

```json
{
  "videoMetadata": {
    "title": "Automate Your Content From Idea to LIVE Article in Minutes",
    "resolution": "1920x1080",
    "fps": 30
  },
  "scenes": [
    {
      "scene_id": 1,
      "audioUrl": "https://drive.google.com/file/d/.../view",
      "layers": [
        {
          "type": "image",
          "url": "https://drive.google.com/file/d/.../view",
          "animation": { "type": "KenBurns", "direction": "topLeft" }
        },
        {
          "type": "text",
          "content": "Automate Your Content:",
          "font": "Merriweather",
          "position": { "x": 960, "y": 200, "anchor": "center" }
        }
      ]
    }
  ]
}
```

---

### 6️⃣ Run the Video Composer

If your main script is `testMoviePy.ipynb` or `main.py`, execute:

```bash
python main.py
```

or inside Jupyter Notebook:

```python
%run testMoviePy.ipynb
```

This will:
- Parse the JSON file  
- Download images/audio from Google Drive  
- Fetch fonts from the Google Fonts API  
- Generate the final composed video  

---

## ⚙️ Configuration

| Option | Description | Default |
|--------|--------------|----------|
| `--input` | Path to JSON composition file | `scene_composition_agent_output.json` |
| `--output` | Output video filename | `output_<date>.mp4` |
| `--resolution` | Target resolution (360p–1080p) | From JSON |
| `--fps` | Frames per second (30/60) | From JSON |

---

## 📦 Project Structure

```
.
├── scene_composition_agent_output.json
├── testMoviePy.ipynb
├── requirements.txt
├── .env
├── assets/
│   ├── images/
│   ├── audio/
│   └── fonts/
└── output/
    └── final_video.mp4
```

---

## 🧩 Dependencies

- **moviepy** – video composition and rendering  
- **Pillow** – image processing  
- **requests** – API and file downloads  
- **python-dotenv** – environment variable handling  
- **gdown** or **pydrive2** – Google Drive asset downloads  

---

## 🧠 Workflow Summary

1. Load composition data from JSON  
2. Initialize video metadata (fps, resolution, title)  
3. Download fonts, images, and audio assets  
4. Generate clips for each scene (text + animation)  
5. Combine and synchronize with audio  
6. Export final MP4 video  

---

## 💡 Tips

- Always activate your virtual environment before running scripts  
- If assets don’t download, check Google Drive sharing permissions  
- Make sure `ffmpeg` is installed and accessible in your system PATH  
- Use `.env` for private keys and configs — never commit them to Git  

