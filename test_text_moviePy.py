import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# MoviePy 2.0 imports
from moviepy import CompositeVideoClip, TextClip, ColorClip

# ==================================================================
# Simplified Data Classes
# ==================================================================
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
    font: Optional[str] = "custom-font" 
    size: Optional[int] = 36
    color: Optional[str] = "white"
    position: Optional[Position] = None
    animation: Optional[str] = None

# ==================================================================
# Test Function
# ==================================================================
def render_text_layer_test():
    """
    Creates a video with a merged text layer, using a robust method
    to add vertical padding and prevent clipping.
    """
    print("🚀 Starting text layer rendering test with canvas padding...")

    font_file_path = "assets\\fonts\\Merriweather.ttf"

    if not os.path.exists(font_file_path):
        print(f"!!! FONT FILE NOT FOUND: '{font_file_path}' !!!")
        return

    # --- 1. Define sample text layers ---
    scene_layers = [
        Layer(
            layer_id="bullet_point_0_1",
            type="text",
            content="Juggling content ideas in random notes apps.",
            size=40,
            color="#EEEEEE",
            position=Position(x=100, y=400, anchor="left")
        ),
        Layer(
            layer_id="bullet_point_1_1",
            type="text",
            content="Tasks scattered across Trello, emails, and sticky notes.",
            size=40,
            color="#EEEEEE",
            position=Position(x=100, y=480, anchor="left")
        ),
        Layer(
            layer_id="bullet_point_2_1",
            type="text",
            content="A separate, static spreadsergrwgwr'",
            size=40,
            color="#EEEEEE",
            position=Position(x=100, y=560, anchor="left")
        ),
        Layer(
            layer_id="bullet_point_2_1",
            type="text",
            content="A separate, stefqeqe3134yhyur 'calendar.'",
            size=40,
            color="#EEEEEE",
            position=Position(x=100, y=560, anchor="left")
        ),
        Layer(
            layer_id="bullet_point_2_1",
            type="text",
            content="A sepaqe345678'calendar.'",
            size=40,
            color="#EEEEEE",
            position=Position(x=100, y=560, anchor="left")
        ),
        Layer(
            layer_id="bullet_point_2_1",
            type="text",
            content="wqrefqer your 'calendar.'",
            size=40,
            color="#EEEEEE",
            position=Position(x=100, y=560, anchor="left")
        )
    ]

    # --- 2. Merge the text layers ---
    text_layers_to_merge = [layer for layer in scene_layers if layer.type == 'text']
    merged_content = "\n".join([layer.content for layer in text_layers_to_merge])
    first_text_layer = text_layers_to_merge[0]

    print(f"\n📝 Using font: {font_file_path}")
    print(f"📄 Merged Text Content:\n---\n{merged_content}\n---\n")

    # --- 3. Create the MoviePy TextClip with the PADDING FIX ---
    width, height = 1920, 1080
    
    try:
        # ===================================================================
        # START: PADDING FIX
        # ===================================================================

        # STEP 1: Create a temporary clip to measure the (clipped) size
        temp_clip = TextClip(
            text=merged_content,
            font=font_file_path,
            font_size=first_text_layer.size,
            color=first_text_layer.color,
            method="label"
        )
        text_w, text_h = temp_clip.size
        temp_clip.close() # Release the temporary clip

        # STEP 2: Define the padding and create the final, larger canvas size
        vertical_padding = 20  # <-- Increase this value if text is still clipped
        
        # The new canvas will have the original width but a taller height
        padded_canvas_size = (text_w, text_h + vertical_padding)

        print(f"Original (clipped) size: {text_w}x{text_h}")
        print(f"Applying {vertical_padding}px padding. New canvas size: {padded_canvas_size[0]}x{padded_canvas_size[1]}")

        # STEP 3: Re-render the text onto the new, larger canvas.
        # MoviePy will automatically center the text in this new space,
        # creating the invisible padding we need.
        txt_clip = TextClip(
            text=merged_content,
            font=font_file_path,
            font_size=first_text_layer.size,
            color=first_text_layer.color,
            size=padded_canvas_size, # <-- Force the render canvas size
            method="label"
        )
        
        # ===================================================================
        # END: PADDING FIX
        # ===================================================================

        # Now, position this new, correctly-sized clip
        if first_text_layer.position:
            # Note: We use the new clip's size for positioning
            clip_w, clip_h = txt_clip.size
            pos_x, pos_y = first_text_layer.position.x, first_text_layer.position.y
            anchor = (first_text_layer.position.anchor or "left").lower()
            if "center" in anchor: pos_x -= clip_w / 2
            elif "right" in anchor: pos_x -= clip_w
            txt_clip = txt_clip.with_position((pos_x, pos_y))

    except Exception as e:
        print(f"ERROR: Could not create TextClip. Details: {e}")
        return

    # --- 4. Create the final video composition ---
    background = ColorClip(size=(width, height), color=(0, 0, 0), duration=5)
    txt_clip = txt_clip.with_duration(5)
    final_clip = CompositeVideoClip([background, txt_clip], size=(width, height))

    output_filename = "text_layer_test_padded.mp4"
    
    # --- 5. Write the final video file ---
    try:
        print(f"🎬 Writing video to {output_filename}...")
        final_clip.write_videofile(output_filename, fps=30, codec="libx264", audio_codec="aac")
        print(f"✅ Success! Video saved to {os.path.join(os.getcwd(), output_filename)}")
    except Exception as e:
        print(f"ERROR: Failed to write video file. {e}")
    finally:
        final_clip.close()

if __name__ == "__main__":
    render_text_layer_test()