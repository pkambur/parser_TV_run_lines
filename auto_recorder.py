import threading
import time
import os
import cv2
import schedule
import json
from datetime import datetime
import subprocess
import urllib.request
import urllib.parse
import sys
from telegram_sender import send_files
import shlex
from utils import setup_logging

logger = setup_logging('auto_recorder_log.txt')

CHANNELS_FILE = 'channels.json'
VIDEO_ROOT = 'TV_video'
RECORD_DURATION = 10 * 60  # 10 минут
VIDEO_DIR = 'TV_video'
UI_STATUS_URL = "http://127.0.0.1:8989/status"

TARGET_CHANNELS = {"RBK", "MIR24", "RenTV", "NTV", "TVC"}

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

def extract_crop_video(full_video_path, crop_params, output_path):
    """Вырезает crop-видео из полного видео с помощью ffmpeg."""
    try:
        crop_str = crop_params.replace('crop=', '')
        width, height, x, y = crop_str.split(':')
        crop_filter = f"crop={width}:{height}:{x}:{y}"
        command = [
            'ffmpeg', '-y',
            '-i', str(full_video_path),
            '-filter:v', crop_filter,
            '-c:a', 'copy',
            str(output_path)
        ]
        subprocess.run(command, check=True)
        return True
    except Exception as e:
        logger.error(f"Ошибка при вырезке crop-видео: {e}")
        return False

def crop_video_has_keywords(crop_video_path, channel_name):
    """Проверяет crop-видео на наличие ключевых слов (использует video_processor.py --single)."""
    try:
        python_executable = sys.executable
        video_processor_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video_processor.py")
        # Запускаем video_processor.py с --single, но не отправляем в ТГ, а только анализируем результат
        # Для этого используем специальный флаг --check-keywords-only (добавим обработку в video_processor.py)
        result = subprocess.run([
            python_executable, video_processor_path, '--single', str(crop_video_path), channel_name, '--check-keywords-only'
        ], capture_output=True, text=True)
        # Ожидаем, что если ключевые слова найдены, в stdout будет строка FOUND_KEYWORDS
        return 'FOUND_KEYWORDS' in result.stdout
    except Exception as e:
        logger.error(f"Ошибка при анализе crop-видео на ключевые слова: {e}")
        return False

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
            # --- Новый блок: обработка crop-видео для целевых каналов ---
            try:
                # Проверяем, нужно ли делать crop
                if channel_name in TARGET_CHANNELS:
                    # Загружаем channels.json для получения crop и lines
                    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
                        channels = json.load(f)
                    info = channels.get(channel_name, {})
                    crop_params = info.get('crop')
                    lines_times = set(info.get('lines', []))
                    schedule_times = set(info.get('schedule', []))
                    # Получаем текущее время запуска (округляем до минут)
                    now_time = datetime.now().strftime('%H:%M')
                    # Если время есть и в lines, и в schedule — делаем crop
                    if now_time in lines_times and now_time in schedule_times and crop_params:
                        crop_video_path = os.path.join('temp_processing', f"{channel_name}_crop_{timestamp}.mp4")
                        if extract_crop_video(output_file, crop_params, crop_video_path):
                            # Проверяем на ключевые слова
                            if crop_video_has_keywords(crop_video_path, channel_name):
                                logger.info(f"Ключевые слова найдены в crop-видео {crop_video_path}, отправляем в Telegram")
                                send_files([crop_video_path], caption=f"Crop-видео {channel_name} {now_time}")
                            else:
                                logger.info(f"Ключевые слова не найдены в crop-видео {crop_video_path}, удаляем файл")
                            # Удаляем crop-видео в любом случае
                            try:
                                os.remove(crop_video_path)
                            except Exception as e:
                                logger.warning(f"Не удалось удалить crop-видео: {e}")
            except Exception as e:
                logger.error(f"Ошибка при post-processing crop-видео: {e}")
            # --- Конец блока ---
            # После этого запускаем обработку полного видео
            try:
                python_executable = sys.executable
                video_processor_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video_processor.py")
                logger.info(f"Запуск обработки видео {output_file} через video_processor.py")
                subprocess.Popen([
                    python_executable, video_processor_path, '--single', output_file, channel_name
                ])
            except Exception as e:
                logger.error(f"Ошибка при запуске video_processor.py для {output_file}: {e}")
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
    """Настройка расписания записи с учетом индивидуальных длительностей."""
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
        
        default_duration = info.get("default_duration", 10)  # fallback 10 минут
        special_durations = info.get("special_durations", {})

        for t in schedule_times:
            try:
                duration = special_durations.get(t, default_duration)
                duration_seconds = duration * 60
                schedule.every().day.at(t).do(start_recording, channel_name=name, url=url, duration_seconds=duration_seconds)
                logger.info(f"Запланирована запись для канала {name} в {t} на {duration} минут.")
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