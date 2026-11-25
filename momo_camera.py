"""
momo_camera.py - Momo's eyes (the webcam).

  1. EYE TRACKING : finds the nearest face (or, if no face, a body) and sends
                    "x,y" (-100..100) to the face over MQTT so the eyes follow you.
  2. PHOTOS/VIDEO : take_photo(), start_video(), stop_video()
  3. FACE MEMORY  : recognizes people it has met, and can learn new ones.

You don't run this file. momo_talk.py uses it.

Install:  pip install opencv-python numpy
The first run downloads two small face models (about 37 MB) into momo_data/models.
Everything about people (names, face data) stays on THIS computer in momo_data/.
"""

import collections
import json
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime

import cv2
import numpy as np

from momo_brain import link

# ---------- settings ----------
CAMERA_INDEX = 0          # 0 = default webcam. Try 1 if you have more than one
SHOW_PREVIEW = True       # window with boxes. Keys: p = photo, v = start/stop video, q = hide window
GAZE_MIRROR = True        # True = eyes look toward you. If they look the WRONG way left/right, set False
BODY_FALLBACK = True      # follow a body when no face is visible
MIN_FACE_PX = 80          # faces smaller than this (far away) are tracked but not recognized
MEET_DELAY_S = 3.0        # an unknown face must stay this long before Momo introduces himself
GREET_COOLDOWN_S = 1800   # greet the same person at most once per 30 minutes
LOST_AFTER_S = 5          # nobody seen for this long = person left
MATCH_THRESHOLD = 0.363   # OpenCV's recommended cosine similarity for "same person"
MAX_FACES_PER_PERSON = 20
VIDEO_FPS = 20
MAX_VIDEO_S = 300         # videos stop by themselves after 5 minutes

TOPIC_GAZE = "momo-robot-x7k2q9/gaze"       # payload: "x,y"  (-100..100, y positive = down)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "momo_data")
MODEL_DIR = os.path.join(DATA_DIR, "models")
FACE_DIR = os.path.join(DATA_DIR, "faces")
PEOPLE_FILE = os.path.join(DATA_DIR, "people.json")
MEDIA_DIR = os.path.join(HERE, "momo_media")
for d in (MODEL_DIR, FACE_DIR, MEDIA_DIR):
    os.makedirs(d, exist_ok=True)

WINDOW = "Momo's eyes"

_ZOO = "https://github.com/opencv/opencv_zoo/raw/{branch}/models/{folder}/{file}"
MODEL_FILES = {
    "face_detection_yunet_2023mar.onnx": ("face_detection_yunet", 100_000),
    "face_recognition_sface_2021dec.onnx": ("face_recognition_sface", 10_000_000),
}


def ensure_models():
    """Download the two face models once. Returns {filename: path}."""
    paths = {}
    for fname, (folder, min_size) in MODEL_FILES.items():
        path = os.path.join(MODEL_DIR, fname)
        if os.path.exists(path) and os.path.getsize(path) > min_size:
            paths[fname] = path
            continue
        urls = [_ZOO.format(branch=b, folder=folder, file=fname) for b in ("main", "master")]
        urls.append(f"https://huggingface.co/opencv/{folder}/resolve/main/{fname}")
        done = False
        for url in urls:
            tmp = path + ".part"
            try:
                print(f"  (downloading {fname} ...)")
                urllib.request.urlretrieve(url, tmp)
                if os.path.getsize(tmp) > min_size:
                    os.replace(tmp, path)
                    done = True
                    break
            except Exception as e:
                print(f"  (download failed from {url.split('/')[2]}: {e})")
            if os.path.exists(tmp):
                os.remove(tmp)
        if not done:
            raise RuntimeError(
                f"Could not download {fname}.\n"
                f"  Download it by hand from https://github.com/opencv/opencv_zoo/tree/main/models/{folder}\n"
                f"  and put it in: {MODEL_DIR}")
        paths[fname] = path
    return paths


def clamp(v, lo=-100.0, hi=100.0):
    return max(lo, min(hi, v))


