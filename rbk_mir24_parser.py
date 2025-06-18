import os
import logging
import json
import asyncio
import subprocess
import urllib.request
from datetime import datetime
import cv2
import numpy as np
from utils import setup_logging

logger = logging.getLogger(__name__)
base_dir = os.path.abspath("video")  # Абсолютный путь для надежности
VIDEO_DURATION = 120  # Для тестов 20 секунд, для продакшена можно увеличить до 240

def load_channels():
    try:
        logger.info("Начало загрузки channels.json")
        if not os.path.exists("channels.json"):
            logger.error("Файл channels.json не найден")
            return {}
        with open("channels.json", "r", encoding="utf-8") as f:
            channels = json.load(f)
            logger.info(f"Содержимое channels.json: {json.dumps(channels, indent=2)}")
            return channels
    except Exception as e:
        logger.error(f"Ошибка при загрузке channels.json: {e}")
        return {}

async def check_url_accessible(url):
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: urllib.request.urlopen(url, timeout=5))
        logger.info(f"URL {url} доступен")
        return True
    except Exception as e:
        logger.error(f"URL {url} недоступен: {e}")
        return False

async def check_video_resolution(url):
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=width,height",
            "-of", "json",
            url
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"Ошибка ffprobe для {url}: {stderr.decode()}")
            return None
        data = json.loads(stdout.decode())
        stream = data.get("streams", [{}])[0]
        width = stream.get("width")
        height = stream.get("height")
        if width is None or height is None:
            logger.warning(f"Разрешение видео для {url} не определено: {data}")
            return None
        resolution = (width, height)
        logger.info(f"Разрешение видео {url}: {resolution}")
        return resolution
    except Exception as e:
        logger.error(f"Ошибка при проверке разрешения {url}: {e}")
        return None

async def validate_crop_params(channel_name, channel_info, resolution):
    crop = channel_info.get("crop", "")
    if not crop:
        logger.warning(f"Фильтр crop не указан для {channel_name}")
        return ""

    try:
        # Убедимся, что формат начинается с crop=
        crop_str = crop.replace("crop=", "")
        width, height, x, y = map(int, crop_str.split(":"))

        if width <= 0 or height <= 0 or x < 0 or y < 0:
            logger.error(f"Недействительные параметры crop для {channel_name}: {crop}")
            return ""

        if resolution is None:
            logger.warning(f"Разрешение видео для {channel_name} не определено, используется crop без проверки: {crop}")
            return f"crop={width}:{height}:{x}:{y}"

        vid_width, vid_height = resolution
        if x + width > vid_width or y + height > vid_height:
            logger.warning(f"Параметры crop для {channel_name} ({crop}) превышают разрешение видео {resolution}. Используется максимальная область.")
            return f"crop={vid_width}:{vid_height}:0:0"

        return f"crop={width}:{height}:{x}:{y}"

    except Exception as e:
        logger.error(f"Ошибка валидации crop для {channel_name}: {e}")
        return ""

async def record_video(channel_name, channel_info, process_list):
    try:
        logger.info(f"Подготовка записи для {channel_name}")
        output_dir = os.path.join(base_dir, channel_name)
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = os.path.join(output_dir, f"{channel_name}_video_{timestamp}.mp4")

        # Проверка доступности URL
        if not await check_url_accessible(channel_info["url"]):
            logger.error(f"Прерывание записи для {channel_name}: URL недоступен")
            return

        # Проверка разрешения видео
        resolution = await check_video_resolution(channel_info["url"])
        crop_filter = await validate_crop_params(channel_name, channel_info, resolution)

        # Создаем задачу для записи видео
        task = asyncio.create_task(
            record_video_opencv(channel_name, channel_info["url"], output_path, crop_filter, VIDEO_DURATION)
        )
        process_list.append(task)

        try:
            await asyncio.wait_for(task, timeout=VIDEO_DURATION + 30)
            if os.path.exists(output_path):
                logger.info(f"Видео сохранено: {output_path}")
            else:
                logger.warning(f"Файл не был создан: {output_path}")
        except asyncio.TimeoutError:
            logger.error(f"Запись видео timed out для {channel_name}")
            task.cancel()
        except asyncio.CancelledError:
            logger.info(f"Запись видео для {channel_name} отменена")
            task.cancel()
            raise
        finally:
            if task in process_list:
                process_list.remove(task)
    except Exception as e:
        logger.error(f"Ошибка при записи {channel_name}: {e}")

