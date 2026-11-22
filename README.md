# Momo

AI desk-pet robot you can talk to.

- **Face:** animated ESP32 face (Wokwi), driven over MQTT
- **Ears:** microphone + Google speech recognition (`momo_talk.py`)
- **Brain:** Gemini, streamed (`momo_brain.py`)
- **Voice:** edge-tts, spoken while Gemini is still writing

```
mic -> speech-to-text -> Gemini -> mood tag -> MQTT -> Wokwi face
                                -> edge-tts -> speakers
```

## Install (Windows, Command Prompt)

```
pip install -r requirements.txt
```

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
| `LANGUAGE` | Speech recognition language, e.g. `en-IN`, `en-US` |
| `MIN_VOLUME` | Raise if Momo reacts to noise, lower if he misses you |

Say "stop" or "be quiet" to cut Momo off (headphones mode).

## MQTT topics

Prefix: `momo-robot-x7k2q9/` (use the same letters in every file)

| Topic | Message |
| --- | --- |
| `mood` | happy, surprised, wink, love, sad, angry, dead |
| `speaking` | 1 while Momo talks, 0 when done |

The broker is public (`broker.hivemq.com`), so keep the prefix random.

## Notes

- Do not use `pyaudio` or `pygame` (they fail to install on very new Python).
- If Gemini gives a 404, update the `MODELS` list in `momo_brain.py`.
