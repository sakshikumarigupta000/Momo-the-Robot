# Momo

AI desk-pet robot you can talk to.

- **Face:** animated ESP32 face (Wokwi), driven over MQTT
- **Ears:** microphone + Google speech recognition (`momo_talk.py`)
- **Brain:** Gemini, streamed (`momo_brain.py`)
- **Voice:** edge-tts, spoken while Gemini is still writing
- **Eyes (in progress):** webcam face tracking and face memory (`momo_camera.py`)

```
mic -> speech-to-text -> Gemini -> mood tag -> MQTT -> Wokwi face
                                -> edge-tts -> speakers

webcam -> face / body detection -> gaze "x,y" -> MQTT -> Wokwi eyes
```

## Files

| File | What it does |
| --- | --- |
| `momo_talk.py` | The file you run. Listens, turns speech into text, decides when to answer |
| `momo_brain.py` | Talks to Gemini, speaks the reply, sends mood and speaking messages to the face |
| `momo_camera.py` | Webcam: eye tracking, photos/video, recognizing people (see [Camera](#camera-in-progress)) |
| `esp32_gaze_snippet.ino` | Code to add to the ESP32 sketch so the eyes follow you |
| `requirements.txt` | Python packages |

## Install (Windows, Command Prompt)

```
pip install -r requirements.txt
```

For the camera, also install:

```
pip install opencv-python
```

Use `opencv-python`, not `opencv-python-headless`, or the preview window won't open.

Momo's voice playback uses Windows' built-in player, so this version is Windows only.

## Gemini API key (free)

1. Create a key at https://aistudio.google.com/apikey
2. Save it, then open a NEW Command Prompt:

```
setx GEMINI_API_KEY "your-key-here"
```

Never upload the key to GitHub.

## Wokwi libraries (Library Manager tab)

- Adafruit ILI9341
- Adafruit GFX Library
- Adafruit BusIO
- PubSubClient

## Run

1. Press Play in Wokwi and wait for `Voice link connected!`
2. In Command Prompt:

```
python momo_talk.py
```

3. Just talk to Momo.

Other commands:

```
python momo_talk.py --devices   # list microphones
python momo_talk.py --level     # test how loud your mic hears you
```

## Settings (top of `momo_talk.py`)

| Setting | Meaning |
| --- | --- |
| `HEADPHONES` | True: you can interrupt Momo by talking. False: Momo stops listening while he talks (for speakers) |
| `ALWAYS_LISTEN` | True: answers everything. False: only when you say "Momo" |
| `MIC_DEVICE` | `None` for the default mic, or a number from `--devices` |
| `LANGUAGE` | Speech recognition language, e.g. `en-IN`, `en-US` |
| `MIN_VOLUME` | Raise if Momo reacts to noise, lower if he misses you |
| `SILENCE_S` | How long a pause means you're done talking (lower = faster replies) |
| `INTERRUPT_FACTOR` | Headphones mode: how much louder than normal you must be to cut Momo off |

Say "stop" or "be quiet" to cut Momo off (headphones mode).

### Voice and replies (top of `momo_brain.py`)

| Setting | Meaning |
| --- | --- |
| `VOICE`, `PITCH`, `RATE`, `VOLUME` | Momo's edge-tts voice (default `en-US-AnaNeural`, a bit higher and slower) |
| `MODELS` | Gemini models to try, in order. If one is busy or missing, the next is used |
| `SYSTEM` | Momo's personality and the mood-tag rules |

Momo picks a reply length from what you say: "story", "poem" or "in detail" gets a long answer, "explain" or "why" gets a few sentences, everything else gets one or two.

## Camera (in progress)

`momo_camera.py` gives Momo eyes. It is written but **not yet connected to `momo_talk.py`**.

What it can do:

- **Eye tracking:** finds the nearest face (or a body if no face is visible) and sends where it is to the face, so Momo's eyes follow you.
- **Photos and video:** saved to `momo_media/`. In the preview window press `p` for a photo, `v` to start/stop video, `q` to hide the window. Videos stop on their own after 5 minutes.
- **Face memory:** recognizes people it has met, greets them (at most once every 30 minutes), and can learn new faces with a name and a note about them.

The first run downloads two small OpenCV face models (about 37 MB) into `momo_data/models/`.

**Privacy:** names, face data and face pictures are saved only on your computer, in `momo_data/`. Photos and videos go in `momo_media/`. Keep both folders out of GitHub.

Camera settings are at the top of `momo_camera.py`:

| Setting | Meaning |
| --- | --- |
| `CAMERA_INDEX` | 0 = default webcam. Try 1 if you have more than one |
| `SHOW_PREVIEW` | Show a window with boxes around faces |
| `GAZE_MIRROR` | If the eyes look the wrong way left/right, set to False |
| `BODY_FALLBACK` | Follow a body when no face is visible |
| `MIN_FACE_PX` | Faces smaller than this (far away) are followed but not recognized |

### ESP32: make the eyes follow you

Add the pieces from `esp32_gaze_snippet.ino` to your Wokwi sketch:

1. Subscribe to `momo-robot-x7k2q9/gaze` after connecting to MQTT.
2. Read the `"x,y"` message in your MQTT callback.
3. Call `updateEyes()` each frame and shift the pupils by the gaze.

Tip: redraw only the pupils instead of clearing the whole screen, to avoid flicker on the ILI9341.

## MQTT topics

Prefix: `momo-robot-x7k2q9/` (use the same letters in every file, including the ESP32 sketch)

| Topic | Message |
| --- | --- |
| `mood` | happy, surprised, wink, love, sad, angry, dead |
| `speaking` | 1 while Momo talks, 0 when done |
| `gaze` | `x,y` from -100 to 100 (x: left to right, y: up to down). `0,0` = look straight ahead |

The broker is public (`broker.hivemq.com`), so keep the prefix random.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No GEMINI_API_KEY found` | Run `setx` again and open a **new** Command Prompt |
| Momo answers background noise | Raise `MIN_VOLUME`, or set `ALWAYS_LISTEN = False` |
| Momo doesn't hear you | Run `--level`, then lower `MIN_VOLUME` or pick another mic with `--devices` |
| Momo hears himself on speakers | Set `HEADPHONES = False` |
| Gemini gives a 404 | Update the `MODELS` list in `momo_brain.py` |
| `All models busy` | Free-tier limit. Wait a minute and try again |
| Face doesn't change | Check the Wokwi sketch uses the same topic prefix and shows `Voice link connected!` |
| `Can't open the camera` | Close other apps using the webcam, or change `CAMERA_INDEX` |

## Notes

- Do not use `pyaudio` or `pygame` (they fail to install on very new Python).
- Momo remembers the last few messages of the conversation while the program is running. Restarting clears it.