async def record_video_opencv(channel_name, stream_url, output_path, crop_params, duration):
    """Запись видео с использованием OpenCV."""
    try:
        # Открываем видеопоток
        cap = cv2.VideoCapture(stream_url)
        
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видеопоток для {channel_name}: {stream_url}")
            return
        
        # Получаем параметры исходного видео
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 25.0  # Значение по умолчанию
        
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Применяем crop если указан
        if crop_params:
            try:
                crop_str = crop_params.replace("crop=", "")
                crop_width, crop_height, x, y = map(int, crop_str.split(":"))
                width, height = crop_width, crop_height
            except Exception as e:
                logger.error(f"Ошибка при парсинге crop для {channel_name}: {e}")
        
        # Создаем VideoWriter
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        if not out.isOpened():
            logger.error(f"Не удалось создать VideoWriter для {channel_name}")
            cap.release()
            return
        
        start_time = asyncio.get_event_loop().time()
        frame_count = 0
        
        logger.info(f"Начало записи видео для {channel_name}")
        
        while True:
            # Проверяем время записи
            if asyncio.get_event_loop().time() - start_time >= duration:
                break
            
            # Читаем кадр
            ret, frame = cap.read()
            
            if not ret or frame is None:
                logger.warning(f"Не удалось прочитать кадр {frame_count} для {channel_name}")
                break
            
            # Применяем crop если указан
            if crop_params:
                try:
                    crop_str = crop_params.replace("crop=", "")
                    crop_width, crop_height, x, y = map(int, crop_str.split(":"))
                    frame = frame[y:y+crop_height, x:x+crop_width]
                except Exception as e:
                    logger.error(f"Ошибка при применении crop для кадра {frame_count} в {channel_name}: {e}")
            
            # Записываем кадр
            out.write(frame)
            frame_count += 1
            
            # Небольшая пауза для предотвращения блокировки
            await asyncio.sleep(0.001)
        
        # Освобождаем ресурсы
        cap.release()
        out.release()
        
        logger.info(f"Запись завершена для {channel_name}: {frame_count} кадров")
        
    except Exception as e:
        logger.error(f"Ошибка при записи видео для {channel_name}: {e}")
        try:
            cap.release()
            out.release()
        except:
            pass

async def process_rbk_mir24(app, ui, send_files=False, channels=None):
    logger.info("Запуск записи видеопотоков")
    if ui.root.winfo_exists():
        ui.update_status("Запуск записи...")
        ui.update_rbk_mir24_status("Запущен")

    process_list = app.process_list
    record_tasks = []

    try:
        channels_data = load_channels()
        if not channels_data:
            logger.error("Не удалось загрузить channels.json, запись невозможна")
            if ui.root.winfo_exists():
                ui.update_status("Ошибка: Не удалось загрузить channels.json")
                ui.update_rbk_mir24_status("Ошибка")
            return

        # Список каналов для видео
        video_channels = ['RBK', 'MIR24', 'RenTV', 'NTV', 'TVC']

        # Если каналы не указаны, используем все каналы для видео
        if channels is None:
            channels = video_channels
        else:
            # Фильтруем только каналы для видео
            channels = [ch for ch in channels if ch in video_channels]
            if not channels:
                logger.warning("Нет каналов для записи видео")
                if ui.root.winfo_exists():
                    ui.update_status("Нет каналов для записи видео")
                    ui.update_rbk_mir24_status("Ошибка")
                return
        
        for name in channels:
            if name in channels_data:
                logger.info(f"Создание задачи для {name}")
                task = asyncio.create_task(record_video(name, channels_data[name], process_list))
                record_tasks.append(task)
            else:
                logger.warning(f"Канал {name} отсутствует в channels.json")
                if ui.root.winfo_exists():
                    ui.update_status(f"Ошибка: Канал {name} отсутствует в channels.json")
                    ui.update_rbk_mir24_status("Ошибка")

        # Проверяем выполнение задач
        done, pending = await asyncio.wait(record_tasks, return_exceptions=True)
        for task in done:
            if task.exception():
                logger.error(f"Задача записи завершилась с ошибкой: {task.exception()}")

        if ui.root.winfo_exists():
            ui.update_status("Запись завершена")
            ui.update_rbk_mir24_status("Остановлен")
        logger.info("Запись видеопотоков завершена")

    except asyncio.CancelledError:
        logger.info("Отмена всех задач записи")
        for task in record_tasks:
            task.cancel()
        await asyncio.gather(*record_tasks, return_exceptions=True)

        for proc in process_list:
            proc.kill()
            await proc.wait()

        process_list.clear()
        if ui.root.winfo_exists():
            ui.update_status("Запись остановлена")
            ui.update_rbk_mir24_status("Остановлен")
        raise

    except Exception as e:
        logger.error(f"Ошибка в process_rbk_mir24: {e}")
        if ui.root.winfo_exists():
            ui.update_status(f"Ошибка записи: {str(e)}")
            ui.update_rbk_mir24_status("Ошибка")

async def stop_rbk_mir24(app, ui):
    logger.info("Остановка записи РБК и МИР24")
    if ui.root.winfo_exists():
        ui.update_status("Остановка записи РБК и МИР24...")
    if hasattr(app, "rbk_mir24_task") and not app.rbk_mir24_task.done():
        app.rbk_mir24_task.cancel()
        try:
            await app.rbk_mir24_task
        except asyncio.CancelledError:
            logger.info("Задача записи успешно отменена")
        if ui.root.winfo_exists():
            ui.update_status("Запись РБК и МИР24 остановлена")
            ui.update_rbk_mir24_status("Остановлен")
    else:
        if ui.root.winfo_exists():
            ui.update_status("Нет активной записи РБК и МИР24")
            ui.update_rbk_mir24_status("Остановлен")