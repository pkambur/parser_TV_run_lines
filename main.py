import logging
import threading
import asyncio
import tkinter as tk
from tkinter import ttk, messagebox
import os
import csv
from datetime import datetime, time, timedelta
import schedule
import time as time_module
import sys
import json
from pathlib import Path
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
import cv2
from typing import List
import numpy as np
import re
import pytesseract
from difflib import SequenceMatcher
import requests
from glob import glob
import psutil

from UI import MonitoringUI
from rbk_mir24_parser import VIDEO_DURATION, RBKMIR24Manager
from utils import setup_logging
from lines_to_csv import process_screenshots, get_daily_file_path
from telegram_sender import send_files, send_report_files
from config_manager import config_manager

# Инициализация логирования
logger = setup_logging()

def get_logs_dir():
    """Получение пути к директории logs относительно исполняемого файла."""
    if getattr(sys, 'frozen', False):
        # Если это исполняемый файл (PyInstaller)
        base_path = os.path.dirname(sys.executable)
    else:
        # Если это скрипт Python
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    logs_dir = os.path.join(base_path, 'logs')
    # Создаем директорию logs, если она не существует
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir

class MonitoringApp:
    """
    Основной класс приложения для мониторинга и обработки бегущих строк с телеканалов.
    Управляет UI, планировщиком, обработкой скриншотов и видео, отправкой в Telegram.
    """
    def __init__(self):
        """
        Инициализация приложения, запуск потоков, UI, менеджера RBK/MIR24 и кэша.
        """
        self.logger = logger
        self.loop = None
        self.thread = None
        self.running = False
        self.scheduler_thread = None
        self.scheduler_running = False
        self.scheduler_paused = False
        self.start_time = time_module.time()
        self.last_lines_activity_time = self.start_time
        self.process_list = []
        self.process_list_lock = threading.Lock()
        self.video_recognition_running = False
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.thread = threading.Thread(
            target=self.loop.run_forever,
            daemon=True
        )
        self.thread.start()
        self.ui = MonitoringUI(self)
        
        # Инициализируем менеджер RBK и MIR24
        self.rbk_mir24_manager = RBKMIR24Manager(self, self.ui)
        
        self.start_status_server()
        self.start_scheduler()
        self._cleanup_old_sent_texts()
        
        # Кэш для результатов Hugging Face API
        self.hf_cache = {}
        self.hf_cache_lock = threading.Lock()
        self.hf_cache_max_size = 1000  # Максимальное количество кэшированных результатов
        self._monitoring_threads_lock = threading.Lock()
        self._start_watchdog_thread()
        self._start_heartbeat_thread()
        self._start_resource_monitor_thread()
        self._start_hf_cache_cleaner_thread()
        self._start_temp_files_cleaner_thread()

    def start_status_server(self):
        """
        Запускает HTTP-сервер для получения статусов от дочерних процессов.
        """
        def create_handler(*args, **kwargs):
            return StatusHandler(self.ui, *args, **kwargs)

        try:
            server_address = ('127.0.0.1', 8989)
            self.httpd = HTTPServer(server_address, create_handler)
            server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            server_thread.start()
            logger.info("HTTP-сервер для статусов запущен на порту 8989")
        except Exception as e:
            logger.error(f"Не удалось запустить HTTP-сервер: {e}")

    def start_rbk_mir24(self):
        """
        Запуск мониторинга RBK и MIR24 (ручной запуск).
        """
        self.rbk_mir24_manager.start_manual_recording()

    def stop_rbk_mir24(self):
        """
        Остановка мониторинга RBK и MIR24.
        """
        self.rbk_mir24_manager.stop_recording()

    def start_lines_monitoring(self):
        """
        Запуск мониторинга строк по кнопке.
        """
        self.rbk_mir24_manager.start_lines_monitoring()

    def stop_lines_monitoring(self):
        """
        Остановка мониторинга строк.
        """
        self.rbk_mir24_manager.stop_lines_monitoring()

    def save_and_send_lines(self):
        """
        Запускает полный цикл проверки скриншотов, фильтрации и отправки в Telegram.
        """
        try:
            self.ui.update_status("Начало обработки скриншотов...")
            self.ui.update_processing_status("Выполняется...")
            thread = threading.Thread(
                target=self._save_and_send_lines_task,
                daemon=True
            )
            thread.start()
        except Exception as e:
            logger.error(f"Ошибка при запуске обработки скриншотов: {e}")
            self.ui.update_status("Ошибка обработки")
            messagebox.showerror("Ошибка", f"Не удалось запустить обработку скриншотов: {e}")

    def fuzzy_keyword_match(self, text, keywords, threshold=0.8):
        """
        Проверяет, есть ли в тексте слова, похожие на ключевые (fuzzy matching).

        Args:
            text (str): Текст для поиска.
            keywords (Iterable[str]): Список ключевых слов.
            threshold (float): Порог схожести для SequenceMatcher.
        Returns:
            bool: True, если найдено похожее слово, иначе False.
        """
        text = text.lower()
        for kw in keywords:
            if kw in text:
                return True
            # Проверяем каждое слово в тексте
            for word in text.split():
                if SequenceMatcher(None, kw, word).ratio() >= threshold:
                    return True
        return False

    def _save_and_send_lines_task(self):
        """
        Задача для проверки, фильтрации и отправки скриншотов.
        """
        summary_title = "Результат обработки скриншотов"
        try:
            screenshots_dir = Path("screenshots")
            processed_dir = Path("screenshots_processed")
            processed_dir.mkdir(exist_ok=True)

            if not screenshots_dir.exists() or not any(screenshots_dir.rglob("*.*")):
                logger.warning("Папка 'screenshots' пуста или не существует.")
                self.ui.root.after(0, messagebox.showinfo, summary_title, "Папка 'screenshots' пуста. Нет файлов для обработки.")
                self.ui.root.after(0, self.ui.update_processing_status, "Ожидание")
                return

            self.ui.root.after(0, self.ui.update_processing_status, "Обработка: распознавание текста...")
            self.ui.root.after(0, self.ui.show_progress)
            files_with_keywords = []
            file_captions = {}
            all_files = list(screenshots_dir.rglob("*.[jp][pn]g")) 
            logger.info(f"Найдено {len(all_files)} скриншотов для обработки.")
            keywords = self._load_keywords()
            today_str = datetime.now().strftime('%Y%m%d')
            sent_texts_file = Path(f'sent_texts_{today_str}.txt')
            sent_texts = []
            if sent_texts_file.exists():
                with sent_texts_file.open('r', encoding='utf-8') as f:
                    sent_texts = [line.strip() for line in f if line.strip()]
            session_texts = []  # Для хранения текстов в рамках одной обработки
            total_files = len(all_files)
            for i, file_path in enumerate(all_files):
                recognized_text = self._extract_text_from_image(file_path)
                text_lower = recognized_text.lower()
                has_keyword = False
                # --- Fuzzy matching вместо Hugging Face ---
                if self.fuzzy_keyword_match(text_lower, keywords):
                    has_keyword = True
                is_duplicate = False
                for prev_text in sent_texts + session_texts:
                    similarity = SequenceMatcher(None, text_lower, prev_text).ratio()
                    if similarity > 0.8:
                        is_duplicate = True
                        break
                channel = ""
                timestamp = ""
                try:
                    channel = file_path.parent.name
                except Exception:
                    channel = ""
                try:
                    date_pattern = r'(\d{8})_(\d{6})'
                    match = re.search(date_pattern, file_path.name)
                    if match:
                        date_str = match.group(1)
                        time_str = match.group(2)
                        timestamp = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    timestamp = ""
                if has_keyword and not is_duplicate:
                    try:
                        new_path = processed_dir / file_path.name
                        file_path.rename(new_path)
                        files_with_keywords.append(new_path)
                        caption = f"{channel}\n{timestamp}\n{recognized_text}".strip()
                        file_captions[str(new_path)] = caption
                        session_texts.append(text_lower)
                        logger.info(f"Файл {file_path.name} перемещен в {processed_dir}")
                    except Exception as e:
                        logger.error(f"Не удалось переместить файл {file_path.name}: {e}")
                else:
                    try:
                        file_path.unlink()
                        logger.info(f"Файл {file_path.name} удален (нет ключевых слов или дубликат).")
                    except Exception as e:
                        logger.error(f"Не удалось удалить файл {file_path.name}: {e}")
                # --- Обновление прогресса ---
                percent = ((i + 1) / total_files) * 100 if total_files else 100
                self.ui.root.after(0, self.ui.update_progress, percent)
            # После отправки файлов — добавляем тексты в файл за день
            if files_with_keywords:
                with sent_texts_file.open('a', encoding='utf-8') as f:
                    for file_path in files_with_keywords:
                        text = self._extract_text_from_image(file_path).lower()
                        f.write(text + '\n')
            self.ui.root.after(0, self.ui.hide_progress)
            if not files_with_keywords:
                self.ui.root.after(0, messagebox.showinfo, summary_title, "Обработка завершена. Файлов с ключевыми словами не найдено.")
                self.ui.root.after(0, self.ui.update_processing_status, "Ожидание")
                return
            self.ui.root.after(0, self.ui.update_processing_status, f"Отправка {len(files_with_keywords)} файлов в Telegram...")
            sent_count = 0
            for file_path in files_with_keywords:
                caption = file_captions.get(str(file_path), f"{file_path.name}")
                if send_files([str(file_path)], caption=caption):
                    sent_count += 1
                    try:
                        file_path.unlink() 
                        logger.info(f"Файл {file_path.name} отправлен и удален.")
                    except Exception as e:
                        logger.error(f"Не удалось удалить файл {file_path.name} после отправки: {e}")
                else:
                    logger.warning(f"Не удалось отправить файл {file_path.name}")
            summary_message = f"Обработка завершена.\n\nНайдено файлов с ключевыми словами: {len(files_with_keywords)}\nУспешно отправлено: {sent_count}"
            if sent_count < len(files_with_keywords):
                summary_message += "\n\nНекоторые файлы не удалось отправить. Подробности в логах."
            self.ui.root.after(0, messagebox.showinfo, summary_title, summary_message)
        except Exception as e:
            logger.error(f"Ошибка в задаче обработки скриншотов: {e}")
            self.ui.root.after(0, messagebox.showerror, "Ошибка", f"В процессе обработки скриншотов произошла ошибка:\n{e}")
        finally:
            self.ui.root.after(0, self.ui.update_processing_status, "Ожидание")
            self.ui.root.after(0, self.ui.hide_progress)

    def _process_and_send_screenshots(self):
        """
        Обработка и отправка скриншотов.
        """
        try:
            # Останавливаем мониторинг
            self.stop_lines_monitoring()
            self.ui.update_processing_status("Обработка скриншотов...")
            
            # Обрабатываем скриншоты и отправляем в Telegram
            self.save_and_send_lines()
            self.ui.update_processing_status("Скриншоты обработаны и отправлены")
            logger.info("Скриншоты обработаны и отправлены")
        except Exception as e:
            logger.error(f"Ошибка при обработке и отправке скриншотов: {e}")
            self.ui.update_processing_status(f"Ошибка: {str(e)}")

    def _send_daily_file_to_telegram(self):
        """
        Отправка ежедневного файла в Telegram.
        """
        try:
            file_path = get_daily_file_path()
            if os.path.exists(file_path):
                logger.info(f"Отправка ежедневного файла в Telegram: {file_path}")
                self.ui.update_status("Отправка ежедневного файла в Telegram...")
                
                # Отправляем файл
                from telegram_sender import send_report_files
                send_report_files(file_path, [])
                
                self.ui.update_status("Ежедневный файл отправлен в Telegram")
                logger.info("Ежедневный файл успешно отправлен в Telegram")
            else:
                logger.warning("Ежедневный файл не найден для отправки")
                self.ui.update_status("Ежедневный файл не найден")
        except Exception as e:
            logger.error(f"Ошибка при отправке ежедневного файла в Telegram: {e}")
            self.ui.update_status(f"Ошибка отправки ежедневного файла: {str(e)}")

    def _send_daily_sent_texts_to_telegram(self):
        """
        Отправка файла с текстами отправленных скриншотов за день в Telegram.
        """
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            sent_texts_file = Path(f'sent_texts_{today_str}.txt')
            if sent_texts_file.exists():
                logger.info(f"Отправка файла с текстами скриншотов за день в Telegram: {sent_texts_file}")
                self.ui.update_status("Отправка файла с текстами скриншотов за день в Telegram...")
                from telegram_sender import send_report_files
                send_report_files(str(sent_texts_file), [])
                self.ui.update_status("Файл с текстами скриншотов за день отправлен в Telegram")
                logger.info("Файл с текстами скриншотов за день успешно отправлен в Telegram")
            else:
                logger.warning("Файл с текстами скриншотов за день не найден для отправки")
                self.ui.update_status("Файл с текстами скриншотов за день не найден")
            # После отправки — очистить устаревшие файлы
            self._cleanup_old_sent_texts()
        except Exception as e:
            logger.error(f"Ошибка при отправке файла с текстами скриншотов за день в Telegram: {e}")
            self.ui.update_status(f"Ошибка отправки файла с текстами скриншотов за день: {str(e)}")

    def _check_and_send_new_files(self):
        """
        Проверка и отправка новых файлов.
        """
        try:
            # Проверяем новые скриншоты
            screenshots_dir = Path("screenshots")
            if screenshots_dir.exists():
                new_files = []
                for filename in screenshots_dir.iterdir():
                    if filename.suffix == '.jpg' and not filename.name.startswith('processed_'):
                        file_path = filename
                        # Проверяем, что файл не старше 5 минут
                        if time_module.time() - file_path.stat().st_mtime < 300:
                            new_files.append(file_path)
                if new_files:
                    logger.info(f"Найдено {len(new_files)} новых файлов для отправки")
                    self.ui.update_status(f"Отправка {len(new_files)} файлов...")
                    # Отправляем файлы в Telegram
                    for file_path in new_files:
                        try:
                            send_files([str(file_path)])
                            # Переименовываем файл как обработанный
                            processed_path = file_path.parent / f"processed_{file_path.name}"
                            file_path.rename(processed_path)
                            logger.info(f"Файл {file_path} отправлен и помечен как обработанный")
                        except Exception as e:
                            logger.error(f"Ошибка при отправке файла {file_path}: {e}")
                    self.ui.update_status(f"Отправлено {len(new_files)} файлов")
        except Exception as e:
            logger.error(f"Ошибка при проверке новых файлов: {e}")

    def check_and_send_videos(self):
        """
        Запускает полный цикл проверки crop-видео и отправки в Telegram.
        """
        if self.video_recognition_running:
            messagebox.showwarning("Предупреждение", "Проверка crop-видео уже запущена.")
            return

        try:
            self.video_recognition_running = True
            self.ui.update_video_check_status("Выполняется: Распознавание...")
            
            # Запускаем весь процесс в отдельном потоке, чтобы не блокировать UI
            thread = threading.Thread(
                target=self._run_check_and_send_task,
                daemon=True
            )
            thread.start()
            
        except Exception as e:
            logger.error(f"Ошибка при запуске проверки и отправки crop-видео: {e}")
            self.video_recognition_running = False
            self.ui.update_video_check_status("Ошибка")
            messagebox.showerror("Ошибка", f"Не удалось запустить процесс: {e}")

    def _run_check_and_send_task(self):
        """
        Задача, выполняющая распознавание, поиск и отправку crop-видео.
        """
        summary_title = "Результат проверки crop-видео"
        try:
            # Проверяем только папку lines_video (crop видео)
            lines_video_dir = Path("lines_video")
            
            # Проверяем наличие видео в папке lines_video
            has_lines_videos = lines_video_dir.exists() and any(lines_video_dir.glob("**/*.mp4"))
            
            if not has_lines_videos:
                logger.warning("В папке lines_video нет crop-видео для проверки.")
                self.ui.root.after(0, self.ui.update_status, "Crop-видео для проверки не найдены.")
                self.ui.root.after(0, messagebox.showinfo, summary_title, "В папке `lines_video` нет файлов для проверки.")
                return

            # --- Этап 1: Распознавание текста из crop-видео ---
            logger.info("Начало распознавания текста из crop-видео")
            self.ui.root.after(0, self.ui.update_status, "Распознавание текста из crop-видео...")
            
            # Обрабатываем crop-видео из папки lines_video
            logger.info("Обработка crop-видео из папки lines_video")
            self._recognize_text_in_videos_to_channel_txt(lines_video_dir)
            
            logger.info("Распознавание завершено.")
            self.ui.root.after(0, self.ui.update_status, "Распознавание текста из crop-видео завершено.")

            # --- Этап 2: Поиск ключевых слов и отправка видео ---
            self.ui.root.after(0, self.ui.update_video_check_status, "Выполняется: Поиск ключевых слов...")
            logger.info("Поиск ключевых слов и их вариаций через Hugging Face API")
            videos_to_send = self._get_videos_with_keywords_hf_channelwise()

            if not videos_to_send:
                self.ui.root.after(0, self.ui.update_status, "Crop-видео с ключевыми словами не найдены. Очистка...")
                logger.info("Crop-видео с ключевыми словами не найдены. Все видеофайлы будут удалены.")
                self._cleanup_video_files()
                self._cleanup_recognized_texts_channelwise()
                self.ui.root.after(0, messagebox.showinfo, summary_title, "Проверка завершена. Crop-видео с ключевыми словами не найдены. Все видеофайлы удалены.")
                return

            logger.info(f"Найдено {len(videos_to_send)} crop-видео с ключевыми словами")
            self.ui.root.after(0, self.ui.update_status, f"Отправка {len(videos_to_send)} crop-видео...")

            sent_count = 0
            for video_info in videos_to_send:
                try:
                    video_path = video_info['video_path']
                    channel_name = video_info['channel']
                    found_keywords = video_info['found_keywords']
                    if self._send_single_video_to_telegram(video_path, channel_name, found_keywords):
                        sent_count += 1
                        logger.info(f"Crop-видео {video_path.name} отправлено в Telegram")
                        video_path.unlink(missing_ok=True)
                        self._remove_video_text_from_channel_txt(video_path.name, channel_name)
                    else:
                        logger.error(f"Не удалось отправить crop-видео {video_path.name}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке crop-видео {video_info.get('video_path', 'unknown')}: {e}")

            self._cleanup_video_files()
            self._cleanup_recognized_texts_channelwise()

            final_status_msg = f"Отправлено {sent_count} из {len(videos_to_send)} crop-видео. Очистка завершена."
            self.ui.root.after(0, self.ui.update_status, final_status_msg)
            logger.info(f"Отправка завершена. Отправлено {sent_count} crop-видео, все файлы удалены")

            summary_message = f"Отправка завершена.\n\nНайдено crop-видео с ключевыми словами: {len(videos_to_send)}\nУспешно отправлено: {sent_count}"
            if sent_count < len(videos_to_send):
                summary_message += "\n\nНекоторые crop-видео не удалось отправить. Подробности смотрите в логах."
            self.ui.root.after(0, messagebox.showinfo, summary_title, summary_message)

        except Exception as e:
            logger.error(f"Ошибка в процессе проверки и отправки crop-видео: {e}")
            self.ui.root.after(0, self.ui.update_status, f"Ошибка: {str(e)}")
            self.ui.root.after(0, self.ui.update_video_check_status, "Ошибка")
            self.ui.root.after(0, messagebox.showerror, "Ошибка", f"В процессе проверки произошла ошибка:\n{e}")
        finally:
            self.video_recognition_running = False
            self.ui.root.after(0, self.ui.update_video_check_status, "Завершено")

    def _recognize_text_in_videos_to_channel_txt(self, video_dir):
        """
        Распознаёт текст из всех crop-видеофайлов и сохраняет результаты в отдельные txt по каналам.
        """
        recognized_dir = Path("recognized_text")
        
        # Создание директории recognized_text если она не существует
        try:
            recognized_dir.mkdir(exist_ok=True)
            logger.info(f"Директория recognized_text создана/проверена: {recognized_dir}")
        except Exception as e:
            logger.error(f"Ошибка при создании директории recognized_text: {e}")
            return
        
        # Проверка существования и валидности video_dir
        if not video_dir.exists():
            logger.error(f"Директория video_dir не найдена: {video_dir}")
            return
        
        if not video_dir.is_dir():
            logger.error(f"Путь video_dir не является директорией: {video_dir}")
            return
        
        channel_files = {}
        for channel_dir in video_dir.iterdir():
            if not channel_dir.is_dir():
                continue
            channel_name = channel_dir.name
            txt_path = recognized_dir / f"{channel_name}.txt"
            if channel_name not in channel_files:
                try:
                    channel_files[channel_name] = open(txt_path, 'w', encoding='utf-8')
                except Exception as e:
                    logger.error(f"Ошибка при создании файла {txt_path}: {e}")
                    continue
            txt_file = channel_files[channel_name]
            for video_file in channel_dir.glob("*.mp4"):
                try:
                    cap = cv2.VideoCapture(str(video_file))
                    if not cap.isOpened():
                        logger.warning(f"Не удалось открыть видео {video_file}")
                        continue
                    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    step = int(fps * 2) if fps > 0 else 50  # Кадр каждые 2 секунды
                    frame_idx = 0
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        if frame_idx % step == 0:
                            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                            text = pytesseract.image_to_string(gray, lang='rus+eng')
                            timestamp_sec = int(frame_idx / fps) if fps > 0 else frame_idx
                            # Сохраняем: имя_файла\tномер_кадра\tсекунда\tтекст
                            txt_file.write(f"{video_file.name}\t{frame_idx}\t{timestamp_sec}\t{text.replace('\n', ' ').strip()}\n")
                        frame_idx += 1
                    cap.release()
                    logger.info(f"Распознан текст по кадрам для {video_file.name}")
                except Exception as e:
                    logger.error(f"Ошибка при распознавании текста в {video_file}: {e}")
        for f in channel_files.values():
            try:
                f.close()
            except Exception as e:
                logger.error(f"Ошибка при закрытии файла: {e}")

    def _get_videos_with_keywords_hf_channelwise(self):
        """
        Возвращает список crop-видео с найденными ключевыми словами (через Hugging Face).
        """
        recognized_dir = Path("recognized_text")
        
        # Проверка существования директории recognized_text
        if not recognized_dir.exists():
            logger.warning(f"Директория recognized_text не найдена: {recognized_dir}")
            return []
        
        if not recognized_dir.is_dir():
            logger.error(f"Путь recognized_text не является директорией: {recognized_dir}")
            return []
        
        keywords = list(self._load_keywords())
        videos_to_send = []
        
        for txt_path in recognized_dir.glob("*.txt"):
            channel_name = txt_path.stem
            try:
                with open(txt_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            video_file, text = line.strip().split('\t', 1)
                            found_keywords = self._find_keywords_hf(text, keywords)
                            if found_keywords:
                                # Ищем видео только в lines_video (crop видео)
                                video_path = Path("lines_video") / channel_name / video_file
                                
                                if video_path.exists():
                                    videos_to_send.append({
                                        'video_path': video_path,
                                        'channel': channel_name,
                                        'found_keywords': found_keywords
                                    })
                                else:
                                    logger.warning(f"Crop-видео {video_file} не найдено в lines_video для канала {channel_name}")
                        except Exception as e:
                            logger.error(f"Ошибка при обработке строки recognized_text/{txt_path.name}: {e}")
            except Exception as e:
                logger.error(f"Ошибка при чтении файла {txt_path}: {e}")
        return videos_to_send

    def _remove_video_text_from_channel_txt(self, video_file_name, channel_name):
        """
        Удаляет строку из recognized_text/<channel>.txt по имени видеофайла.
        """
        recognized_dir = Path("recognized_text")
        
        # Проверка существования директории recognized_text
        if not recognized_dir.exists():
            logger.warning(f"Директория recognized_text не найдена: {recognized_dir}")
            return
        
        if not recognized_dir.is_dir():
            logger.error(f"Путь recognized_text не является директорией: {recognized_dir}")
            return
        
        txt_path = recognized_dir / f"{channel_name}.txt"
        if not txt_path.exists():
            logger.warning(f"Файл {txt_path} не найден")
            return
        
        try:
            lines = []
            with open(txt_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            with open(txt_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    if not line.startswith(video_file_name + '\t'):
                        f.write(line)
            logger.info(f"Удалена строка для видео {video_file_name} из {txt_path}")
        except Exception as e:
            logger.error(f"Ошибка при удалении строки для видео {video_file_name} из {txt_path}: {e}")

    def _cleanup_recognized_texts_channelwise(self):
        """
        Удаляет все recognized_text/<channel>.txt файлы.
        """
        recognized_dir = Path("recognized_text")
        
        # Проверка существования директории recognized_text
        if not recognized_dir.exists():
            logger.info(f"Директория recognized_text не существует, очистка не требуется: {recognized_dir}")
            return
        
        if not recognized_dir.is_dir():
            logger.error(f"Путь recognized_text не является директорией: {recognized_dir}")
            return
        
        for txt_path in recognized_dir.glob("*.txt"):
            try:
                txt_path.unlink()
                logger.info(f"Удален файл: {txt_path}")
            except Exception as e:
                logger.error(f"Ошибка при удалении файла {txt_path}: {e}")

    def _cleanup_video_files(self):
        """
        Удаляет все видеофайлы из папки lines_video.
        """
        lines_video_dir = Path("lines_video")
        
        # Проверка существования директории lines_video
        if not lines_video_dir.exists():
            logger.info(f"Директория lines_video не существует, очистка не требуется: {lines_video_dir}")
            return
        
        if not lines_video_dir.is_dir():
            logger.error(f"Путь lines_video не является директорией: {lines_video_dir}")
            return
        
        deleted_count = 0
        for channel_dir in lines_video_dir.iterdir():
            if not channel_dir.is_dir():
                continue
            for video_file in channel_dir.glob("*.mp4"):
                try:
                    video_file.unlink()
                    deleted_count += 1
                    logger.info(f"Удален видеофайл: {video_file}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении видеофайла {video_file}: {e}")
        
        logger.info(f"Очистка видеофайлов завершена. Удалено файлов: {deleted_count}")

    def cleanup(self):
        """
        Очистка ресурсов при закрытии приложения.
        """
        try:
            logger.info("Начало очистки ресурсов...")
            
            # Очищаем кэш Hugging Face API
            self.clear_hf_cache()
            
            # Очищаем ресурсы менеджера RBK и MIR24
            if hasattr(self, 'rbk_mir24_manager'):
                self.rbk_mir24_manager.cleanup()
            
            # Останавливаем распознавание crop-видео
            if self.video_recognition_running:
                self.video_recognition_running = False
                logger.info("Распознавание crop-видео остановлено")
            
            # Останавливаем event loop
            if self.loop and not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self.loop.stop)
                logger.info("Event loop остановлен")
            
            # Очищаем UI
            if hasattr(self, 'ui'):
                self.ui.cleanup()
            
            # Останавливаем HTTP-сервер
            if hasattr(self, 'httpd'):
                logger.info("Остановка HTTP-сервера...")
                self.httpd.shutdown()
                logger.info("HTTP-сервер остановлен.")
            
            logger.info("Очистка ресурсов завершена")
            
        except Exception as e:
            logger.error(f"Ошибка при очистке ресурсов: {e}")

    def start_scheduler(self):
        """
        Запуск планировщика задач.
        """
        if not self.scheduler_running:
            self.scheduler_running = True
            self.scheduler_thread = threading.Thread(
                target=self._run_scheduler,
                daemon=True
            )
            self.scheduler_thread.start()
            logger.info("Планировщик задач запущен")

    def _run_scheduler(self):
        """
        Основной цикл планировщика задач.
        """
        logger.info("Настройка расписания задач...")
        self._setup_schedule()
        logger.info("Расписание настроено, начинаем выполнение...")
        self.ui.update_scheduler_status("Активен")
        while self.scheduler_running:
            try:
                if not self.scheduler_paused:
                    try:
                        schedule.run_pending()
                    except Exception as sched_exc:
                        logger.error(f"Ошибка в schedule.run_pending: {sched_exc}")
                    # Проверка на необходимость перезагрузки расписания
                    if getattr(self, 'scheduler_reload_requested', False):
                        logger.info("Перезагрузка расписания по запросу...")
                        self.reload_scheduler()
                        self.scheduler_reload_requested = False
                self._check_and_start_idle_monitoring()
                time_module.sleep(1)
            except Exception as e:
                logger.error(f"Ошибка в планировщике: {e}")
                self.ui.update_scheduler_status(f"Ошибка: {str(e)}")

    def _setup_schedule(self):
        """
        Настройка расписания задач для всех каналов.
        """
        schedule.clear()
        
        # Загружаем конфигурацию каналов через config_manager
        channels = config_manager.load_channels()
        if not channels:
            error_msg = "Не удалось загрузить конфигурацию каналов. Планировщик не может быть настроен."
            logger.error(error_msg)
            self.ui.update_scheduler_status("Ошибка: не удалось загрузить каналы")
            messagebox.showerror("Ошибка конфигурации", error_msg)
            return
        
        channel_methods = {
            "R1": self._start_r1_monitoring,
            "Zvezda": self._start_zvezda_monitoring,
            "TVC": self._start_other_channels_monitoring,
            "RenTV": self._start_other_channels_monitoring,
            "NTV": self._start_other_channels_monitoring,
        }
        for channel, info in channels.items():
            lines_times = set(info.get("lines", []))
            if not lines_times:
                continue
            # Для RBK и MIR24 — запускать crop-видео и мониторинг строк по расписанию
            if channel in ("RBK", "MIR24"):
                for t in lines_times:
                    schedule.every().day.at(t).do(self._start_rbk_mir24_crop_recording)
                    logger.info(f"Добавлено расписание записи crop-видео для {channel}: {t}")
                    schedule.every().day.at(t).do(self._start_rbk_mir24_lines_monitoring)
                    logger.info(f"Добавлено расписание мониторинга строк для {channel}: {t}")
            else:
                method = channel_methods.get(channel)
                if method:
                    for t in lines_times:
                        schedule.every().day.at(t).do(method)
                        logger.info(f"Добавлено расписание для {channel} (lines): {t}")
        schedule.every().day.at("22:00").do(self._send_daily_file_to_telegram)
        logger.info("Добавлено расписание отправки ежедневного файла в Telegram: 22:00")
        schedule.every().day.at("23:00").do(self._send_daily_sent_texts_to_telegram)
        logger.info("Добавлено расписание отправки sent_texts_YYYYMMDD.txt в Telegram: 23:00")

    def reload_scheduler(self):
        """
        Перезагрузка расписания задач.
        """
        logger.info("Выполняется перезагрузка расписания...")
        # Очищаем кэш config_manager перед перезагрузкой
        config_manager.clear_cache()
        self._setup_schedule()
        logger.info("Расписание успешно перезагружено.")
        self.ui.update_scheduler_status("Перезагружено")

    def request_scheduler_reload(self):
        """
        Установить флаг для перезагрузки расписания (можно вызывать из UI или внешнего события).
        """
        self.scheduler_reload_requested = True

    def pause_scheduler(self):
        """
        Приостановить планировщик задач.
        """
        if not self.scheduler_paused:
            self.scheduler_paused = True
            logger.info("Планировщик приостановлен.")
            self.ui.update_scheduler_status("Приостановлен")
            self.ui.toggle_scheduler_buttons(paused=True)

    def resume_scheduler(self):
        """
        Возобновить планировщик задач.
        """
        if self.scheduler_paused:
            self.scheduler_paused = False
            logger.info("Планировщик возобновлен.")
            self.ui.update_scheduler_status("Активен")
            self.ui.toggle_scheduler_buttons(paused=False)

    def _has_new_videos_in_lines_video(self):
        """
        Проверяет, есть ли новые видеофайлы в папке lines_video.
        """
        video_dir = Path("lines_video")
        if not video_dir.exists():
            return False
        for channel_dir in video_dir.iterdir():
            if not channel_dir.is_dir():
                continue
            if any(channel_dir.glob("*.mp4")):
                return True
        return False

    def start_video_processing(self):
        """
        Запускает скрипт обработки видеосюжетов в отдельном потоке (устаревшая функция).
        """
        messagebox.showinfo("Информация", "Обработка полноценного видео больше не поддерживается. Используйте 'Проверка crop-видео' для обработки crop-роликов.")
        logger.info("Попытка запуска обработки полноценного видео - функция больше не поддерживается")

    def _extract_text_from_image(self, image_path):
        """
        Извлекает текст из изображения с помощью pytesseract.
        """
        try:
            img = cv2.imread(str(image_path))
            if img is None:
                return ""
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            text = pytesseract.image_to_string(gray, lang='rus+eng')
            return text
        except Exception as e:
            logger.error(f"Ошибка при извлечении текста из {image_path}: {e}")
            return ""

    def _load_keywords(self):
        """
        Загружает и приводит к нижнему регистру список ключевых слов.
        """
        return set(word.lower() for word in config_manager.get_keywords_list())

    def _find_keywords_local(self, text, keywords):
        """
        Улучшенная локальная проверка ключевых слов без использования API.
        """
        found = []
        text_lower = text.lower()
        
        # Предобработка текста
        import re
        text_clean = re.sub(r'\s+', ' ', text_lower).strip()
        words = text_clean.split()
        
        for kw in keywords:
            kw_lower = kw.lower()
            kw_found = False
            
            # 1. Точное совпадение
            if kw_lower in text_clean:
                found.append(kw)
                logger.debug(f"Найдено точное совпадение ключевого слова '{kw}'")
                continue
            
            # 2. Проверка на уровне слов
            for word in words:
                word_clean = re.sub(r'[^\wа-яё]', '', word)
                if len(word_clean) < 3:
                    continue
                
                if word_clean == kw_lower:
                    found.append(kw)
                    logger.debug(f"Найдено точное совпадение слова '{kw}' в '{word_clean}'")
                    kw_found = True
                    break
                
                if kw_lower in word_clean or word_clean in kw_lower:
                    found.append(kw)
                    logger.debug(f"Найдено вхождение ключевого слова '{kw}' в слово '{word_clean}'")
                    kw_found = True
                    break
            
            if kw_found:
                continue
            
            # 3. Fuzzy matching
            from difflib import SequenceMatcher
            for word in words:
                word_clean = re.sub(r'[^\wа-яё]', '', word)
                if len(word_clean) < 3:
                    continue
                
                similarity = SequenceMatcher(None, kw_lower, word_clean).ratio()
                if similarity >= 0.8:
                    found.append(kw)
                    logger.debug(f"Найдено fuzzy совпадение '{kw}' ~ '{word_clean}' (схожесть: {similarity:.2f})")
                    break
        
        return found

    def _find_keywords_hf(self, text, keywords):
        """
        Проверка ключевых слов через Hugging Face API с fallback на локальную.
        """
        # Импортируем токен из telegram_sender
        try:
            from telegram_sender import HF_API_TOKEN
        except ImportError:
            # Fallback к переменной окружения
            HF_API_TOKEN = os.environ.get("HF_API_TOKEN")
        
        # Проверка существования токена HF_API_TOKEN
        if not HF_API_TOKEN:
            logger.warning("HF_API_TOKEN не найден в переменных окружения, используется локальная проверка")
            return self._find_keywords_local(text, keywords)
        
        # Создаем ключ кэша на основе текста и ключевых слов
        cache_key = f"{hash(text)}:{hash(tuple(sorted(keywords)))}"
        
        # Проверяем кэш
        with self.hf_cache_lock:
            if cache_key in self.hf_cache:
                logger.debug("Используется кэшированный результат Hugging Face API")
                return self.hf_cache[cache_key]
        
        # Используем более стабильную модель
        HF_API_URL = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium"
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        found = []
        
        try:
            # Создаем один запрос для всех ключевых слов
            keywords_list = ', '.join(keywords)
            prompt = f"""Analyze the following text and identify which keywords from the list are present or have variations.

Keywords to check: {keywords_list}

Text to analyze: {text}

Respond with only the keywords that are found, separated by commas. If no keywords are found, respond with "none".

Example responses:
- "пожар, МЧС, спасатели"
- "none"
- "авария, ДТП"
"""
            
            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_length": 100,
                    "return_full_text": False,
                    "temperature": 0.1,
                    "do_sample": False
                }
            }
            
            response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                # Обработка различных форматов ответа
                answer = ""
                if isinstance(result, list) and len(result) > 0:
                    answer = result[0].get('generated_text', '').strip().lower()
                elif isinstance(result, dict):
                    answer = result.get('generated_text', '').strip().lower()
                elif isinstance(result, str):
                    answer = result.strip().lower()
                
                # Парсим ответ и находим ключевые слова
                if answer and answer != "none":
                    # Удаляем лишние символы и разбиваем по запятым
                    answer_clean = answer.replace('\n', ' ').replace('"', '').replace("'", "")
                    found_keywords = [kw.strip() for kw in answer_clean.split(',') if kw.strip()]
                    
                    # Проверяем, что найденные слова действительно есть в нашем списке
                    for found_kw in found_keywords:
                        # Ищем точное совпадение или близкое совпадение
                        for original_kw in keywords:
                            if (found_kw == original_kw.lower() or 
                                found_kw in original_kw.lower() or 
                                original_kw.lower() in found_kw):
                                if original_kw not in found:
                                    found.append(original_kw)
                                    logger.debug(f"Найдено ключевое слово '{original_kw}' через Hugging Face API")
                                break
                    
                    logger.info(f"Hugging Face API нашел {len(found)} ключевых слов: {found}")
                else:
                    logger.info("Hugging Face API не нашел ключевых слов")
                    
            else:
                logger.warning(f"HF API error: {response.status_code} {response.text}")
                # При ошибке API используем локальную проверку
                found = self._find_keywords_local(text, keywords)
                
        except requests.exceptions.Timeout:
            logger.warning("Таймаут при проверке ключевых слов через Hugging Face API")
            found = self._find_keywords_local(text, keywords)
        except requests.exceptions.RequestException as e:
            logger.warning(f"Ошибка сети при проверке ключевых слов через Hugging Face API: {e}")
            found = self._find_keywords_local(text, keywords)
        except (ValueError, KeyError) as e:
            logger.warning(f"Ошибка парсинга ответа Hugging Face API: {e}")
            found = self._find_keywords_local(text, keywords)
        except Exception as e:
            logger.error(f"Неожиданная ошибка при проверке ключевых слов через Hugging Face API: {e}")
            found = self._find_keywords_local(text, keywords)
        
        # Если API не дал результатов, используем локальную проверку
        if not found:
            logger.info("Hugging Face API не нашел ключевых слов, используется локальная проверка")
            found = self._find_keywords_local(text, keywords)
        
        # Сохраняем результат в кэш
        self._add_to_hf_cache(cache_key, found)
                
        return found
    
    def _add_to_hf_cache(self, cache_key, result):
        """
        Добавляет результат в кэш Hugging Face API с ограничением размера.
        """
        with self.hf_cache_lock:
            # Если кэш переполнен, удаляем старые записи
            if len(self.hf_cache) >= self.hf_cache_max_size:
                # Удаляем 20% старых записей
                keys_to_remove = list(self.hf_cache.keys())[:self.hf_cache_max_size // 5]
                for key in keys_to_remove:
                    del self.hf_cache[key]
                logger.debug(f"Очищен кэш Hugging Face API, удалено {len(keys_to_remove)} записей")
            self.hf_cache[cache_key] = result
            logger.debug(f"Добавлен результат в кэш Hugging Face API, размер кэша: {len(self.hf_cache)}")
    
    def clear_hf_cache(self):
        """
        Очищает кэш Hugging Face API.
        """
        with self.hf_cache_lock:
            self.hf_cache.clear()
            logger.info("Кэш Hugging Face API очищен")

    def _start_r1_monitoring(self):
        """
        Запуск мониторинга строк для канала R1 по расписанию.
        """
        self.rbk_mir24_manager.start_scheduled_lines_monitoring(['R1'])

    def _start_zvezda_monitoring(self):
        """
        Запуск мониторинга строк для канала Zvezda по расписанию.
        """
        self.rbk_mir24_manager.start_scheduled_lines_monitoring(['Zvezda'])

    def _start_other_channels_monitoring(self):
        """
        Запуск мониторинга строк для других каналов по расписанию (TVC, RenTV, NTV).
        """
        # Определяем канал из контекста планировщика
        # Поскольку этот метод используется для нескольких каналов, 
        # мы не можем точно определить канал, поэтому используем общий подход
        self.rbk_mir24_manager.start_scheduled_lines_monitoring()

    def _check_and_start_idle_monitoring(self):
        """
        Заглушка для проверки и запуска idle-мониторинга (для планировщика).
        """
        logger.debug("Вызван _check_and_start_idle_monitoring (заглушка)")
        pass

    def _start_rbk_mir24_crop_recording(self):
        """
        Запуск записи crop-видео для RBK и MIR24 по расписанию.
        """
        self.rbk_mir24_manager.start_scheduled_crop_recording(['RBK', 'MIR24'])

    def _start_rbk_mir24_lines_monitoring(self):
        """
        Запуск мониторинга строк (скриншотов) для RBK и MIR24 по расписанию и автоматическая обработка после завершения.
        """
        self.rbk_mir24_manager.start_scheduled_lines_monitoring(['RBK', 'MIR24'])

    def _start_channel_lines_monitoring(self, channel):
        """
        Запуск мониторинга строк (скриншотов) для указанного канала по расписанию и автоматическая обработка после завершения.
        """
        self.rbk_mir24_manager.start_scheduled_lines_monitoring([channel])

    def _cleanup_old_sent_texts(self):
        """
        Удаляет устаревшие файлы sent_texts_YYYYMMDD.txt, кроме текущего дня.
        """
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            current_dir = Path('.')
            
            # Проверка существования текущей директории
            if not current_dir.exists():
                logger.error(f"Текущая директория не найдена: {current_dir}")
                return
            
            if not current_dir.is_dir():
                logger.error(f"Текущий путь не является директорией: {current_dir}")
                return
            
            for file_path in current_dir.glob('sent_texts_*.txt'):
                if today_str not in file_path.name:
                    try:
                        file_path.unlink()
                        logger.info(f"Удалён устаревший файл: {file_path}")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении {file_path}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при очистке устаревших файлов sent_texts: {e}")

    def get_video_fragments_with_keywords(self, video_path, channel_name, keywords, context_sec=2):
        """
        По файлу recognized_text/<channel>.txt и списку ключевых слов возвращает интервалы (start_sec, end_sec)
        для нарезки видео (±context_sec вокруг каждого найденного предложения).
        """
        recognized_file = Path("recognized_text") / f"{channel_name}.txt"
        if not recognized_file.exists():
            logger.warning(f"Файл распознанного текста не найден: {recognized_file}")
            return []
        fragments = []
        video_name = video_path.name
        # Собираем все строки для этого видео
        with open(recognized_file, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.startswith(video_name + '\t')]
        for line in lines:
            try:
                parts = line.split('\t', 3)
                if len(parts) < 4:
                    continue
                _, _, timestamp_sec, text = parts
                timestamp_sec = int(timestamp_sec)
                found = self._find_keywords_local(text, keywords)
                if found:
                    start = max(0, timestamp_sec - context_sec)
                    end = timestamp_sec + context_sec
                    fragments.append((start, end))
            except Exception as e:
                logger.error(f"Ошибка при парсинге строки распознанного текста: {e}")
        # Объединяем пересекающиеся интервалы
        if not fragments:
            return []
        fragments.sort()
        merged = [fragments[0]]
        for start, end in fragments[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    def cut_and_concat_video_fragments_ffmpeg(self, video_path, fragments, output_path):
        """
        Нарезает и склеивает фрагменты видео через ffmpeg. fragments — список (start_sec, end_sec).
        Возвращает True при успехе.
        """
        import tempfile
        import subprocess
        import os
        temp_dir = tempfile.mkdtemp()
        temp_files = []
        try:
            for idx, (start, end) in enumerate(fragments):
                temp_file = os.path.join(temp_dir, f"frag_{idx}.mp4")
                duration = end - start
                cmd = [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-ss", str(start), "-t", str(duration),
                    "-c", "copy", temp_file
                ]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode != 0:
                    logger.error(f"Ошибка ffmpeg при нарезке: {result.stderr.decode()}")
                    continue
                temp_files.append(temp_file)
            if not temp_files:
                logger.warning("Нет нарезанных фрагментов для склейки")
                return False
            # Создаем файл со списком для ffmpeg
            concat_list = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_list, 'w', encoding='utf-8') as f:
                for temp_file in temp_files:
                    f.write(f"file '{temp_file}'\n")
            # Склеиваем
            cmd_concat = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                "-c", "copy", str(output_path)
            ]
            result = subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode != 0:
                logger.error(f"Ошибка ffmpeg при склейке: {result.stderr.decode()}")
                return False
            return True
        finally:
            # Удаляем временные файлы
            for temp_file in temp_files:
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
            try:
                os.remove(os.path.join(temp_dir, "concat_list.txt"))
            except Exception:
                pass
            try:
                os.rmdir(temp_dir)
            except Exception:
                pass

    def _send_single_video_to_telegram(self, video_path, channel_name, found_keywords):
        """
        Отправляет одно видео в Telegram. Если есть ключевые слова — отправляет видео целиком.
        Не отправляет видео, если оно уже было отправлено (sent_videos.txt) или неудачно отправлено (failed_videos.txt).
        После двух неудачных попыток отправки — добавляет в failed_videos.txt и очищает папку, как при успехе.
        """
        try:
            from telegram_sender import send_files
            sent_videos_file = Path('sent_videos.txt')
            failed_videos_file = Path('failed_videos.txt')
            sent_videos = set()
            failed_videos = set()
            if sent_videos_file.exists():
                with sent_videos_file.open('r', encoding='utf-8') as f:
                    sent_videos = set(line.strip() for line in f if line.strip())
            if failed_videos_file.exists():
                with failed_videos_file.open('r', encoding='utf-8') as f:
                    failed_videos = set(line.strip() for line in f if line.strip())
            video_name = os.path.basename(str(video_path))
            if video_name in sent_videos or video_name in failed_videos:
                logger.info(f"Видео {video_name} уже было отправлено ранее или неудачно отправлено, пропуск отправки.")
                return False
            if found_keywords:
                caption = f"Канал: {channel_name}\nНайденные ключевые слова: {', '.join(found_keywords)}"
                file_to_send = str(video_path)
            else:
                logger.info(f"Нет ключевых слов для {video_path.name}, видео не отправляется")
                return False
            file_size = os.path.getsize(file_to_send)
            file_size_mb = file_size / (1024 * 1024)
            logger.info(f"Отправка видео {os.path.basename(file_to_send)} ({file_size_mb:.2f} MB) в Telegram")
            max_attempts = 2
            for attempt in range(max_attempts):
                success = send_files([file_to_send], caption=caption)
                if success:
                    logger.info(f"Видео {os.path.basename(file_to_send)} успешно отправлено в Telegram")
                    with sent_videos_file.open('a', encoding='utf-8') as f:
                        f.write(video_name + '\n')
                    # Очистка папки после успешной отправки
                    self._cleanup_channel_video_folder(channel_name)
                    return True
                else:
                    logger.error(f"Не удалось отправить видео {os.path.basename(file_to_send)} в Telegram (попытка {attempt+1})")
            # После двух неудачных попыток
            logger.error(f"Видео {os.path.basename(file_to_send)} не удалось отправить после {max_attempts} попыток. Помещаем в failed_videos.txt и очищаем папку.")
            with failed_videos_file.open('a', encoding='utf-8') as f:
                f.write(video_name + '\n')
            self._cleanup_channel_video_folder(channel_name)
            return False
        except Exception as e:
            logger.error(f"Ошибка при отправке видео {video_path}: {e}")
            return False

    def _cleanup_channel_video_folder(self, channel_name):
        """
        Очищает папку lines_video/<channel_name> (удаляет все mp4-файлы).
        """
        try:
            channel_dir = Path("lines_video") / channel_name
            if channel_dir.exists() and channel_dir.is_dir():
                for file in channel_dir.glob("*.mp4"):
                    try:
                        file.unlink()
                        logger.info(f"Удалён файл {file} из папки {channel_dir}")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении файла {file}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при очистке папки lines_video/{channel_name}: {e}")

    def _start_watchdog_thread(self):
        def watchdog():
            while True:
                try:
                    with self._monitoring_threads_lock:
                        for thread in list(getattr(self, 'monitoring_threads', [])):
                            if not thread.is_alive():
                                logger.warning(f"Watchdog: Поток {thread.name} не отвечает!")
                    time_module.sleep(60)
                except Exception as e:
                    logger.error(f"Watchdog error: {e}")
        threading.Thread(target=watchdog, daemon=True).start()

    def _start_heartbeat_thread(self):
        def heartbeat():
            while True:
                logger.info("Heartbeat: приложение работает")
                time_module.sleep(300)
        threading.Thread(target=heartbeat, daemon=True).start()

    def _start_resource_monitor_thread(self):
        def resource_monitor():
            while True:
                try:
                    mem = psutil.virtual_memory()
                    disk = psutil.disk_usage('.')
                    if mem.percent > 85:
                        logger.warning(f"Использование памяти: {mem.percent}%")
                    if disk.percent > 90:
                        logger.warning(f"Использование диска: {disk.percent}%")
                    time_module.sleep(120)
                except Exception as e:
                    logger.error(f"Resource monitor error: {e}")
        threading.Thread(target=resource_monitor, daemon=True).start()

    def _start_hf_cache_cleaner_thread(self):
        def cache_cleaner():
            while True:
                try:
                    self.clear_hf_cache()
                    logger.info("Плановая очистка кэша Hugging Face API")
                    time_module.sleep(3600)
                except Exception as e:
                    logger.error(f"HF cache cleaner error: {e}")
        threading.Thread(target=cache_cleaner, daemon=True).start()

    def _start_temp_files_cleaner_thread(self):
        def temp_cleaner():
            while True:
                try:
                    self._cleanup_temp_files()
                    time_module.sleep(86400)
                except Exception as e:
                    logger.error(f"Temp files cleaner error: {e}")
        threading.Thread(target=temp_cleaner, daemon=True).start()

    def _cleanup_temp_files(self):
        # Удаляет старые временные файлы (скриншоты, видео, recognized_text)
        try:
            now = datetime.now().timestamp()
            folders = [Path('screenshots'), Path('screenshots_processed'), Path('video'), Path('lines_video'), Path('recognized_text')]
            for folder in folders:
                if folder.exists() and folder.is_dir():
                    for file in folder.rglob('*'):
                        if file.is_file():
                            try:
                                if now - file.stat().st_mtime > 3*86400:  # старше 3 дней
                                    file.unlink()
                                    logger.info(f"Удалён устаревший временный файл: {file}")
                            except Exception as e:
                                logger.error(f"Ошибка удаления временного файла {file}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при очистке временных файлов: {e}")

class StatusHandler(BaseHTTPRequestHandler):
    """
    HTTP-обработчик для получения статусов от дочерних процессов и обновления UI.
    """
    def __init__(self, ui_instance, *args, **kwargs):
        """
        Инициализация обработчика статусов.
        """
        self.ui = ui_instance
        super().__init__(*args, **kwargs)

    def do_POST(self):
        """
        Обработка POST-запроса для обновления статуса в UI.
        """
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = parse_qs(post_data.decode('utf-8'))
            
            if 'status' in params:
                status_message = params['status'][0]
                # Обновляем UI в основном потоке
                self.ui.root.after(0, self.ui.update_auto_recorder_status, status_message)
                
            self.send_response(200)
            self.end_headers()
        except Exception as e:
            logger.error(f"Ошибка в StatusHandler: {e}")
            self.send_response(500)
            self.end_headers()

    def log_message(self, format, *args):
        """
        Подавляет логирование запросов в консоль.
        """
        # Подавляем логирование запросов в консоль
        return

if __name__ == "__main__":
    app = MonitoringApp()
    try:
        app.ui.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения работы")
    except Exception as e:
        logger.error(f"Ошибка приложения: {e}")
    finally:
        app.cleanup()