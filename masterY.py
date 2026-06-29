"""
masterY.py — SortIQ Brain - Section 1: Imports & Configuration
"""

# ========================================== #
#                  IMPORTS                   #
# ========================================== #

# Standard libraries
import os
import time
import queue
import threading
import json
from collections import deque

# pip install influxdb-client

# Hardware libraries
import serial

# Vision libraries
import cv2
import numpy as np

# Local vision engine (Option B modular approach)
from vision_engine import EWasteSorter

# SortIQ custom multi-object belt tracker
from VEREVRUGO import SortIQTracker

# ========================================== #
#          SERIAL & DB CONFIGURATION         #
# ========================================== #
PICO_PORT = "COM11"
ESP32_PORT = "COM7"
SERIAL_BAUD = 115200

# InfluxDB credentials
INFLUXDB_URL    = "http://localhost:8086"
INFLUXDB_TOKEN  = "sortiq_token_fixed_123"
INFLUXDB_ORG    = "sortiq_corp"
INFLUXDB_BUCKET = "factory_data"

# ========================================== #
#          DUAL-MOTOR CONFIGURATION          #
# ========================================== #
# Universal "rest" state — blades parallel to belt, e-waste flows freely
MOTOR_HOME = 0

# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! #
# !!  NOTE: Negative values (-180) are LOGICAL commands.           !! #
# !!  The ESP32 firmware maps these to physical MG995 servo        !! #
# !!  degrees using: servoDeg = 90 + (pythonAngle / 2).            !! #
# !!  -180 → 0°,  0 → 90° (home),  +180 → 180°.                   !! #
# !!  Do NOT change these values without updating the firmware.    !! #
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! #

# Logical angles sent to ESP32 firmware.
# Firmware maps: servoDeg = 90 + (pythonAngle / 2)
# pythonAngle =   0 → servo 90° (home, neutral)
# pythonAngle = -90 → servo 45° (CCW 45° physical sweep)
# pythonAngle = +90 → servo 135° (CW 45° physical sweep)

# Left PCB Motor (LPM)
LPM_HIGH_VAL = -90   # High-value PCB — CCW 45°
LPM_HAZARD   = -90   # Battery — CCW 45° (same bin as high value)
LPM_STD      = 90    # Standard PCB chunk — CW 45°

# Right Magnet Motor (RPM)
RPM_PERMANENT = 90   # Permanent magnet — CW 45°
RPM_FERROUS   = -90  # Ferrous metal — CCW 45°

# ========================================== #
#           PHYSICAL DIMENSIONS              #
# ========================================== #
BELT_WIDTH_MM = 100
BELT_LENGTH_MM = 500
MAG_RADIUS_MM = 30   # Detection radius for Adafruit MLX magnetic sensor
IND_RADIUS_MM = 30   # Detection radius for Inductive Proximity Sensor

PIXELS_TO_MM = 0.1283

# ========================================== #
#               LOGIC CONSTANTS              #
# ========================================== #
COLLISION_WINDOW_MS = 500
DECISION_LIMIT = 7.0
CONF_THRESH = 0.65

# ========================================== #
#    ACTIVE LEARNING (HEISENBERG MISMATCH)   #
# ========================================== #
HEISENBERG_DIR = "Heisenberg"
HEISENBERG_CONF_THRESH = 0.75


# ================================================================== #
#            SECTION 2: HARDWARE INIT & QUEUES                       #
# ================================================================== #

db_queue = queue.Queue(maxsize=500)
actuation_queue = queue.Queue()

esp32_lock = threading.Lock()