# =====================================================================
# People memory (saved in momo_data/people.json)
# =====================================================================
class PeopleStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.people = {}      # key (lowercase name) -> {"name","about","embeddings","first_seen","last_seen"}
        self.cache = {}       # key -> list of numpy arrays
        self.load()

    def load(self):
        if not os.path.exists(PEOPLE_FILE):
            return
        try:
            with open(PEOPLE_FILE, encoding="utf-8") as f:
                self.people = json.load(f)
        except (OSError, ValueError) as e:
            print(f"  (could not read {PEOPLE_FILE}: {e})")
            self.people = {}
        for key, p in self.people.items():
            self.cache[key] = [np.array(e, dtype=np.float32).reshape(1, -1) for e in p["embeddings"]]

    def save(self):
        tmp = PEOPLE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.people, f, indent=1)
        os.replace(tmp, PEOPLE_FILE)

    def names(self):
        with self.lock:
            return [p["name"] for p in self.people.values()]

    def get(self, name):
        with self.lock:
            return dict(self.people.get(name.lower(), {})) if name else {}

    def identify(self, recognizer, feat):
        """Returns (name or None, best_score)."""
        best_key, best = None, -1.0
        with self.lock:
            for key, embs in self.cache.items():
                for e in embs:
                    score = recognizer.match(feat, e, cv2.FaceRecognizerSF_FR_COSINE)
                    if score > best:
                        best, best_key = score, key
            if best_key is not None and best >= MATCH_THRESHOLD:
                return self.people[best_key]["name"], best
        return None, best

    def add(self, name, about, feats):
        key = name.strip().lower()
        now = time.time()
        with self.lock:
            p = self.people.get(key) or {"name": name.strip(), "about": "", "embeddings": [], "first_seen": now}
            if about:
                p["about"] = about.strip()
            p["embeddings"] = (p["embeddings"] + [f.flatten().tolist() for f in feats])[-MAX_FACES_PER_PERSON:]
            p["last_seen"] = now
            self.people[key] = p
            self.cache[key] = [np.array(e, dtype=np.float32).reshape(1, -1) for e in p["embeddings"]]
            self.save()

    def touch(self, name):
        with self.lock:
            p = self.people.get(name.lower())
            if p:
                p["last_seen"] = time.time()
                self.save()

    def forget(self, name):
        key = (name or "").lower()
        with self.lock:
            if key not in self.people:
                return False
            del self.people[key]
            self.cache.pop(key, None)
            self.save()
        for ext in (".jpg",):
            path = os.path.join(FACE_DIR, key.replace(" ", "_") + ext)
            if os.path.exists(path):
                os.remove(path)
        return True


