#!/usr/bin/python3

import dropbox
import time
import itertools
import io
import os
import sys
import subprocess
import configparser
import uuid
import warnings
import imutils
import json
import cv2
from picamera.array import PiRGBArray
from picamera import PiCamera, Color
from datetime import datetime, time as datetime_time
from fractions import Fraction

config_parser = configparser.RawConfigParser()
config_file = f"{os.path.dirname(os.path.realpath(sys.argv[0]))}/config"
config_parser.read(config_file)
db_config = config_parser['db_config']

MAX_FILE_SIZE_MB = db_config.getint('max_file_size_mb', 8)
RESOLUTION_X = db_config.getint('resolution_x', 1280)
RESOLUTION_Y = db_config.getint('resolution_y', 720)
FRAMERATE = db_config.getint('framerate', 15)
SENSOR_MODE = db_config.getint('sensor_mode', 0)
ROTATION = db_config.getint('rotation', 0)
BRIGHTNESS = db_config.getint('brightness', 50)
CONTRAST = db_config.getint('contrast', 0)
QUALITY = db_config.getint('quality', 25)
BITRATE = db_config.getint('bitrate', 20000000)
TEXT_SIZE = db_config.getint('text_size', 16)
TEXT_COLOR = db_config.get('text_color', '#fff')
PROBE_SIZE = db_config.get('probe_size', '16M')
STREAM_FORMAT = db_config.get('stream_format', 'h264')
UPLOAD_FORMAT = db_config.get('upload_format', 'mp4')
DATE_FORMAT = db_config.get('date_format', '%Y-%m-%d')
TIME_FORMAT = db_config.get('time_format', '%H.%M.%S')
NIGHT_ENABLED = db_config.getboolean('night_enabled', fallback=False)
UPLOAD_ENABLED = db_config.getboolean('upload_enabled', fallback=True)
TIME_STATE = db_config.get('time_state', 'day')
MODE = db_config.get('mode', 'motion')
DELTA_THRESH = db_config.getint('delta_thresh', 5)
MIN_UPLOAD_SECONDS = db_config.getfloat('min_upload_seconds', 3.0)
MIN_MOTION_FRAMES = db_config.getint('min_motion_frames', 8)
MIN_AREA = db_config.get('min_area', 5000)
CAMERA_WARMUP_TIME = db_config.getfloat('camera_warmup_time', 2.5)
ACCESS_TOKEN = os.environ.get('DB_ACCESS_TOKEN')

CAMERA = PiCamera()
RAW_CAPTURE = None

warnings.filterwarnings("ignore")

def out_path():
  return f"{os.path.dirname(os.path.realpath(sys.argv[0]))}/output"

class TempImage:
	def __init__(self, basePath=out_path(), ext=".jpg"):
		self.path = "{base_path}/{rand}{ext}".format(base_path=basePath,
			rand=str(uuid.uuid4()), ext=ext)

	def cleanup(self):
		os.remove(self.path)

def now():
  return datetime.now().strftime(TIME_FORMAT)

def today():
  return datetime.now().strftime(DATE_FORMAT)

def write(s):
  sys.stdout.write(f"{today()} {now()}: {s}\n")

if sys.version_info[0] < 3:
  write("Python 3 is required.")
  sys.exit(1)

try:
  len(ACCESS_TOKEN)
except Exception:
  write("Dropbox access token not set.")
  sys.exit(1)
else:
  DBX = dropbox.Dropbox(ACCESS_TOKEN)

def is_day():
  now = datetime.now().time()
  return now < datetime_time(17, 00) and now >= datetime_time(9, 00)

def is_night():
  if not NIGHT_ENABLED:
    return
  now = datetime.now().time()
  return now >= datetime_time(17, 00) or now < datetime_time(9, 00)

def must_update():
  return (
    NIGHT_ENABLED and
    (
      is_day() and TIME_STATE is not 'day' or
      is_night() and TIME_STATE is not 'night'
    )
  )

def init_camera(delay=5):
  global CAMERA
  global TIME_STATE
  global RAW_CAPTURE

  write(f"Initializing camera in {delay}s...")
  time.sleep(delay)
  write(f"Initializing camera...")

  if MODE == 'motion':
    img_resolution = tuple([RESOLUTION_X, RESOLUTION_Y])
    CAMERA.resolution = img_resolution
    RAW_CAPTURE = PiRGBArray(CAMERA, size=img_resolution)
    return record_motion()
  else:
    if delay >= 10:
      CAMERA.close()
      CAMERA = PiCamera()

    settings = {
      'rotation': ROTATION,
      'annotate_text_size': TEXT_SIZE,
      'annotate_foreground': Color(TEXT_COLOR),
      'resolution': (RESOLUTION_X, RESOLUTION_Y),
      'brightness': BRIGHTNESS,
      'contrast': CONTRAST,
    }

    day = {
      'framerate': FRAMERATE,
      'shutter_speed': 0,
      'exposure_mode': 'auto',
      'iso': 0,
    }

    night = {
      'framerate': Fraction(1, 6),
      'shutter_speed': 6000000,
      'exposure_mode': 'off',
      'iso': 800,
    }

    if is_night():
      write("Assigning nighttime settings.")
      settings = {**settings, **night}
      TIME_STATE = 'night'
    else:
      write("Assigning daytime settings.")
      settings = {**settings, **day}
      TIME_STATE = 'day'

    for k, v in settings.items():
      setattr(CAMERA, k, v)

    record_sequence()

