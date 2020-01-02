#!/usr/bin/python3

import dropbox
import time
import itertools
import io
import os
import sys
import subprocess
from picamera import PiCamera, Color
from datetime import datetime, time as datetime_time
from fractions import Fraction

MAX_FILE_SIZE_MB = 8
RESOLUTION = (1280, 720)
FRAMERATE = 15
ROTATION = 15
QUALITY = 25
BITRATE = 20000000
TEXT_SIZE = 16
TEXT_COLOR = '#fff'
PROBE_SIZE = '16M'
STREAM_FORMAT = 'h264'
UPLOAD_FORMAT = 'mp4'
DATE_FORMAT = '%Y-%m-%d'
TIME_FORMAT = '%H.%M.%S'
TIME_STATE = 'day'
ACCESS_TOKEN = os.environ.get('DB_ACCESS_TOKEN')
CAMERA = PiCamera()

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

def out_path():
  return f"{os.path.dirname(os.path.realpath(sys.argv[0]))}/output"

def is_day():
  now = datetime.now().time()
  return now < datetime_time(17, 00) and now >= datetime_time(9, 00)

def is_night():
  return
  now = datetime.now().time()
  return now >= datetime_time(17, 00) or now < datetime_time(9, 00)

def must_update():
  return (
    is_day() and TIME_STATE is not 'day' or
    is_night() and TIME_STATE is not 'night'
  )

def init_camera(delay=0):
  global CAMERA
  global TIME_STATE

  write(f"Initializing camera in {delay}s...")
  time.sleep(delay)
  write(f"Initializing camera...")

  if delay > 1:
    CAMERA.close()
    CAMERA = PiCamera()

  settings = {
    'rotation': ROTATION,
    'annotate_text_size': TEXT_SIZE,
    'annotate_foreground': Color(TEXT_COLOR),
    'resolution': RESOLUTION,
  }

  day = {
    'framerate': FRAMERATE,
    'shutter_speed': 0,
    'exposure_mode': 'auto',
    'iso': 0,
  }

  night = {
    'framerate': FRAMERATE,
    'shutter_speed': 0,
    'exposure_mode': 'auto',
    'iso': 0,
  }
  # night = {
  #   'framerate': Fraction(1, 6),
  #   'shutter_speed': 6000000,
  #   'exposure_mode': 'off',
  #   'iso': 800,
  # }

  if is_day():
    write("Assigning daytime settings.")
    settings = {**settings, **day}
    TIME_STATE = 'day'
  elif is_night():
    write("Assigning nighttime settings.")
    settings = {**settings, **night}
    TIME_STATE = 'night'

  for k, v in settings.items():
    setattr(CAMERA, k, v)

  record()

def outputs():
  for i in itertools.count(1):
    yield io.open(f"{out_path()}/stream{i}.{STREAM_FORMAT}", 'wb')

def upload(stream_file):
  converted_file = f"{stream_file}.{UPLOAD_FORMAT}"
  up_file = f"/hc_{today()}/{now()}.{UPLOAD_FORMAT}"

  write(f"Converting {stream_file} to {UPLOAD_FORMAT}...")

  try:
    p = subprocess.Popen([
      'ffmpeg',
      '-hide_banner',
      '-loglevel', 'panic',
      '-framerate', str(FRAMERATE),
      '-probesize', str(PROBE_SIZE),
      '-i', str(stream_file),
      '-c', 'copy', str(converted_file),
    ])
    p.wait()
  except Exception as e:
    return write(f"ffmpeg error: {e}")

  with open(converted_file, 'rb') as f:
    try:
      DBX.files_upload(f.read(), up_file)
    except Exception as e:
      write(f"Dropbox upload error: {e}")

  os.remove(stream_file)
  os.remove(converted_file)

  write(f"Uploaded {converted_file}.")

def record():
  if not os.path.exists(out_path()):
    os.mkdir(out_path())

  max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
  write("Recording...")

  for output in CAMERA.record_sequence(
    outputs(), quality=QUALITY, bitrate=BITRATE, format=STREAM_FORMAT
  ):
    while output.tell() < max_bytes:
      CAMERA.wait_recording(1)
      CAMERA.annotate_text = f"{today()} {now()}"
      if must_update():
        write("Time of day changed, reinitializing...")
        return init_camera(10)

    if output.tell() >= max_bytes:
      upload(output.name)

def main():
  init_camera()

if __name__ == '__main__':
  main()