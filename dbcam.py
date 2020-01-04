#!/usr/bin/python3

import dropbox
import time
import itertools
import io
import os
import sys
import subprocess
import configparser
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
  if not NIGHT_ENABLED:
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

  record()

def outputs():
  for i in itertools.count(1):
    yield io.open(f"{out_path()}/stream{i}.{STREAM_FORMAT}", 'wb')

def convert(stream_file):
  write(f"Converting {stream_file} to {UPLOAD_FORMAT}...")

  try:
    p = subprocess.Popen([
      'ffmpeg',
      '-y',
      '-hide_banner',
      '-loglevel', 'panic',
      '-framerate', str(FRAMERATE),
      '-probesize', str(PROBE_SIZE),
      '-i', str(stream_file),
      '-c', 'copy', str(f"{stream_file}.{UPLOAD_FORMAT}"),
    ])
    p.wait()
  except Exception as e:
    return write(f"ffmpeg error: {e}")


  if UPLOAD_ENABLED:
    upload(stream_file)
  else:
    os.remove(stream_file)

def upload(stream_file):
  converted_file = f"{stream_file}.{UPLOAD_FORMAT}"

  with open(converted_file, 'rb') as f:
    try:
      DBX.files_upload(f.read(), f"/hc_{today()}/{now()}.{UPLOAD_FORMAT}")
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
      convert(output.name)

def main():
  init_camera()

if __name__ == '__main__':
  main()
