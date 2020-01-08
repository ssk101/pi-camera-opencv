# dbcam

Records h264 streams from your Pi camera, converts and uploads to your Dropbox app folder.

You must create an app via the Dropbox dev console here, and generate a token:

https://www.dropbox.com/developers/apps


## Setup
```sh
pip3 install .
sudo apt install -y libhdf5-dev libhdf5-serial-dev libatlas-base-dev libjasper-dev libqtgui4 python3-pyqt5 libqt4-test

```