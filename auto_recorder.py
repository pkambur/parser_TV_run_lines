import threading
import time
import os
import cv2
import schedule
import json
from datetime import datetime
import subprocess
import logging
import urllib.request
import urllib.parse

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CHANNELS_FILE = 'channels.json'
VIDEO_ROOT = 'TV_video'
RECORD_DURATION = 10 * 60  # 10 минут
VIDEO_DIR = 'TV_video'
UI_STATUS_URL = "http://127.0.0.1:8989/status"

# Загрузка каналов
with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
    CHANNELS = json.load(f)

def update_ui_status(message):
    """Отправляет статус в основной UI."""
    try:
        data = urllib.parse.urlencode({'status': message}).encode('utf-8')
        req = urllib.request.Request(UI_STATUS_URL, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.status != 200:
                logger.warning(f"Не удалось обновить статус в UI: {response.status}")
    except Exception as e:
        logger.warning(f"Не удалось подключиться к UI для обновления статуса: {e}")

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

def start_recording(channel_name, url, duration_seconds):
    """Запускает запись видео с помощью ffmpeg."""
    if not url:
        logger.warning(f"URL для канала {channel_name} не указан. Пропуск записи.")
        return

    # Создаем директорию для канала, если она не существует
    channel_dir = os.path.join(VIDEO_DIR, channel_name)
    os.makedirs(channel_dir, exist_ok=True)

    # Имя файла на основе текущей даты и времени
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    output_file = os.path.join(channel_dir, f"{timestamp}.mp4")

    logger.info(f"Начало записи канала {channel_name} в файл {output_file} на {duration_seconds} секунд.")
    update_ui_status(f"Запись: {channel_name}")

    command = [
        'ffmpeg', '-y',
        '-i', url,
        '-t', str(duration_seconds),
        '-c', 'copy',
        '-bsf:a', 'aac_adtstoasc',
        output_file
    ]

    try:
        # Запускаем ffmpeg
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            logger.info(f"Запись канала {channel_name} успешно завершена.")
        else:
            logger.error(f"Ошибка при записи канала {channel_name}: {stderr.decode('utf-8', errors='ignore')}")
    except FileNotFoundError:
        logger.error("ffmpeg не найден. Убедитесь, что он установлен и доступен в системном PATH.")
    except Exception as e:
        logger.error(f"Произошла ошибка при записи {channel_name}: {e}")
    finally:
        update_ui_status("Ожидание")

def schedule_recordings():
    for channel, info in CHANNELS.items():
        url = info.get('url')
        times = info.get('schedule', [])
        if not url or not times:
            continue
        for t in times:
            schedule.every().day.at(t).do(start_recording, channel_name=channel, url=url, duration_seconds=RECORD_DURATION)

def setup_schedule():
    """Настройка расписания записи."""
    channels = CHANNELS
    if not channels:
        logger.warning("Нет каналов для настройки расписания.")
        return

    schedule.clear()

    for name, info in channels.items():
        schedule_times = info.get("schedule", [])
        if not schedule_times:
            continue

        url = info.get("url")
        if not url:
            logger.warning(f"Нет URL для канала {name}, пропуск расписания.")
            continue
        
        # Примерная длительность. Можно сделать настраиваемой.
        duration_minutes = 20 
        duration_seconds = duration_minutes * 60

        for t in schedule_times:
            try:
                schedule.every().day.at(t).do(start_recording, channel_name=name, url=url, duration_seconds=duration_seconds)
                logger.info(f"Запланирована запись для канала {name} в {t} на {duration_minutes} минут.")
            except Exception as e:
                logger.error(f"Неверный формат времени '{t}' для канала {name}: {e}")

def start_auto_recording():
    schedule_recordings()
    def run():
        while True:
            schedule.run_pending()
            time.sleep(1)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

def main():
    """Основная функция."""
    logger.info("Запуск автоматического рекордера...")
    update_ui_status("Активен")
    setup_schedule()
    logger.info("Расписание настроено. Ожидание задач...")
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main() 