def stream_outputs():
  for i in itertools.count(1):
    yield io.open(f"{out_path()}/stream{i}.{STREAM_FORMAT}", 'wb')

def convert_stream(stream_file):
  write(f"Converting {stream_file} to {UPLOAD_FORMAT}...")
  timestamp = f"{today()}_{now()}"

  try:
    p = subprocess.Popen([
      'ffmpeg',
      '-y',
      '-hide_banner',
      '-loglevel', 'panic',
      '-framerate', str(FRAMERATE),
      '-probesize', str(PROBE_SIZE),
      '-i', str(stream_file),
      '-c', 'copy', str(f"{timestamp}.{UPLOAD_FORMAT}"),
    ])
    p.wait()
  except Exception as e:
    return write(f"ffmpeg error: {e}")


  if UPLOAD_ENABLED and MODE is 'sequence':
    upload_sequence(stream_file, timestamp)
  else:
    os.remove(stream_file)

def upload_motion(ts, frame, timestamp):
  t = TempImage()
  cv2.imwrite(t.path, frame)
  write("[UPLOAD] {}".format(ts))
  path = f"/hc_{today()}/{timestamp}.jpg"
  DBX.files_upload(open(t.path, "rb").read(), path)
  t.cleanup()

def upload_sequence(stream_file, timestamp):
  converted_file = f"{timestamp}.{UPLOAD_FORMAT}"

  with open(converted_file, 'rb') as f:
    try:
      DBX.files_upload(f.read(), f"/hc_{today()}/{timestamp}.{UPLOAD_FORMAT}")
    except Exception as e:
      write(f"Dropbox upload error: {e}")

  os.remove(stream_file)
  os.remove(converted_file)

  write(f"Uploaded {converted_file}.")

def record_motion():
  write("Recording on motion...")

  time.sleep(CAMERA_WARMUP_TIME)
  avg = None
  lastUploaded = datetime.now()
  motionCounter = 0

  for f in CAMERA.capture_continuous(
    RAW_CAPTURE,
    format="bgr",
    use_video_port=True
  ):
    frame = f.array
    raw_timestamp = datetime.now()
    text = "Unoccupied"

    frame = imutils.resize(frame, width=500)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)

    if avg is None:
      write("[INFO] starting background model...")
      avg = gray.copy().astype("float")
      RAW_CAPTURE.truncate(0)
      continue

    cv2.accumulateWeighted(gray, avg, 0.5)
    frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(avg))

    thresh = cv2.threshold(frameDelta, DELTA_THRESH, 255,
      cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,
      cv2.CHAIN_APPROX_SIMPLE)
    cnts = imutils.grab_contours(cnts)

    for c in cnts:
      if cv2.contourArea(c) < MIN_AREA:
        continue

      (x, y, w, h) = cv2.boundingRect(c)
      cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
      text = "Occupied"

    ts = now()
    cv2.putText(frame, "Room Status: {}".format(text), (10, 20),
      cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
    cv2.putText(frame, ts, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
      0.35, (0, 0, 255), 1)

    if text == "Occupied":
      if (raw_timestamp - lastUploaded).seconds >= MIN_UPLOAD_SECONDS:
        motionCounter += 1

        if motionCounter >= MIN_MOTION_FRAMES:
          if UPLOAD_ENABLED:
            upload_motion(ts, frame, raw_timestamp)

          lastUploaded = raw_timestamp
          motionCounter = 0

    else:
      motionCounter = 0

    RAW_CAPTURE.truncate(0)

def record_sequence():
  if not os.path.exists(out_path()):
    os.mkdir(out_path())

  max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
  write("Recording...")

  for output in CAMERA.record_sequence(
    stream_outputs(), quality=QUALITY, bitrate=BITRATE, format=STREAM_FORMAT
  ):
    while output.tell() < max_bytes:
      CAMERA.wait_recording(1)
      CAMERA.annotate_text = f"{today()} {now()}"
      if must_update():
        write("Time of day changed, reinitializing...")
        return init_camera(10)

    if output.tell() >= max_bytes:
      convert_stream(output.name)

def main():
  init_camera()

if __name__ == '__main__':
  main()