def db_worker():
    """
    Daemon thread: drains db_queue and writes telemetry to InfluxDB.
    Handles both 'sort_event' and 'heisenberg_event' measurements.
    """
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS

    client = InfluxDBClient(
        url=INFLUXDB_URL,
        token=INFLUXDB_TOKEN,
        org=INFLUXDB_ORG
    )
    write_api = client.write_api(write_options=SYNCHRONOUS)

    while True:
        try:
            data = db_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            measurement = data.get("measurement", "sort_event")

            if measurement == "heisenberg_event":
                # ---- Heisenberg mismatch telemetry ------------------
                point = (
                    Point("heisenberg_event")
                    .tag("belt", "1")
                    .tag("trigger_type", data.get("trigger_type", "unknown"))
                    .tag("class_name", data.get("class_name", "unknown"))
                    .field("confidence", float(data.get("confidence", 0.0)))
                    .field("mag_delta_uT", float(data.get("mag_delta_uT", 0.0)))
                    .field("track_id", int(data.get("track_id", 0)))
                    .field("image_path", str(data.get("image_path", "")))
                    .field("total_saved", int(data.get("total_saved", 0)))
                )
            else:
                # ---- Standard sort event telemetry ------------------
                point = (
                    Point("sort_event")
                    .tag("belt", "1")
                    .tag("item_type", data.get("class_name", "unknown"))
                    .tag("motor", data.get("motor", "NONE"))
                    .field("confidence", float(data.get("confidence", 0.0)))
                    .field("belt_velocity_px", float(data.get("belt_velocity_px", 0.0)))
                    .field("dwell_time_ms", float(data.get("dwell_time_ms", 0.0)))
                    .field("vision_ms", float(data.get("vision_ms", 0.0)))
                    .field("decision_ms", float(data.get("decision_ms", 0.0)))
                    .field("dispatch_ms", float(data.get("dispatch_ms", 0.0)))
                    .field("actuation_ms", float(data.get("actuation_ms", 0.0)))
                    .field("total_pipeline_ms", float(
                        data.get("vision_ms", 0.0) +
                        data.get("decision_ms", 0.0) +
                        data.get("dispatch_ms", 0.0) +
                        data.get("actuation_ms", 0.0)
                    ))
                    .field("is_mag_active", int(data.get("is_mag_active", False)))
                    .field("mag_delta_uT", float(data.get("mag_delta_uT", 0.0)))
                    .field("angle", int(data.get("angle", 0)))
                    .field("track_id", int(data.get("track_id", 0)))
                )
            write_api.write(
                bucket=INFLUXDB_BUCKET,
                org=INFLUXDB_ORG,
                record=point
            )
        except Exception as e:
            print(f"[DB_WORKER] InfluxDB write failed: {e}")
        finally:
            db_queue.task_done()


def esp32_dispatcher():
    """
    Daemon thread: drains actuation_queue and sends motor commands
    to the ESP32 over serial.
    """
    while True:
        motor_id, target_angle, execute_timestamp = actuation_queue.get()
        try:
            delay_ms = int((execute_timestamp - time.time()) * 1000.0)
            if delay_ms < 0:
                delay_ms = 0

            payload = json.dumps({
                "motor": motor_id,
                "angle": target_angle,
                "delay_ms": delay_ms
            }) + "\n"

            print(f"[ESP32_DISPATCH] → motor={motor_id} angle={target_angle} delay_ms={delay_ms}")

            if esp32_serial is not None and esp32_serial.is_open:
                with esp32_lock:
                    esp32_serial.write(payload.encode("utf-8"))
            else:
                print(f"[ESP32_DISPATCH] ⚠️  Serial not open — command dropped: {payload.strip()}")
        except Exception as e:
            print(f"[ESP32_DISPATCH] Serial write failed: {e}")
        finally:
            actuation_queue.task_done()


