"""
momo_talk.py  -  THE file you run. Talk to Momo with your voice.

  Speech to text : microphone + Google speech recognition (this file)
  AI + voice     : momo_brain.py (must be in the SAME folder)

Run:
    python momo_talk.py             # talk to Momo
    python momo_talk.py --devices   # list microphones
    python momo_talk.py --level     # test: shows how loud your mic hears you

Install:
    pip install requests paho-mqtt edge-tts SpeechRecognition sounddevice numpy
"""

import re
import sys
import threading
import time
import numpy as np
import sounddevice as sd
import speech_recognition as sr

from momo_brain import (ask_and_speak, stop_speaking, speak, warm_up, shutdown,
                        API_KEY)

# ---------- settings ----------
HEADPHONES = False       # True = you wear headphones, so you can INTERRUPT Momo by talking.
                         # False = Momo stops listening while he talks (no echo on speakers).
ALWAYS_LISTEN = True     # True = answers everything you say. False = only when you say "Momo"
MIC_DEVICE = None        # None = default mic. Or a number from --devices
RATE = 16000
LANGUAGE = "en-IN"       # "en-US" for American English
MIN_VOLUME = 300         # raise if Momo reacts to noise, lower if he misses your voice
INTERRUPT_FACTOR = 2.0   # headphones: you must be this much louder than the threshold to cut Momo off
SILENCE_S = 0.7          # a pause this long means "I'm done talking" (lower = faster reply)
MAX_RECORD_S = 15        # longest sentence

# "stop", "stop talking", "momo be quiet please" ... every word must be one of these
STOP_WORDS = {"stop", "shh", "shush", "quiet", "enough", "talking", "be", "please", "ok", "okay", "now"}
# one-word things that are still worth answering when ALWAYS_LISTEN is on
SHORT_OK = {"hello", "hi", "hey", "yes", "no", "thanks", "thank", "bye", "goodbye", "hmm"}

WAKE = r"(hey momo|hi momo|ok momo|okay momo|momo|mo mo|mumu|moomoo|mommo|hey mom|hi mom)\b[,.!?]*\s*"
WAKE_START = r"^\s*" + WAKE          # only counts at the START of the sentence

recognizer = sr.Recognizer()


def level(block):
    return float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))


def stop_talking():
    """Cut Momo off if he is still speaking."""
    stop_speaking()


# ---------------------------------------------------------------------
# SPEECH TO TEXT
# ---------------------------------------------------------------------
def record_phrase(on_speech=None):
    """Wait for you to speak, record until you stop.
    on_speech() is called once if you get loud enough to interrupt (headphones mode)."""
    block = int(RATE * 0.1)
    silence_blocks = max(1, int(SILENCE_S / 0.1))
    before = []
    frames = []
    started = False
    fired = False
    silent = 0

    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", device=MIC_DEVICE) as stream:
        ambient = [level(stream.read(block)[0]) for _ in range(5)][1:]   # skip the first block
        threshold = max(MIN_VOLUME, 2.5 * sum(ambient) / len(ambient))
        t0 = time.time()
        while True:
            data = stream.read(block)[0]
            vol = level(data)
            loud = vol > threshold

            if on_speech and not fired and vol > threshold * INTERRUPT_FACTOR:
                fired = True
                on_speech()

            if not started:
                before = (before + [data])[-3:]
                if loud:
                    started = True
                    frames.extend(before)
                    t0 = time.time()
            else:
                frames.append(data)
                silent = 0 if loud else silent + 1
                if silent >= silence_blocks or time.time() - t0 > MAX_RECORD_S:
                    break
    return sr.AudioData(np.concatenate(frames).tobytes(), RATE, 2)


def to_text(audio):
    try:
        return recognizer.recognize_google(audio, language=LANGUAGE)
    except sr.UnknownValueError:
        return None
    except sr.RequestError as e:
        print(f"  (speech recognition problem: {e})")
        return None


# ---------------------------------------------------------------------
# AI + TEXT TO SPEECH (done in momo_brain.py)
# ---------------------------------------------------------------------
def answer(text):
    print(f"You: {text}")
    try:
        # Momo starts talking while the AI is still writing.
        # wait=True (speakers): returns only after Momo finishes, so the mic never hears him.
        # wait=False (headphones): returns once the AI is done writing.
        ask_and_speak(text, wait=not HEADPHONES)
    except Exception as e:
        print("Brain error:", e)
        return
    if not HEADPHONES:
        time.sleep(0.4)                     # let the room go quiet


def answer_async(text):
    """Headphones mode: answer in the background so we can keep listening (and be interrupted)."""
    threading.Thread(target=answer, args=(text,), daemon=True).start()


def main():
    if "--devices" in sys.argv:
        print(sd.query_devices())
        print("\nPut the number of your microphone into MIC_DEVICE at the top of this file.")
        return
    if "--level" in sys.argv:
        print("Talk for 4 seconds...")
        rec = sd.rec(int(4 * RATE), samplerate=RATE, channels=1, dtype="int16", device=MIC_DEVICE)
        sd.wait()
        print("Loudest level:", int(np.abs(rec).max()), "(should be in the hundreds or thousands)")
        return
    if not API_KEY:
        sys.exit('No GEMINI_API_KEY found. Run setx GEMINI_API_KEY your-key and open a NEW Command Prompt.')

    warm_up()                                # open the connection to Google
    speak("Hi hi! I'm Momo. Talk to me!")    # hello, so you know the speaker works
    mode = "headphones: you can interrupt Momo by talking" if HEADPHONES else "speakers: Momo listens after he finishes"
    print(f"Momo is listening ({mode}). Just talk! Ctrl+C to stop.\n")

    while True:
        audio = record_phrase(on_speech=stop_talking if HEADPHONES else None)
        text = to_text(audio)
        if not text:
            continue

        lowtext = text.lower()
        has_wake = bool(re.search(WAKE_START, lowtext))
        body = re.sub(WAKE_START, "", lowtext, count=1).strip()
        plain = re.sub(r"[^\w\s]", "", body).strip()
        words = plain.split()

        # "stop", "stop talking", "momo be quiet please" ...
        if words and all(w in STOP_WORDS for w in words) and any(w in {"stop", "shh", "shush", "quiet", "enough"} for w in words):
            print("You: (stop)")
            stop_talking()
            continue

        if not ALWAYS_LISTEN and not has_wake:
            continue                         # not meant for Momo

        if not words:                        # they only said "Momo"
            print("You: Momo?")
            speak("Yes? I'm listening!", wait=not HEADPHONES)
            continue

        if ALWAYS_LISTEN and len(words) < 2 and plain not in SHORT_OK:
            continue                         # probably background noise

        (answer_async if HEADPHONES else answer)(body)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        shutdown()                           # stop talking, close the face's mouth
        print("\nBye!")
