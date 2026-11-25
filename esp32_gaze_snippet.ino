// ---------------------------------------------------------------
// Eye tracking for Momo's face (ESP32). ADD these pieces to your sketch.
// Python sends  momo-robot-x7k2q9/gaze  with text like "35,-10"
//   x: -100 (look left) ... +100 (look right)   (as seen on the screen)
//   y: -100 (look up)   ... +100 (look down)
// "0,0" means nobody is there: look straight ahead.
// ---------------------------------------------------------------

// 1) Global variables (near the top of the sketch)
float gazeX = 0, gazeY = 0;   // where Python says to look
float eyeX  = 0, eyeY  = 0;   // smoothed value that is actually drawn

// 2) In setup(), after you connect to MQTT, also subscribe:
//      client.subscribe("momo-robot-x7k2q9/gaze");

// 3) Inside your existing MQTT callback(topic, payload, length), add:
//
//   if (String(topic) == "momo-robot-x7k2q9/gaze") {
//     String s;
//     for (unsigned int i = 0; i < length; i++) s += (char)payload[i];
//     int comma = s.indexOf(',');
//     if (comma > 0) {
//       gazeX = s.substring(0, comma).toFloat();
//       gazeY = s.substring(comma + 1).toFloat();
//     }
//   }

// 4) Call this once per animation frame, BEFORE drawing the eyes:
void updateEyes() {
  eyeX += (gazeX - eyeX) * 0.3;   // glide toward the target (lower = slower, smoother)
  eyeY += (gazeY - eyeY) * 0.3;
}

// 5) When you draw each pupil, shift it by the gaze. Example:
//      int maxShiftX = 18;   // pixels the pupil may move sideways (adjust to your eye size)
//      int maxShiftY = 12;   // pixels up and down
//      int pupilX = eyeCenterX + (int)(eyeX / 100.0 * maxShiftX);
//      int pupilY = eyeCenterY + (int)(eyeY / 100.0 * maxShiftY);
//    Draw the pupil at (pupilX, pupilY) instead of (eyeCenterX, eyeCenterY).
//
// Tip: redraw only the pupils (erase the old spot, draw the new one) instead of
// clearing the whole screen every frame, to avoid flicker on the ILI9341.
