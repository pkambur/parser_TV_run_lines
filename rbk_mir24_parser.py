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
from pathlib import Path
from config_manager import config_manager
import threading
from typing import Optional, List, Dict, Any
from tkinter import messagebox

from parser_lines import main as start_lines_monitoring, stop_subprocesses, start_force_capture, stop_force_capture, force_capture_event, stop_monitoring_event

logger = setup_logging('rbk_mir24_parser_log.txt')
base_dir = Path("video").resolve()  # Абсолютный путь для надежности
LINES_VIDEO_ROOT = Path("lines_video").resolve()  # Для crop-роликов
VIDEO_DURATION = 240  # 240 секунд

def get_current_time_str():
    """
    Возвращает текущее время в формате HH:MM.
    """
    return datetime.now().strftime("%H:%M")

def load_channels():
    """
    Загрузка конфигурации каналов через config_manager.
    """
    return config_manager.load_channels()

async def check_url_accessible(url):
    """
    Проверяет доступность URL (асинхронно).
    """
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: urllib.request.urlopen(url, timeout=5))
        logger.info(f"URL {url} доступен")
        return True
    except Exception as e:
        logger.error(f"URL {url} недоступен: {e}")
        return False

async def check_video_resolution(url):
    """
    Получает разрешение видео по URL с помощью ffprobe (асинхронно).
    """
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
        
        # Ищем первый поток с разрешением
        width, height = None, None
        for stream in data.get("streams", []):
            if "width" in stream and "height" in stream:
                width = stream.get("width")
                height = stream.get("height")
                break
        
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
    """
    Валидирует параметры crop для канала с учетом разрешения видео.
    """
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

async def record_video_opencv(channel_name, stream_url, output_path, crop_params, duration):
    """
    Запись видео с использованием OpenCV.
    """
    try:
        cap = cv2.VideoCapture(stream_url)
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видеопоток для {channel_name}: {stream_url}")
            return
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if crop_params:
            try:
                crop_str = crop_params.replace("crop=", "")
                crop_width, crop_height, x, y = map(int, crop_str.split(":"))
                width, height = crop_width, crop_height
            except Exception as e:
                logger.error(f"Ошибка при парсинге crop для {channel_name}: {e}")
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
            if stop_monitoring_event.is_set():
                logger.info(f"Остановка записи видео для {channel_name} по флагу stop_monitoring_event")
                break
            if asyncio.get_event_loop().time() - start_time >= duration:
                break
            ret, frame = cap.read()
            if not ret or frame is None:
                logger.warning(f"Не удалось прочитать кадр {frame_count} для {channel_name}")
                break
            if crop_params:
                try:
                    crop_str = crop_params.replace("crop=", "")
                    crop_width, crop_height, x, y = map(int, crop_str.split(":"))
                    frame = frame[y:y+crop_height, x:x+crop_width]
                except Exception as e:
                    logger.error(f"Ошибка при применении crop для кадра {frame_count} в {channel_name}: {e}")
            out.write(frame)
            frame_count += 1
            await asyncio.sleep(0.001)
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

async def record_lines_video(channel_name, channel_info, duration=VIDEO_DURATION):
    """
    Записывает crop-ролик в lines_video/<channel>/.
    """
    try:
        if not LINES_VIDEO_ROOT.exists():
            try:
                LINES_VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
                logger.info(f"Создана корневая директория lines_video: {LINES_VIDEO_ROOT}")
            except Exception as e:
                logger.error(f"Ошибка при создании корневой директории lines_video: {e}")
                return
        output_dir = LINES_VIDEO_ROOT / channel_name
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Создана директория для канала {channel_name}: {output_dir}")
        except Exception as e:
            logger.error(f"Ошибка при создании директории для канала {channel_name}: {e}")
            return
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = output_dir / f"{channel_name}_lines_{timestamp}.mp4"
        if not await check_url_accessible(channel_info["url"]):
            logger.error(f"Прерывание записи для {channel_name}: URL недоступен")
            return
        resolution = await check_video_resolution(channel_info["url"])
        crop_filter = await validate_crop_params(channel_name, channel_info, resolution)
        if stop_monitoring_event.is_set():
            logger.info(f"Остановка записи crop-видео для {channel_name} по флагу stop_monitoring_event")
            return
        await record_video_opencv(channel_name, channel_info["url"], output_path, crop_filter, duration)
        logger.info(f"Crop-видео для {channel_name} сохранено: {output_path}")
    except Exception as e:
        logger.error(f"Ошибка при записи crop-видео для {channel_name}: {e}")