def esp32_listener():
    """
    Daemon thread: drains the ESP32 serial buffer to prevent overflow.

    CRITICAL: esp32_lock must NEVER be held during sleep().
    Sleeping inside the lock starves esp32_dispatcher, preventing
    all motor commands from being sent (lock starvation bug).
    """
    while True:
        if esp32_serial is not None and esp32_serial.is_open:
            try:
                has_data = False
                with esp32_lock:
                    has_data = esp32_serial.in_waiting > 0
                    if has_data:
                        raw_line = esp32_serial.readline().decode("utf-8").strip()
                        if raw_line:
                            print(f"[ESP32 FEEDBACK] {raw_line}")
                # Sleep OUTSIDE the lock so esp32_dispatcher can always acquire
                if not has_data:
                    time.sleep(0.01)
            except Exception:
                time.sleep(0.1)
        else:
            time.sleep(1.0)


# ========================================== #
#             THREAD EXECUTION               #
# ========================================== #
pico_serial = None
esp32_serial = None

thread_db = threading.Thread(target=db_worker, daemon=True)
thread_db.start()
print("[BOOT] db_worker thread started")

thread_esp32 = threading.Thread(target=esp32_dispatcher, daemon=True)
thread_esp32.start()
print("[BOOT] esp32_dispatcher thread started")

thread_esp32_listen = threading.Thread(target=esp32_listener, daemon=True)
thread_esp32_listen.start()
print("[BOOT] esp32_listener thread started")


# ========================================== #
#           HARDWARE BOOT SEQUENCE           #
# ========================================== #

try:
    esp32_serial = serial.Serial(ESP32_PORT, SERIAL_BAUD, timeout=0)
    print(f"[BOOT] ESP32 serial connected on {ESP32_PORT}")
except Exception as e:
    print(f"[BOOT] ⚠️  ESP32 serial FAILED on {ESP32_PORT}: {e}")
    print("[BOOT]    Actuation commands will be silently dropped.")

try:
    pico_serial = serial.Serial(PICO_PORT, SERIAL_BAUD, timeout=0.1)
    print(f"[BOOT] Pico serial connected on {PICO_PORT}")
except Exception as e:
    print(f"[BOOT] ⚠️  Pico serial FAILED on {PICO_PORT}: {e}")
    print("[BOOT]    Sensor data will be unavailable.")

try:
    sorter = EWasteSorter(model_path="best.onnx", conf_thresh=CONF_THRESH)
    print("[BOOT] EWasteSorter loaded (best.onnx)")

    tracker = SortIQTracker()
    print("[BOOT] SortIQTracker initialised")
except Exception as e:
    print(f"[BOOT] ⚠️  AI/Tracker init FAILED: {e}")
    raise


# ========================================== #
#     DYNAMIC TARE (AUTO-ZERO CALIBRATION)   #
# ========================================== #
MAG_BASELINE = 0.0
IND_BASELINE = 0.0

if pico_serial is not None and pico_serial.is_open:
    print("[TARE] Starting auto-zero calibration (50 samples, 3s timeout)...")

    _tare_mag_readings = []
    _tare_ind_readings = []
    _tare_start = time.time()
    _TARE_TARGET = 50
    _TARE_TIMEOUT = 3.0

    while len(_tare_mag_readings) < _TARE_TARGET:
        if time.time() > _tare_start + _TARE_TIMEOUT:
            print(f"[TARE] ⚠️  Calibration Timeout! Only got "
                  f"{len(_tare_mag_readings)}/{_TARE_TARGET} readings.")
            print("[TARE]    Baselines left at 0.0 — sensor fusion degraded.")
            break

        try:
            raw_line = pico_serial.readline().decode("utf-8").strip()
            if not raw_line:
                continue

            sample = json.loads(raw_line)

            if "uT" in sample and "ind" in sample:
                _tare_mag_readings.append(float(sample["uT"]))
                _tare_ind_readings.append(float(sample["ind"]))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            continue

    if _tare_mag_readings:
        MAG_BASELINE = sum(_tare_mag_readings) / len(_tare_mag_readings)
        IND_BASELINE = sum(_tare_ind_readings) / len(_tare_ind_readings)
        print(f"[TARE] ✅ Calibration complete — "
              f"MAG_BASELINE={MAG_BASELINE:.2f} uT, "
              f"IND_BASELINE={IND_BASELINE:.2f}")
