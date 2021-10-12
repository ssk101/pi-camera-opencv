from setuptools import setup

setup(
  name='dbcam',
  version='0.1',
  description='Record and upload video streams or frames captured via motion detection with Pi Camera.',
  author='ssk101',
  author_email='steelskysoftware@gmail.com',
  packages=['dbcam'],
  install_requires=[
    'imutils',
    'opencv-contrib-python==4.1.1.26',
    'pyautogui',
  ]
)