async def process_rbk_mir24(app, ui, send_files=False, channels=None, force_crop=False):
    """
    Основная корутина для записи crop-видео RBK и MIR24, распознавания и отправки.
    """
    logger.info("Запуск записи crop-видео (с учётом lines)")
    if ui.root.winfo_exists():
        ui.update_status("Запуск записи crop-видео...")
        ui.update_rbk_mir24_status("Запущен")
    process_list = app.process_list
    record_tasks = []
    recorded_videos = []
    try:
        channels_data = load_channels()
        if not channels_data:
            logger.error("Не удалось загрузить channels.json, запись невозможна")
            if ui.root.winfo_exists():
                ui.update_status("Ошибка: Не удалось загрузить channels.json")
                ui.update_rbk_mir24_status("Ошибка")
            return
        video_channels = ['RBK', 'MIR24', 'RenTV', 'NTV', 'TVC']
        if channels is None:
            channels = video_channels
        else:
            channels = [ch for ch in channels if ch in video_channels]
            if not channels:
                logger.warning("Нет каналов для записи видео")
                if ui.root.winfo_exists():
                    ui.update_status("Нет каналов для записи видео")
                    ui.update_rbk_mir24_status("Ошибка")
                return
        now_str = get_current_time_str()
        logger.info(f"Текущее время: {now_str}")
        for name in channels:
            if stop_monitoring_event.is_set():
                logger.info(f"Остановка записи crop-видео по флагу stop_monitoring_event (канал {name})")
                break
            if name not in channels_data:
                logger.warning(f"Канал {name} отсутствует в channels.json")
                if ui.root.winfo_exists():
                    ui.update_status(f"Ошибка: Канал {name} отсутствует в channels.json")
                    ui.update_rbk_mir24_status("Ошибка")
                continue
            info = channels_data[name]
            lines_times = set(info.get("lines", []))
            if force_crop:
                logger.info(f"{name}: ручной запуск — запись crop-ролика (lines_video)")
                task = asyncio.create_task(record_lines_video(name, info, VIDEO_DURATION))
                record_tasks.append(task)
                recorded_videos.append({"channel": name, "type": "crop"})
            else:
                if now_str in lines_times:
                    logger.info(f"{name}: {now_str} найдено в lines — запись crop-ролика (lines_video)")
                    task = asyncio.create_task(record_lines_video(name, info, VIDEO_DURATION))
                    record_tasks.append(task)
                    recorded_videos.append({"channel": name, "type": "crop"})
                else:
                    logger.info(f"{name}: {now_str} не найдено в lines — пропуск")
        if record_tasks:
            done, pending = await asyncio.wait(record_tasks, return_exceptions=True)
            for task in done:
                if isinstance(task, Exception):
                    logger.error(f"Задача записи завершилась с ошибкой: {task}")
                elif hasattr(task, 'exception') and task.exception():
                    logger.error(f"Задача записи завершилась с ошибкой: {task.exception()}")
        if recorded_videos and hasattr(app, "check_and_send_videos"):
            logger.info(f"Запись завершена, найдено {len(recorded_videos)} crop-видео для обработки")
            def run_check_and_send():
                try:
                    app.check_and_send_videos()
                except Exception as e:
                    logger.error(f"Ошибка при запуске распознавания и отправки видео: {e}")
            if hasattr(app, "ui") and hasattr(app.ui, "root"):
                app.ui.root.after(0, run_check_and_send)
            else:
                run_check_and_send()
        elif recorded_videos:
            logger.info(f"Запись завершена, но функция check_and_send_videos недоступна. Записанные видео: {recorded_videos}")
        else:
            logger.info("Запись завершена, crop-видео для обработки не найдено")
        if ui.root.winfo_exists():
            ui.update_status("Запись crop-видео завершена")
            ui.update_rbk_mir24_status("Остановлен")
        logger.info("Запись crop-видео завершена")
    except asyncio.CancelledError:
        logger.info("Отмена всех задач записи")
        for task in record_tasks:
            task.cancel()
        await asyncio.gather(*record_tasks, return_exceptions=True)
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
    """
    Остановка записи RBK и MIR24.
    """
    logger.info("Остановка записи РБК и МИР24")
    if ui.root.winfo_exists():
        ui.update_status("Остановка записи РБК и МИР24...")
    
    # Проверяем, есть ли менеджер и активная задача
    if hasattr(app, 'rbk_mir24_manager') and app.rbk_mir24_manager.is_recording():
        if hasattr(app.rbk_mir24_manager, "rbk_mir24_task") and not app.rbk_mir24_manager.rbk_mir24_task.done():
            app.rbk_mir24_manager.rbk_mir24_task.cancel()
            try:
                await app.rbk_mir24_manager.rbk_mir24_task
            except asyncio.CancelledError:
                logger.info("Задача записи успешно отменена")
            app.rbk_mir24_manager.rbk_mir24_running = False
            if ui.root.winfo_exists():
                ui.update_status("Запись РБК и МИР24 остановлена")
                ui.update_rbk_mir24_status("Остановлен")
        else:
            if ui.root.winfo_exists():
                ui.update_status("Нет активной записи РБК и МИР24")
                ui.update_rbk_mir24_status("Остановлен")
    else:
        if ui.root.winfo_exists():
            ui.update_status("Нет активной записи РБК и МИР24")
            ui.update_rbk_mir24_status("Остановлен")

