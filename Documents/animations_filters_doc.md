## Available Animations

Animations are applied to individual layers within a scene. They are defined inside an `animation` object in the layer's JSON definition.

#### Common Animation Parameters
*   `type` (string): The name of the animation (e.g., `"fadeIn"`).
*   `startTime_sec` (float, optional): The time in seconds when the animation should start, relative to the beginning of the scene. Defaults to `0.0`.
*   `duration_sec` (float, optional): The duration of the animation effect in seconds.

---

### Animation Types

#### 1. FadeIn
**Description:** Gradually fades the layer in from transparent to opaque.
**JSON Parameters:**
*   `type`: `"fadeIn"`
*   `duration_sec`: (float) How long the fade should last.

**Example:**
```json
"animation": {
  "type": "fadeIn",
  "startTime_sec": 0.5,
  "duration_sec": 1.0
}
```

#### 2. FadeOut
**Description:** Gradually fades the layer out from opaque to transparent.
**JSON Parameters:**
*   `type`: `"fadeOut"`
*   `startTime_sec`: (float) The time when the fade-out should *begin*.
*   `duration_sec`: (float) How long the fade should last.

**Example:**
```json
"animation": {
  "type": "fadeOut",
  "startTime_sec": 4.0,
  "duration_sec": 1.0
}
```

#### 3. CrossFadeIn
**Description:** Fades the layer in while fading out the layers behind it.
**JSON Parameters:**
*   `type`: `"crossFadeIn"`
*   `duration_sec`: (float) The duration of the crossfade effect.

**Example:**
```json
"animation": {
  "type": "crossFadeIn",
  "duration_sec": 1.5
}
```

#### 4. CrossFadeOut
**Description:** Fades the layer out while fading in the layers that appear after it.
**JSON Parameters:**
*   `type`: `"crossFadeOut"`
*   `startTime_sec`: (float) Time when the crossfade-out should *begin*.
*   `duration_sec`: (float) The duration of the crossfade effect.

**Example:**
```json
"animation": {
  "type": "crossFadeOut",
  "startTime_sec": 3.0,
  "duration_sec": 1.5
}
```

#### 5. SlideIn
**Description:** Slides the layer into the frame from a specified direction.
**JSON Parameters:**
*   `type`: `"slideIn"`
*   `duration_sec`: (float) How long the slide animation should take.
*   `direction`: (string) The side to slide from (`"left"`, `"right"`, `"top"`, `"bottom"`).

**Example:**
```json
"animation": {
  "type": "slideIn",
  "duration_sec": 0.8,
  "direction": "left"
}
```

#### 6. SlideOut
**Description:** Slides the layer out of the frame to a specified direction.
**JSON Parameters:**
*   `type`: `"slideOut"`
*   `startTime_sec`: (float) The time when the slide-out should *begin*.
*   `duration_sec`: (float) How long the slide animation should take.
*   `direction`: (string) The side to slide to (`"left"`, `"right"`, `"top"`, `"bottom"`).

**Example:**
```json
"animation": {
  "type": "slideOut",
  "startTime_sec": 5.0,
  "duration_sec": 0.8,
  "direction": "right"
}
```

#### 7. MultiplySpeed
**Description:** Speeds up the clip by a given factor, adjusting its duration.
**JSON Parameters:**
*   `type`: `"multiplySpeed"`
*   `factor`: (float) The multiplier for the speed (e.g., `2.0` for double speed).
*   `final_duration`: (float, optional) The target duration for the clip after speeding it up.

**Example:**
```json
"animation": {
  "type": "multiplySpeed",
  "factor": 2.5
}
```

#### 8. Resize
**Description:** Resizes the layer to a specific dimension or by a scale factor.
**JSON Parameters:**
*   `type`: `"resize"`
*   `width`: (integer, optional) The new width in pixels.
*   `height`: (integer, optional) The new height in pixels.
*   `scale`: (float, optional) A scaling factor (e.g., `0.5` for half size). If provided, `width` and `height` are ignored.

**Example:**
```json
"animation": {
  "type": "resize",
  "scale": 1.2
}
```

#### 9. KenBurns
**Description:** A pan-and-zoom effect, typically used on images. The animation spans the entire duration of the layer.
**JSON Parameters:**
*   `type`: `"kenBurns"`
*   `start_zoom`: (float) The initial zoom level (e.g., `1.0` for original size).
*   `end_zoom`: (float) The final zoom level (e.g., `1.2` for 20% zoom in).

**Example:**
```json
"animation": {
  "type": "kenBurns",
  "start_zoom": 1.0,
  "end_zoom": 1.15
}
```

---

## Available Filters

Filters are applied to individual layers to change their visual appearance. They are defined inside a `filter` object in the layer's JSON definition.

---

### Filter Types

#### 1. LumContrast
**Description:** Adjusts the luminosity and contrast of the layer.
**JSON Parameters:**
*   `type`: `"lumContrast"`
*   `lum`: (integer, optional) Luminosity adjustment. Negative values darken, positive values brighten.
*   `contrast`: (integer, optional) Contrast adjustment.
*   `contrast_thr`: (integer, optional) Contrast threshold.

**Example:**
```json
"filter": {
  "type": "lumContrast",
  "lum": 10,
  "contrast": -5
}
```

#### 2. Painting
**Description:** Gives the layer a "painting" effect.
**JSON Parameters:**
*   `type`: `"painting"`
*   `saturation`: (float, optional) The degree of color saturation (e.g., `1.5` for more vibrant colors).
*   `black`: (float, optional) The intensity of black in the image.

**Example:**
```json
"filter": {
  "type": "painting",
  "saturation": 1.8
}
```

#### 3. InvertColors
**Description:** Inverts the colors of the layer.
**JSON Parameters:**
*   `type`: `"invertColors"`

**Example:**
```json
"filter": {
  "type": "invertColors"
}
```

#### 4. BlackAndWhite
**Description:** Converts the layer to grayscale.
**JSON Parameters:**
*   `type`: `"blackAndWhite"`

**Example:**
```json
"filter": {
  "type": "blackAndWhite"
}
```

#### 5. Blink
**Description:** Makes the layer blink (disappear and reappear).
**JSON Parameters:**
*   `type`: `"blink"`
*   `on_duration`: (float, optional) Duration in seconds the layer is visible.
*   `off_duration`: (float, optional) Duration in seconds the layer is hidden.
note: The parameter in the MoviePy library asks for duration_on & duration_off. The purpose of flipping the parameter is to easier indentify if the error come from the JSON file or from the MoviePy library.

**Example:**
```json
"filter": {
  "type": "blink",
  "on_duration": 0.5,
  "off_duration": 0.2
}
```

#### 6. MultiplyColor
**Description:** Multiplies the layer's colors by a specified color.
**JSON Parameters:**
*   `type`: `"multiplyColor"`
*   `color`: (string) The color to multiply with (e.g., `"#FF0000"` for red, or `"blue"`).
Note: this value will be convert to a float value in the code.

**Example:**
```json
"filter": {
  "type": "multiplyColor",
  "color": "#87CEEB"
}
```