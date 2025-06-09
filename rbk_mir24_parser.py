import os
import cv2
import pytesseract
import pandas as pd
import numpy as np
import logging
import re
import json
from datetime import datetime
import shutil
import asyncio
import subprocess

# Настройка логирования
logger = logging.getLogger(__name__)

# Папки
base_dir = "screenshots"
processed_dir = "screenshots_processed"

# Длительность записи видео (в секундах)
VIDEO_DURATION = 240  # 4 минуты
# Интервал извлечения кадров для распознавания текста (в секундах)
FRAME_INTERVAL = 10

# Загрузка ключевых слов из файла keywords.json
try:
    with open("keywords.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        keywords = data.get("keywords", [])
    logger.info(f"Ключевые слова успешно загружены: {keywords}")
except FileNotFoundError:
    logger.error("Файл keywords.json не найден")
    keywords = []
except Exception as e:
    logger.error(f"Ошибка при загрузке keywords.json: {e}")
    keywords = []


# Загрузка channels.json для получения URL и crop
async def load_channels():
    try:
        with open("channels.json", "r", encoding="utf-8") as f:
            channels_data = json.load(f)
        return channels_data
    except FileNotFoundError:
        logger.error("Файл channels.json не найден")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка формата JSON в channels.json: {e}")
        return {}


# Запись видеопотока
async def record_video(channel_name, channel_info):
    try:
        output_dir = os.path.join(base_dir, channel_name)
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = os.path.join(output_dir, f"{channel_name}_video_{timestamp}.mp4")

        # Команда FFmpeg для записи видео
        cmd = [
            "ffmpeg",
            "-i", channel_info["url"],
            "-t", str(VIDEO_DURATION),  # Длительность записи
            "-c:v", "libx264",  # Кодек видео
            "-c:a", "aac",  # Кодек аудио
            "-y"  # Перезаписывать файл, если существует
        ]

        # Добавляем обрезку, если указано
        if "crop" in channel_info:
            cmd.extend(["-vf", channel_info["crop"]])

        cmd.append(output_path)

        logger.info(f"Запуск записи видео для {channel_name}: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            error_msg = stderr.decode()
            logger.error(f"Ошибка ffmpeg при записи видео для {channel_name}: {error_msg}")
            return None, error_msg
        else:
            logger.info(f"Видео сохранено: {output_path}")
            return output_path, None
    except Exception as e:
        logger.error(f"Ошибка при записи видео для {channel_name}: {e}")
        return None, str(e)


# Предобработка кадра
def preprocess_frame(frame):
    try:
        if frame is None:
            logger.error("Не удалось загрузить кадр")
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.convertScaleAbs(gray, alpha=2.0, beta=10)
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 5
        )
        gray = cv2.fastNlMeansDenoising(gray, h=10)
        return gray
    except Exception as e:
        logger.error(f"Ошибка при обработке кадра: {e}")
        return None


# Распознавание текста из кадра
def recognize_text_from_frame(frame):
    try:
        processed_frame = preprocess_frame(frame)
        if processed_frame is None:
            return ""
        custom_config = r'--oem 3 --psm 6 -l rus+eng --dpi 600'
        text = pytesseract.image_to_string(processed_frame, config=custom_config)
        text = text.strip()
        logger.info(f"Распознанный текст: '{text}'")
        valid_text_pattern = re.compile(r'^[a-zA-Zа-яА-Я0-9,.!?\-\s:«»()]+$', re.UNICODE)
        meaningful_text_pattern = re.compile(r'[a-zA-Zа-яА-Я]{2,}')
        if text and valid_text_pattern.match(text) and meaningful_text_pattern.search(text):
            logger.info(f"Текст прошел фильтрацию: '{text}'")
            return text
        else:
            logger.warning(f"Текст не прошел фильтрацию: '{text}'")
            return text
    except Exception as e:
        logger.error(f"Ошибка при распознавании текста: {e}")
        return ""


# Проверка наличия ключевых слов
def has_keywords(text):
    text_lower = text.lower()
    result = any(keyword.lower() in text_lower for keyword in keywords)
    logger.info(f"Проверка ключевых слов для '{text}': {result}")
    return result


# Обработка видео: извлечение кадров и распознавание текста
def process_video(video_path, channel_name):
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видео: {video_path}")
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_interval = int(fps * FRAME_INTERVAL)  # Интервал кадров для анализа
        frame_count = 0
        results = []

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % frame_interval == 0:
                text = recognize_text_from_frame(frame)
                if text and has_keywords(text):
                    timestamp = datetime.now()
                    results.append((video_path, timestamp, os.path.basename(video_path), text))
            frame_count += 1
            # Позволяем другим задачам выполняться
            cv2.waitKey(1)

        cap.release()
        logger.info(f"Обработка видео {video_path} завершена: найдено {len(results)} текстов")
        return results
    except Exception as e:
        logger.error(f"Ошибка при обработке видео {video_path}: {e}")
        return []


async def process_rbk_mir24(app, ui, send_files):
    logger.info("Обработка видеопотоков РБК и МИР24")
    ui.status_label.config(text="Состояние: Обработка РБК и МИР24...")
    ui.rbk_mir24_button.config(state="disabled")
    ui.stop_rbk_mir24_button.config(state="normal")

    try:
        app.rbk_mir24_task = asyncio.current_task()  # Сохраняем текущую задачу
        data = {"Channel": [], "Timestamp": [], "Text": [], "Video": []}
        channels_data = await load_channels()
        channels = ["RBK", "MIR24"]

        if not channels_data:
            logger.error("Не удалось загрузить channels.json")
            ui.status_label.config(text="Состояние: Ошибка: channels.json не найден")
            return None, None

        os.makedirs(processed_dir, exist_ok=True)

        for channel_name in channels:
            if channel_name not in channels_data:
                logger.warning(f"Канал {channel_name} отсутствует в channels.json")
                continue

            channel_info = channels_data[channel_name]
            logger.info(f"Запись видео для канала: {channel_name}")

            # Записываем видео
            video_path, error_msg = await record_video(channel_name, channel_info)
            if not video_path:
                logger.error(f"Не удалось записать видео для {channel_name}: {error_msg}")
                continue

            # Обрабатываем видео
            results = process_video(video_path, channel_name)
            if not results:
                logger.warning(f"Нет распознанных текстов для {channel_name}")
                continue

            # Сохраняем результаты
            for video_path, timestamp, filename, text in results:
                data["Channel"].append(channel_name)
                data["Timestamp"].append(timestamp)
                data["Text"].append(text)
                data["Video"].append(filename)

                # Перемещаем видео в processed_dir
                dest_path = os.path.join(processed_dir, filename)
                if os.path.exists(video_path):
                    shutil.move(video_path, dest_path)
                    logger.info(f"Видео перемещено в {dest_path}")

                await asyncio.sleep(0)  # Позволяем отмену задачи

            await asyncio.sleep(0)  # Позволяем отмену задачи

        # Сохранение в CSV
        if data["Channel"]:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output_file = f"logs/recognized_text_rbk_mir24_{timestamp}.csv"
            df = pd.DataFrame(data)
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            logger.info(f"Результаты РБК и МИР24 сохранены в {output_file}")

            # Отправка файлов в Telegram
            await send_files(output_file, data["Video"])

            ui.status_label.config(text="Состояние: Сохранение РБК и МИР24 завершено")
            return output_file, data["Video"]
        else:
            logger.warning("Нет данных для сохранения")
            ui.status_label.config(text="Состояние: Нет данных для РБК и МИР24")
            return None, None

    except asyncio.CancelledError:
        logger.info("Парсинг РБК и МИР24 остановлен")
        ui.status_label.config(text="Состояние: Парсинг РБК и МИР24 остановлен")
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке РБК и МИР24: {e}")
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
        return None, None
    finally:
        ui.rbk_mir24_button.config(state="normal")
        ui.stop_rbk_mir24_button.config(state="disabled")
        app.rbk_mir24_task = None


async def stop_rbk_mir24(app, ui):
    logger.info("Остановка парсинга РБК и МИР24")
    if app.rbk_mir24_task and not app.rbk_mir24_task.done():
        app.rbk_mir24_task.cancel()
        try:
            await app.rbk_mir24_task
        except asyncio.CancelledError:
            logger.info("Задача парсинга РБК и МИР24 успешно отменена")
            ui.status_label.config(text="Состояние: Парсинг РБК и МИР24 остановлен")
        finally:
            ui.rbk_mir24_button.config(state="normal")
            ui.stop_rbk_mir24_button.config(state="disabled")
            app.rbk_mir24_task = None
    else:
        logger.warning("Нет активной задачи парсинга РБК и МИР24 для остановки")
        ui.status_label.config(text="Состояние: Нет активного парсинга РБК и МИР24")
        ui.rbk_mir24_button.config(state="normal")
        ui.stop_rbk_mir24_button.config(state="disabled")