else:
    print("[TARE] Pico not available — skipping calibration, baselines = 0.0")

print("[BOOT] ====== SortIQ Brain — Section 2 boot complete ======")


# ================================================================== #
#            SECTION 3: THE MAIN LOOP                                #
# ================================================================== #

# ========================================== #
#            PRE-LOOP CONSTANTS              #
# ========================================== #
MAG_SPIKE_THRESH = 100.0
PERMANENT_MAGNET_THRESH = 500.0  # TODO: calibrate with real magnets
IND_SWITCH_THRESH = 0.5
IND_SENSOR_ENABLED = False

ACTUATION_X_LINE = 675
PHYSICAL_DISTANCE_LPM_MM = 185.0
PHYSICAL_DISTANCE_RPM_MM = 315.0
CAMERA_TO_SENSOR_OFFSET_MM = 0.0  # TODO: Measure and set before physical testing

MAX_ACTUATED_HISTORY = 500
actuated_ids_deque = deque(maxlen=MAX_ACTUATED_HISTORY)

per_track_mag_peak = {}

_heisenberg_count = len(os.listdir(HEISENBERG_DIR)) if os.path.exists(HEISENBERG_DIR) else 0

# ---- Visualization State -----------------------------------------
color_map = {
    "battery":            (0, 0, 255),
    "PCBValue_Component": (0, 165, 255),
    "Pcb_Chunk":          (255, 255, 0),
    "Mag_Chunk":          (255, 0, 255)
}

sort_counts = {"battery": 0, "PCBValue_Component": 0, "Pcb_Chunk": 0, "Mag_Chunk": 0}

fps_counter = 0
fps_display = 0
fps_timer = time.time()

actuation_flash = None

last_valid_sensor_time = time.time()


# ========================================== #
#           CAMERA INITIALIZATION            #
# ========================================== #
cap = cv2.VideoCapture(1)
if not cap.isOpened():
    print("[FATAL] Could not open camera (index 1)")
    raise RuntimeError("Camera unavailable")

time.sleep(1.0)
print("[BOOT] Camera warmup complete")

cv2.namedWindow("SortIQ Brain", cv2.WINDOW_AUTOSIZE)
print("[BOOT] Camera opened — entering main loop")

_camera_stop_event = threading.Event()
_frame_queue = queue.Queue(maxsize=1)

def _camera_worker(cap, frame_queue, stop_event):
    fail_count = 0
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            fail_count += 1
            if fail_count > 30:  # ~1s of failures at 30fps
                print(f"[CAMERA] {fail_count} consecutive read failures — stopping")
                break
            time.sleep(0.03)  # brief wait before retry
            continue
        fail_count = 0  # reset on success
        if not frame_queue.empty():
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                pass
        frame_queue.put(frame)

thread_camera = threading.Thread(
    target=_camera_worker,
    args=(cap, _frame_queue, _camera_stop_event),
    daemon=True
)
thread_camera.start()
print("[BOOT] Camera capture thread started")


# ========================================== #
#              THE MAIN LOOP                 #
# ========================================== #
_last_frame_time = time.time()
_frame_duration_ms = 33.0