class RBKMIR24Manager:
    """
    Менеджер для управления записью и мониторингом каналов RBK и MIR24.
    """
    
    def __init__(self, app, ui):
        """
        Инициализация менеджера RBK/MIR24.
        """
        self.app = app
        self.ui = ui
        self.recording_channels = []
        self.lines_monitoring_thread = None
        self.lines_monitoring_running = False
        self.rbk_mir24_task = None
        self.rbk_mir24_running = False
    
    def start_manual_recording(self, channels: Optional[List[str]] = None) -> bool:
        """
        Запуск ручной записи crop-видео для RBK и MIR24.

        Args:
            channels: Список каналов для записи. Если None, используются все доступные.
        Returns:
            bool: True если запись запущена успешно, False иначе.
        """
        try:
            from rbk_mir24_parser import get_current_time_str, process_rbk_mir24
            
            now_str = get_current_time_str()
            channels_data = config_manager.load_channels()
            video_channels = ['RBK', 'MIR24', 'RenTV', 'NTV', 'TVC']
            
            # Проверяем, не запущена ли уже запись на каналах с бегущими строками
            channels_in_lines = []
            for name in video_channels:
                info = channels_data.get(name)
                if not info:
                    continue
                lines_times = set(info.get("lines", []))
                if now_str in lines_times:
                    channels_in_lines.append(name)
            
            if channels_in_lines:
                messagebox.showwarning(
                    "Бегущие строки",
                    f"Бегущие строки уже записываются на канале(ах): {', '.join(channels_in_lines)}"
                )
                return False
            
            # Если нет совпадений с lines, запускаем crop-запись
            if channels is None:
                channels = video_channels
            else:
                channels = [ch for ch in channels if ch in video_channels]
                if not channels:
                    logger.warning("Нет каналов для записи видео")
                    self.ui.update_status("Нет каналов для записи видео")
                    return False
            
            self.recording_channels.clear()
            self.recording_channels.extend(channels)
            
            for channel in channels:
                self.ui.update_recording_status(channel, True)
            
            self.app.process_list.clear()
            self.ui.update_status("Запуск записи RBK и MIR24 (crop)...")
            
            self.rbk_mir24_task = asyncio.run_coroutine_threadsafe(
                process_rbk_mir24(self.app, self.ui, True, channels=channels, force_crop=True),
                self.app.loop
            )
            
            self.rbk_mir24_running = True
            self.ui.update_rbk_mir24_status("Запущен")
            logger.info("Запущен мониторинг RBK и MIR24 (crop)")
            return True
            
        except Exception as e:
            self.ui.update_rbk_mir24_status("Ошибка")
            self.ui.update_status(f"Ошибка запуска записи: {str(e)}")
            logger.error(f"Ошибка при запуске записи RBK и MIR24: {e}")
            messagebox.showerror("Ошибка", f"Не удалось запустить запись: {str(e)}")
            return False
    
    def stop_recording(self) -> bool:
        """
        Остановка записи RBK и MIR24.
        Returns:
            bool: True если запись остановлена успешно, False иначе.
        """
        if not self.rbk_mir24_running or self.app.loop is None:
            messagebox.showwarning("Предупреждение", "Мониторинг RBK и MIR24 уже остановлен или event loop не инициализирован")
            return False
        
        try:
            for channel in self.recording_channels:
                self.ui.update_recording_status(channel, False)
            
            self.recording_channels.clear()
            self.rbk_mir24_running = False
            self.ui.update_status("Остановка записи RBK и MIR24...")
            
            # Останавливаем задачу
            asyncio.run_coroutine_threadsafe(
                stop_rbk_mir24(self.app, self.ui),
                self.app.loop
            )
            
            self.ui.update_rbk_mir24_status("Остановлен")
            logger.info("Остановлен мониторинг RBK и MIR24")
            return True
            
        except Exception as e:
            self.ui.update_status(f"Ошибка остановки записи: {str(e)}")
            logger.error(f"Ошибка при остановке записи RBK и MIR24: {e}")
            messagebox.showerror("Ошибка", f"Не удалось остановить запись: {str(e)}")
            return False
    
    def start_scheduled_crop_recording(self, channels: Optional[List[str]] = None) -> None:
        """
        Запуск записи crop-видео для RBK и MIR24 по расписанию.
        Args:
            channels: Список каналов для записи. Если None, используются RBK и MIR24.
        """
        def run_and_process():
            try:
                if channels is None:
                    video_channels = ['RBK', 'MIR24']
                else:
                    video_channels = channels
                
                future = asyncio.run_coroutine_threadsafe(
                    process_rbk_mir24(self.app, self.ui, True, channels=video_channels, force_crop=False),
                    self.app.loop
                )
                
                self.ui.update_rbk_mir24_status("Запущен (по расписанию)")
                logger.info("Запущена запись crop-видео для RBK и MIR24 по расписанию")
                
                # Дождаться завершения записи
                future.result()
                logger.info("Запись crop-видео для RBK и MIR24 завершена, запускается распознавание и отправка видео...")
                
                # Запускать обработку и отправку видео потокобезопасно для UI
                if hasattr(self.app, "ui") and hasattr(self.app.ui, "root"):
                    self.app.ui.root.after(0, self.app.check_and_send_videos)
                else:
                    self.app.check_and_send_videos()
                    
            except Exception as e:
                logger.error(f"Ошибка при запуске записи crop-видео по расписанию: {e}")
                self.ui.update_rbk_mir24_status("Ошибка")
        
        threading.Thread(target=run_and_process, daemon=True).start()
    
    def start_scheduled_lines_monitoring(self, channels: Optional[List[str]] = None) -> None:
        """
        Запуск мониторинга строк (скриншотов) для RBK и MIR24 по расписанию.
        Args:
            channels: Список каналов для мониторинга. Если None, используются RBK и MIR24.
        """
        def run_and_process():
            try:
                channel_names = ', '.join(channels) if channels else "RBK+MIR24"
                self.ui.update_status(f"Запуск мониторинга строк для {channel_names} по расписанию...")
                
                self.lines_monitoring_running = True
                start_force_capture()
                
                thread = threading.Thread(target=start_lines_monitoring, daemon=True)
                thread.start()
                self.lines_monitoring_thread = thread
                
                self.ui.update_lines_status(f"Запущен ({channel_names})")
                logger.info(f"Запущен мониторинг строк для {channel_names} по расписанию")
                
                # Таймер для автоматической остановки
                timer = threading.Timer(VIDEO_DURATION, self.stop_lines_monitoring)
                timer.start()
                
                thread.join()
                timer.cancel()
                
                logger.info(f"Мониторинг строк для {channel_names} завершён, запускается обработка скриншотов...")
                self.app.save_and_send_lines()
                
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга строк для {channels}: {e}")
                self.ui.update_status(f"Ошибка запуска мониторинга {channels}: {e}")
                messagebox.showerror("Ошибка", f"Не удалось запустить мониторинг {channels}: {e}")
        
        threading.Thread(target=run_and_process, daemon=True).start()
    
    def start_lines_monitoring(self) -> bool:
        """
        Запуск мониторинга строк по кнопке.
        Returns:
            bool: True если мониторинг запущен успешно, False иначе.
        """
        if self.lines_monitoring_running:
            logger.warning("Мониторинг уже запущен")
            messagebox.showwarning("Предупреждение", "Мониторинг строк уже запущен")
            return False
        
        try:
            self.lines_monitoring_running = True
            self.app.last_lines_activity_time = datetime.now().timestamp()
            start_force_capture()
            
            self.lines_monitoring_thread = threading.Thread(
                target=start_lines_monitoring,
                daemon=True
            )
            self.lines_monitoring_thread.start()
            
            self.ui.update_lines_status("Запущен")
            logger.info("Запущен мониторинг строк по кнопке")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при запуске мониторинга по кнопке: {e}")
            self.lines_monitoring_running = False
            messagebox.showerror("Ошибка", f"Не удалось запустить мониторинг: {e}")
            return False
    
    def stop_lines_monitoring(self) -> bool:
        """
        Остановка мониторинга строк.
        Returns:
            bool: True если мониторинг остановлен успешно, False иначе.
        """
        if not self.lines_monitoring_running:
            messagebox.showwarning("Предупреждение", "Мониторинг строк уже остановлен")
            return False
        
        try:
            self.lines_monitoring_running = False
            stop_force_capture()
            stop_subprocesses()
            
            if self.lines_monitoring_thread and self.lines_monitoring_thread.is_alive():
                self.lines_monitoring_thread.join(timeout=5.0)
            
            if hasattr(self.app, 'check_files_thread') and self.app.check_files_thread.is_alive():
                self.app.check_files_thread.join(timeout=5.0)
            
            self.lines_monitoring_thread = None
            self.ui.update_lines_status("Остановлен")
            logger.info("Остановлен мониторинг строк")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при остановке мониторинга строк: {e}")
            return False
    
    def cleanup(self) -> None:
        """
        Очистка ресурсов менеджера.
        """
        try:
            # Останавливаем мониторинг строк
            if self.lines_monitoring_running:
                stop_force_capture()
                self.lines_monitoring_running = False
                logger.info("Мониторинг строк остановлен")
            
            # Останавливаем RBK и MIR24
            if self.rbk_mir24_running:
                stop_rbk_mir24(self.app, self.ui)
                self.rbk_mir24_running = False
                logger.info("RBK и MIR24 остановлены")
                
        except Exception as e:
            logger.error(f"Ошибка при очистке ресурсов RBKMIR24Manager: {e}")
    
    def is_recording(self) -> bool:
        """
        Проверяет, запущена ли запись.
        Returns:
            bool: True если запись активна, иначе False.
        """
        return self.rbk_mir24_running
    
    def is_lines_monitoring(self) -> bool:
        """
        Проверяет, запущен ли мониторинг строк.
        Returns:
            bool: True если мониторинг активен, иначе False.
        """
        return self.lines_monitoring_running