# =====================================================================
# The camera
# =====================================================================
class Camera:
    def __init__(self):
        paths = ensure_models()
        self.detector = cv2.FaceDetectorYN.create(
            paths["face_detection_yunet_2023mar.onnx"], "", (320, 320), 0.8, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(
            paths["face_recognition_sface_2021dec.onnx"], "")
        self.hog = None
        if BODY_FALLBACK:
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        self.store = PeopleStore()
        self.lock = threading.Lock()      # protects self.frame
        self.vlock = threading.Lock()     # protects the video writer
        self.frame = None
        self.running = False
        self.thread = None
        self.cap = None

        # video
        self.writer = None
        self.video_path = None
        self.video_start = 0.0
        self.last_write = 0.0

        # who is in front of Momo
        self.events = collections.deque()          # ("greet", name) or ("meet", None)
        self.current_name = None
        self.recent_names = collections.deque(maxlen=4)
        self.recent_feats = collections.deque(maxlen=12)   # (time, feature, face picture)
        self.unknown_since = None
        self.last_greeted = {}
        self.decline_until = 0.0

    # ---------------- start / stop ----------------
    def start(self):
        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else 0
        self.cap = cv2.VideoCapture(CAMERA_INDEX, backend)
        if not self.cap.isOpened():
            raise RuntimeError(f"Can't open the camera (CAMERA_INDEX = {CAMERA_INDEX}). "
                               "Is another app using it?")
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        self.stop_video()
        if self.cap:
            self.cap.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
        link.publish(TOPIC_GAZE, "0,0")

    # ---------------- photos and video ----------------
    def take_photo(self):
        with self.lock:
            frame = None if self.frame is None else self.frame.copy()
        if frame is None:
            return None
        path = os.path.join(MEDIA_DIR, datetime.now().strftime("photo_%Y%m%d_%H%M%S.jpg"))
        cv2.imwrite(path, frame)
        return path

    def start_video(self):
        with self.lock:
            frame = None if self.frame is None else self.frame.copy()
        if frame is None:
            return None
        with self.vlock:
            if self.writer is not None:
                return self.video_path
            h, w = frame.shape[:2]
            path = os.path.join(MEDIA_DIR, datetime.now().strftime("video_%Y%m%d_%H%M%S.mp4"))
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), VIDEO_FPS, (w, h))
            if not writer.isOpened():
                return None
            self.writer, self.video_path = writer, path
            self.video_start, self.last_write = time.time(), 0.0
            return path

    def stop_video(self):
        """Returns (path, seconds) or None if nothing was recording."""
        with self.vlock:
            if self.writer is None:
                return None
            self.writer.release()
            self.writer = None
            return self.video_path, time.time() - self.video_start

    def is_recording(self):
        return self.writer is not None

    def _write_video(self, frame, now):
        with self.vlock:
            if self.writer is None:
                return
            if now - self.video_start > MAX_VIDEO_S:
                self.writer.release()
                self.writer = None
                print("  (video reached the time limit and stopped)")
                return
            if now - self.last_write >= 1.0 / VIDEO_FPS:
                self.writer.write(frame)
                self.last_write = now

    # ---------------- people ----------------
    def has_event(self):
        return bool(self.events)

    def next_event(self):
        try:
            return self.events.popleft()
        except IndexError:
            return None

    def context(self):
        """A sentence for Gemini about who Momo is looking at."""
        name = self.current_name
        if not name:
            return ""
        p = self.store.get(name)
        if not p:
            return ""
        text = f"You are talking to {p['name']}, a friend you recognize with your camera."
        if p.get("about"):
            text += f" They once told you about themselves: {p['about']}"
        return text + " Use their name now and then, but not in every sentence."

    def enroll(self, name, about=""):
        """Save the face Momo is looking at under this name. False if no clear face was seen lately."""
        now = time.time()
        samples = [s for s in list(self.recent_feats) if now - s[0] < 10]
        if len(samples) < 2:
            return False
        samples = samples[-6:]
        self.store.add(name, about, [s[1] for s in samples])
        crop = samples[-1][2]
        if crop is not None and crop.size:
            cv2.imwrite(os.path.join(FACE_DIR, name.lower().replace(" ", "_") + ".jpg"), crop)
        self.current_name = name
        self.last_greeted[name] = now
        self.unknown_since = None
        self.recent_names.clear()
        return True

    def forget(self, name):
        ok = self.store.forget(name)
        if self.current_name and self.current_name.lower() == (name or "").lower():
            self.current_name = None
            self.recent_names.clear()
        return ok

    def _lose_person(self):
        self.current_name = None
        self.unknown_since = None
        self.recent_names.clear()
        self.recent_feats.clear()

    def _update_people(self, now):
        names = list(self.recent_names)[-3:]
        if len(names) < 3 or len(set(names)) != 1:
            return
        who = names[0]
        if who is not None:                              # a face Momo knows
            self.unknown_since = None
            self.current_name = who
            if now - self.last_greeted.get(who, 0) > GREET_COOLDOWN_S:
                self.last_greeted[who] = now
                self.store.touch(who)
                self.events.append(("greet", who))
        else:                                            # a face Momo doesn't know
            self.current_name = None
            if self.unknown_since is None:
                self.unknown_since = now
            if now - self.unknown_since >= MEET_DELAY_S and now >= self.decline_until:
                self.decline_until = now + 60            # momo_talk sets the real value afterwards
                self.events.append(("meet", None))

    # ---------------- seeing ----------------
    def _find_body(self, frame):
        h, w = frame.shape[:2]
        scale = 320.0 / w
        small = cv2.resize(frame, (320, int(h * scale)))
        rects, _ = self.hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
        if len(rects) == 0:
            return None
        x, y, bw, bh = max(rects, key=lambda r: r[2] * r[3])
        return ((x + bw / 2) / scale, (y + bh * 0.2) / scale)     # aim near the head

    def _loop(self):
        sm_x = sm_y = 0.0
        sent_x = sent_y = 0
        sent_t = 0.0
        idle_sent = True
        last_feat_t = last_body_t = 0.0
        face_seen_t = body_t = 0.0
        body_target = None
        window_ok = SHOW_PREVIEW

        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            now = time.time()
            h, w = frame.shape[:2]
            with self.lock:
                self.frame = frame
            self._write_video(frame, now)

            # ----- find faces -----
            self.detector.setInputSize((w, h))
            faces = self.detector.detect(frame)[1]
            big = None
            if faces is not None and len(faces):
                big = max(faces, key=lambda f: f[2] * f[3])
                face_seen_t = now

            # ----- who to look at -----
            target = None
            if big is not None:
                target = (big[0] + big[2] / 2, big[1] + big[3] / 2)
            elif self.hog is not None and now - face_seen_t > 0.5:
                if now - last_body_t > 0.5:
                    last_body_t = now
                    found = self._find_body(frame)
                    if found:
                        body_target, body_t = found, now
                if body_target and now - body_t < 1.0:
                    target = body_target

            # ----- recognize the nearest face -----
            if big is not None and big[2] >= MIN_FACE_PX and now - last_feat_t > 0.4:
                last_feat_t = now
                try:
                    aligned = self.recognizer.alignCrop(frame, big)
                    feat = self.recognizer.feature(aligned)
                except cv2.error:
                    feat = None
                if feat is not None:
                    name, _score = self.store.identify(self.recognizer, feat)
                    x, y, fw, fh = [int(v) for v in big[:4]]
                    crop = frame[max(y, 0):y + fh, max(x, 0):x + fw].copy()
                    self.recent_feats.append((now, feat.copy(), crop))
                    self.recent_names.append(name)
                    self._update_people(now)

            if now - face_seen_t > LOST_AFTER_S and (self.recent_names or self.current_name):
                self._lose_person()

            # ----- move the eyes -----
            if target is not None:
                nx = (target[0] / w - 0.5) * 2
                ny = (target[1] / h - 0.5) * 2
                if GAZE_MIRROR:
                    nx = -nx
                sm_x += (clamp(nx * 100) - sm_x) * 0.5
                sm_y += (clamp(ny * 100) - sm_y) * 0.5
                idle_sent = False
                if now - sent_t > 0.1 and (abs(sm_x - sent_x) >= 4 or abs(sm_y - sent_y) >= 4):
                    sent_x, sent_y, sent_t = int(sm_x), int(sm_y), now
                    link.publish(TOPIC_GAZE, f"{sent_x},{sent_y}")
            elif now - max(face_seen_t, body_t) > 2.0 and not idle_sent:
                sm_x = sm_y = 0.0
                sent_x = sent_y = 0
                idle_sent = True
                link.publish(TOPIC_GAZE, "0,0")          # nobody there: eyes back to the middle

            # ----- preview window -----
            if window_ok:
                try:
                    disp = frame.copy()
                    if faces is not None:
                        for f in faces:
                            x, y, fw, fh = [int(v) for v in f[:4]]
                            is_big = big is not None and f[0] == big[0] and f[1] == big[1]
                            color = (0, 200, 0) if (is_big and self.current_name) else (0, 165, 255)
                            cv2.rectangle(disp, (x, y), (x + fw, y + fh), color, 2)
                            if is_big:
                                label = self.current_name or "new face"
                                cv2.putText(disp, label, (x, max(y - 8, 15)),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                    if self.is_recording():
                        cv2.circle(disp, (20, 20), 8, (0, 0, 255), -1)
                        cv2.putText(disp, "REC", (36, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    cv2.imshow(WINDOW, disp)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("p"):
                        print("  photo:", self.take_photo())
                    elif key == ord("v"):
                        if self.is_recording():
                            print("  video saved:", self.stop_video())
                        else:
                            print("  recording:", self.start_video())
                    elif key == ord("q"):
                        cv2.destroyWindow(WINDOW)
                        window_ok = False
                except cv2.error:
                    print("  (the preview window isn't available; install opencv-python, not -headless)")
                    window_ok = False
