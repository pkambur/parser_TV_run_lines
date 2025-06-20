import threading
import time
import os
import cv2
import schedule
import json
from datetime import datetime

CHANNELS_FILE = 'channels.json'
VIDEO_ROOT = 'TV_video'
RECORD_DURATION = 5 * 60  # 5 минут

# Загрузка каналов
with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
    CHANNELS = json.load(f)

def record_channel(channel, url, duration=RECORD_DURATION):
    os.makedirs(os.path.join(VIDEO_ROOT, channel), exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(VIDEO_ROOT, channel, f'{channel}_{timestamp}.mp4')
    cap = cv2.VideoCapture(url)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
    start_time = time.time()
    while time.time() - start_time < duration:
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)
    cap.release()
    out.release()


def schedule_recordings():
    for channel, info in CHANNELS.items():
        url = info.get('url')
        times = info.get('schedule', [])
        if not url or not times:
            continue
        for t in times:
            schedule.every().day.at(t).do(record_channel, channel, url)


def start_auto_recording():
    schedule_recordings()
    def run():
        while True:
            schedule.run_pending()
            time.sleep(1)
    thread = threading.Thread(target=run, daemon=True)
    thread.start() 