try:
    while True:

        # ---------------------------------------------------------- #
        # STEP 1: READ FRAME                                         #
        # ---------------------------------------------------------- #
        try:
            frame = _frame_queue.get(timeout=3.0)
        except queue.Empty:
            print("[MAIN] Camera thread timeout — exiting loop")
            break

        _now = time.time()
        _frame_duration_ms = (_now - _last_frame_time) * 1000.0
        _last_frame_time = _now

        # ---------------------------------------------------------- #
        # STEP 2: DRAIN PICO BUFFER                                  #
        # ---------------------------------------------------------- #
        latest_uT = 0.0
        latest_ind = 0.0
        latest_sensor_valid = False

        if pico_serial is not None and pico_serial.is_open:
            last_valid_line = None
            while pico_serial.in_waiting > 0:
                try:
                    raw_line = pico_serial.readline().decode("utf-8").strip()
                    if raw_line:
                        last_valid_line = raw_line
                except (UnicodeDecodeError, serial.SerialException):
                    continue

            if last_valid_line is not None:
                try:
                    sensor_data = json.loads(last_valid_line)
                    if "uT" in sensor_data and "ind" in sensor_data:
                        latest_uT = float(sensor_data["uT"])
                        latest_ind = float(sensor_data["ind"])
                        latest_sensor_valid = "error" not in sensor_data
                except (json.JSONDecodeError, ValueError):
                    pass

        # ---------------------------------------------------------- #
        # STEP 3: EVALUATE SENSORS                                   #
        # ---------------------------------------------------------- #
        mag_delta = abs(latest_uT - MAG_BASELINE)
        is_mag_active        = mag_delta > MAG_SPIKE_THRESH
        is_permanent_magnet  = mag_delta > PERMANENT_MAGNET_THRESH
        is_ind_active        = False

        # ---------------------------------------------------------- #
        # STEP 4: VISION & TRACKING                                  #
        # ---------------------------------------------------------- #
        _t_vision_start = time.time()
        detections = sorter.process_frame(frame)
        confirmed_tracks = tracker.update(detections, dt=_frame_duration_ms / 33.0)
        _vision_ms = (time.time() - _t_vision_start) * 1000.0

        # ---------------------------------------------------------- #
        # STEP 5: LOGIC & ACTUATION HANDOFF                          #
        # ---------------------------------------------------------- #
        for trk in confirmed_tracks:
            bbox = trk["bbox"]
            x2 = bbox[2]
            track_id = trk["track_id"]
            class_name = trk["class_name"]
            confidence = trk["confidence"]
            belt_velocity_px = trk["belt_velocity_px"]
            dwell_time_ms = trk["dwell_time_ms"]

            # ---- Update per-track magnetic peak memory --------------
            if track_id not in per_track_mag_peak:
                per_track_mag_peak[track_id] = {
                    "peak_delta": mag_delta,
                    "is_permanent": is_permanent_magnet
                }
            else:
                if mag_delta > per_track_mag_peak[track_id]["peak_delta"]:
                    per_track_mag_peak[track_id]["peak_delta"] = mag_delta
                    per_track_mag_peak[track_id]["is_permanent"] = is_permanent_magnet

            # --- Has this item crossed the actuation line? ----------
            if x2 >= ACTUATION_X_LINE and track_id not in actuated_ids_deque:

                actuated_ids_deque.append(track_id)
                sort_counts[class_name] = sort_counts.get(class_name, 0) + 1
                actuation_flash = (class_name, time.time() + 0.5)

                _t_decision_start = time.time()

                payload = None

                if class_name == "battery":
                    payload = ("LPM", LPM_HAZARD)

                elif class_name == "PCBValue_Component":
                    payload = ("LPM", LPM_HIGH_VAL)

                elif class_name == "Pcb_Chunk":
                    payload = ("LPM", LPM_STD)

                elif class_name == "Mag_Chunk" or is_mag_active:
                    _track_mag = per_track_mag_peak.get(track_id, {
                        "peak_delta": mag_delta,
                        "is_permanent": is_permanent_magnet
                    })
                    if _track_mag["is_permanent"]:
                        payload = ("RPM", RPM_PERMANENT)
                        print(f"[SORT] Permanent magnet — peak uT delta: {_track_mag['peak_delta']:.1f}")
                    else:
                        payload = ("RPM", RPM_FERROUS)
                        print(f"[SORT] Ferrous metal — peak uT delta: {_track_mag['peak_delta']:.1f}")

                else:
                    payload = ("RPM", RPM_FERROUS)

                _decision_ms = (time.time() - _t_decision_start) * 1000.0

                # --- Calculate timing using per-motor distance -------
                if payload is not None:
                    motor_distance_mm = PHYSICAL_DISTANCE_LPM_MM if payload[0] == "LPM" else PHYSICAL_DISTANCE_RPM_MM
                    if belt_velocity_px > 0:
                        distance_px = motor_distance_mm / PIXELS_TO_MM
                        frames_to_target = distance_px / belt_velocity_px
                        time_to_target_ms = frames_to_target * 33.0
                    else:
                        time_to_target_ms = 500.0
                else:
                    time_to_target_ms = 500.0

                execute_timestamp = time.time() + (time_to_target_ms / 1000.0)

                # --- Dispatch to ESP32 --------------------------------
                if payload is not None:
                    actuation_queue.put((payload[0], payload[1], execute_timestamp))
                    print(f"[SORT] ✅ Dispatched: class={class_name} motor={payload[0]} "
                          f"angle={payload[1]} time_to_target={time_to_target_ms:.0f}ms "
                          f"track_id={track_id}")

                _dispatch_ms = (time.time() - _t_decision_start) * 1000.0 - _decision_ms

                # --- InfluxDB telemetry ------------------------------
                try:
                    db_queue.put_nowait({
                        "measurement": "sort_event",
                        "track_id": track_id,
                        "class_name": class_name,
                        "confidence": trk.get("peak_confidence", confidence),
                        "belt_velocity_px": belt_velocity_px,
                        "dwell_time_ms": dwell_time_ms,
                        "is_mag_active": is_mag_active,
                        "is_ind_active": is_ind_active,
                        "mag_delta_uT": per_track_mag_peak.get(track_id, {}).get("peak_delta", mag_delta),
                        "motor": payload[0] if payload else "NONE",
                        "angle": payload[1] if payload else 0,
                        "vision_ms": _vision_ms,
                        "decision_ms": _decision_ms,
                        "dispatch_ms": _dispatch_ms,
                        "actuation_ms": 0.0,
                        "timestamp": time.time(),
                    })
                except queue.Full:
                    pass

                # ---------------------------------------------------- #
                # STEP 6: HEISENBERG MISMATCH CATCH (vision-only)      #
                # ---------------------------------------------------- #
                # Vision says metal/battery/pcb but sensors are silent.
                metal_classes = {"battery", "PCBValue_Component", "Pcb_Chunk", "Mag_Chunk"}
                if latest_sensor_valid and class_name in metal_classes and not is_mag_active and not is_ind_active:
                    os.makedirs(HEISENBERG_DIR, exist_ok=True)
                    heisenberg_path = os.path.join(
                        HEISENBERG_DIR,
                        f"mismatch_{track_id}_{int(time.time())}.jpg"
                    )
                    if _heisenberg_count < 500:
                        cv2.imwrite(heisenberg_path, frame)
                        _heisenberg_count += 1
                        print(f"[HEISENBERG] Vision/Sensor mismatch — "
                              f"AI={class_name} conf={confidence:.2f} but sensors silent. "
                              f"Saved: {heisenberg_path} ({_heisenberg_count} total)")
                        # ✅ FIX: Write Heisenberg event to InfluxDB
                        try:
                            db_queue.put_nowait({
                                "measurement": "heisenberg_event",
                                "trigger_type": "vision_only",
                                "class_name": class_name,
                                "confidence": confidence,
                                "mag_delta_uT": mag_delta,
                                "track_id": track_id,
                                "image_path": heisenberg_path,
                                "total_saved": _heisenberg_count,
                            })
                        except queue.Full:
                            pass

        # ---- Clean up mag peak memory for disappeared tracks --------
        active_ids = {t["track_id"] for t in confirmed_tracks}
        for gone_id in list(per_track_mag_peak.keys()):
            if gone_id not in active_ids:
                del per_track_mag_peak[gone_id]

        # ---------------------------------------------------------- #
        # STEP 6B: HEISENBERG — SENSOR-ONLY MAGNET CATCH             #
        # ---------------------------------------------------------- #
        if is_mag_active and latest_sensor_valid:
            vision_saw_metal = any(
                t["class_name"] == "Mag_Chunk" for t in confirmed_tracks
            )
            if not vision_saw_metal:
                os.makedirs(HEISENBERG_DIR, exist_ok=True)
                label = "permanent" if is_permanent_magnet else "ferrous"
                heisenberg_path = os.path.join(
                    HEISENBERG_DIR,
                    f"sensor_only_{label}_{int(time.time())}.jpg"
                )
                if _heisenberg_count < 500:
                    cv2.imwrite(heisenberg_path, frame)
                    _heisenberg_count += 1
                    print(f"[HEISENBERG] Sensor-only {label} magnet — "
                          f"uT delta={mag_delta:.1f}, vision missed. "
                          f"Saved: {heisenberg_path} ({_heisenberg_count} total)")
                    # ✅ FIX: Write Heisenberg event to InfluxDB
                    try:
                        db_queue.put_nowait({
                            "measurement": "heisenberg_event",
                            "trigger_type": f"sensor_only_{label}",
                            "class_name": "Mag_Chunk",
                            "confidence": 0.0,
                            "mag_delta_uT": mag_delta,
                            "track_id": -1,
                            "image_path": heisenberg_path,
                            "total_saved": _heisenberg_count,
                        })
                    except queue.Full:
                        pass

        # ---------------------------------------------------------- #
        # STEP 7: VISUALIZATION                                      #
        # ---------------------------------------------------------- #
        h, w = frame.shape[:2]

        fps_counter += 1
        if time.time() - fps_timer >= 1.0:
            fps_display = fps_counter
            fps_counter = 0
            fps_timer = time.time()

        if latest_sensor_valid:
            last_valid_sensor_time = time.time()
        pico_alive = (time.time() - last_valid_sensor_time) < 0.5

        if actuation_flash is not None:
            flash_class, flash_expire = actuation_flash
            if time.time() < flash_expire:
                flash_color = color_map.get(flash_class, (0, 255, 0))
                overlay = frame.copy()
                cv2.rectangle(overlay, (ACTUATION_X_LINE, 0), (w, h), flash_color, -1)
                cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)
            else:
                actuation_flash = None

        cv2.line(frame, (ACTUATION_X_LINE, 0), (ACTUATION_X_LINE, h),
                 (0, 0, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "ACTUATION", (ACTUATION_X_LINE + 5, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

        for trk in confirmed_tracks:
            x1, y1, x2, y2 = map(int, trk["bbox"])
            cls       = trk["class_name"]
            box_color = color_map.get(cls, (0, 255, 0))
            vel_px    = trk["belt_velocity_px"]
            dwell_ms  = trk["dwell_time_ms"]

            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

            label = f"ID:{trk['track_id']} {cls} {trk['confidence']:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(frame, (x1, y1 - 18), (x1 + tw + 4, y1), box_color, -1)
            cv2.putText(frame, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            arrow_len = int(vel_px * 3)
            if arrow_len > 5:
                cv2.arrowedLine(frame, (cx, cy), (cx + arrow_len, cy),
                                box_color, 2, cv2.LINE_AA, tipLength=0.3)

            dwell_ratio = min(dwell_ms / (DECISION_LIMIT * 1000), 1.0)
            bar_w  = x2 - x1
            filled = int(bar_w * dwell_ratio)
            bar_color = (0, int(200 * (1 - dwell_ratio)), int(200 * dwell_ratio))
            cv2.rectangle(frame, (x1, y2 + 2), (x1 + filled, y2 + 8), bar_color, -1)
            cv2.rectangle(frame, (x1, y2 + 2), (x2, y2 + 8), (80, 80, 80), 1)

        # ---- Hardware & Sensor HUD (Top Left) ----------------------
        cv2.rectangle(frame, (5, 5), (290, 180), (20, 20, 20), -1)
        cv2.rectangle(frame, (5, 5), (290, 180), (60, 60, 60),  1)

        hud_y  = 28
        line_h = 26

        mag_col = (0, 0, 255) if is_mag_active else (0, 200, 0)
        cv2.putText(frame,
                    f"MAG: {latest_uT:.1f} uT {'[SPIKE]' if is_mag_active else ''}",
                    (14, hud_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, mag_col, 1, cv2.LINE_AA)

        ind_col = (0, 0, 255) if is_ind_active else (0, 200, 0)
        cv2.putText(frame,
                    f"IND: {latest_ind:.2f} {'[SPIKE]' if is_ind_active else ''}",
                    (14, hud_y + line_h), cv2.FONT_HERSHEY_SIMPLEX, 0.55, ind_col, 1, cv2.LINE_AA)

        pico_col = (0, 255, 0) if pico_alive else (0, 0, 255)
        cv2.putText(frame, f"PICO:  {'ONLINE' if pico_alive else 'OFFLINE'}",
                    (14, hud_y + line_h * 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, pico_col, 1, cv2.LINE_AA)

        esp32_alive = esp32_serial is not None and esp32_serial.is_open
        esp32_col   = (0, 255, 0) if esp32_alive else (0, 0, 255)
        cv2.putText(frame, f"ESP32: {'ONLINE' if esp32_alive else 'OFFLINE'}",
                    (14, hud_y + line_h * 3), cv2.FONT_HERSHEY_SIMPLEX, 0.55, esp32_col, 1, cv2.LINE_AA)

        cv2.putText(frame, f"FPS:   {fps_display}",
                    (14, hud_y + line_h * 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)

        # ---- Per-Class Sort Counter (Bottom Left) ------------------
        line_h_sm    = 22
        counter_y    = h - 10
        panel_top    = h - (len(sort_counts) * line_h_sm) - 15
        cv2.rectangle(frame, (5, panel_top), (250, h - 5), (20, 20, 20), -1)
        cv2.rectangle(frame, (5, panel_top), (250, h - 5), (60, 60, 60),  1)

        for cls_name, count in reversed(list(sort_counts.items())):
            col = color_map.get(cls_name, (200, 200, 200))
            cv2.putText(frame, f"{cls_name}: {count}", (14, counter_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
            counter_y -= line_h_sm

        cv2.imshow("SortIQ Brain", frame)

        # ---------------------------------------------------------- #
        # STEP 8: EXIT CONDITION                                     #
        # ---------------------------------------------------------- #
        if cv2.waitKey(1) & 0xFF == ord("q"):
            print("[MAIN] 'q' pressed — shutting down")
            break

except KeyboardInterrupt:
    print("[MAIN] Ctrl+C received — initiating graceful shutdown")

finally:
    _camera_stop_event.set()

    if esp32_serial is not None and esp32_serial.is_open:
        try:
            for motor_id in ("LPM", "RPM"):
                home_payload = json.dumps({
                    "motor": motor_id,
                    "angle": MOTOR_HOME,
                    "delay_ms": 0
                }) + "\n"
                with esp32_lock:
                    esp32_serial.write(home_payload.encode("utf-8"))
            time.sleep(0.15)
            print("[CLEANUP] Motors homed")
        except Exception as e:
            print(f"[CLEANUP] Motor home failed: {e}")

    if esp32_serial is not None and esp32_serial.is_open:
        esp32_serial.close()
        print("[CLEANUP] ESP32 serial closed")

    if pico_serial is not None and pico_serial.is_open:
        pico_serial.close()
        print("[CLEANUP] Pico serial closed")

    cap.release()
    cv2.destroyAllWindows()
    print("[MAIN] SortIQ Brain shutdown complete.")
