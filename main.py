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

from UI import MonitoringUI
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging
from parser_lines import main as start_lines_monitoring, stop_subprocesses, start_force_capture, stop_force_capture
from lines_to_csv import process_screenshots, get_daily_file_path
from telegram_sender import send_files, send_report_files

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
    def __init__(self):
        self.logger = logger
        self.loop = None
        self.thread = None
        self.running = False
        self.scheduler_thread = None
        self.scheduler_running = False
        self.scheduler_paused = False
        self.start_time = time_module.time()
        self.last_lines_activity_time = self.start_time

        self.rbk_mir24_task = None
        self.rbk_mir24_running = False
        self.process_list = []
        self.recording_channels = []
        
        self.lines_monitoring_thread = None
        self.lines_monitoring_running = False

        # Переменные для обработки сюжетов
        self.video_processing_thread = None
        self.video_processing_running = False
        
        # Для запуска auto_recorder.py
        self.auto_recorder_process = None

        # Для видео-проверки (check_and_send_videos)
        self.video_recognition_running = False

        # Инициализируем event loop
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Запускаем event loop в отдельном потоке
        self.thread = threading.Thread(
            target=self.loop.run_forever,
            daemon=True
        )
        self.thread.start()

        # Создаем и запускаем UI
        self.ui = MonitoringUI(self)
        
        # Запускаем HTTP сервер для статусов
        self.start_status_server()
        
        # Запускаем планировщик
        self.start_scheduler()
        
        # Запускаем авто-рекордер
        self.start_auto_recorder()

    def start_auto_recorder(self):
        """Запускает auto_recorder.py в отдельном процессе."""
        try:
            python_executable = sys.executable
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auto_recorder.py")
            self.auto_recorder_process = subprocess.Popen([python_executable, script_path])
            logger.info(f"Процесс auto_recorder.py запущен с PID: {self.auto_recorder_process.pid}")
            self.ui.update_auto_recorder_status("Активен")
        except Exception as e:
            logger.error(f"Не удалось запустить auto_recorder.py: {e}")
            self.ui.update_auto_recorder_status(f"Ошибка: {e}")

    def start_status_server(self):
        """Запускает HTTP-сервер для получения статусов от дочерних процессов."""
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

    def start_scheduler(self):
        """Запуск планировщика задач."""
        if not self.scheduler_running:
            self.scheduler_running = True
            self.scheduler_thread = threading.Thread(
                target=self._run_scheduler,
                daemon=True
            )
            self.scheduler_thread.start()
            logger.info("Планировщик задач запущен")

    def _run_scheduler(self):
        logger.info("Настройка расписания задач...")
        self.ui.update_scheduler_status("Настройка расписания...")
        
        # Загрузка расписания из channels.json
        with open("channels.json", "r", encoding="utf-8") as f:
            channels = json.load(f)

        # Сопоставление каналов с методами запуска
        channel_methods = {
            "R1": self._start_r1_monitoring,
            "Zvezda": self._start_zvezda_monitoring,
            "TVC": self._start_other_channels_monitoring,
            "RenTV": self._start_other_channels_monitoring,
            "NTV": self._start_other_channels_monitoring,
        }

        for channel, info in channels.items():
            # Этот планировщик отвечает ТОЛЬКО за 'lines'
            lines_times = set(info.get("lines", []))
            schedule_times = set(info.get("schedule", []))
            
            if not lines_times:
                continue

            method = channel_methods.get(channel)
            if method:
                for t in lines_times:
                    if t in schedule_times:
                        logger.info(f"Пропуск расписания 'lines' для {channel} в {t}, так как оно совпадает с 'schedule'. Запись сюжета будет выполнена.")
                        continue
                    
                    schedule.every().day.at(t).do(method)
                    logger.info(f"Добавлено расписание для {channel} ('lines'): {t}")

        # Настройка отправки ежедневного файла в Telegram
        schedule.every().day.at("22:00").do(self._send_daily_file_to_telegram)
        logger.info("Добавлено расписание отправки ежедневного файла в Telegram: 22:00")

        # Новое: отправка файла с текстами скриншотов за день в 23:00
        schedule.every().day.at("23:00").do(self._send_daily_sent_texts_to_telegram)
        logger.info("Добавлено расписание отправки sent_texts_YYYYMMDD.txt в Telegram: 23:00")

        logger.info("Расписание настроено, начинаем выполнение...")
        self.ui.update_scheduler_status("Активен")
        while self.scheduler_running:
            try:
                if not self.scheduler_paused:
                    schedule.run_pending()
                
                # Проверка неактивности мониторинга строк
                self._check_and_start_idle_monitoring()

                time_module.sleep(1)
            except Exception as e:
                logger.error(f"Ошибка в планировщике: {e}")
                self.ui.update_scheduler_status(f"Ошибка: {str(e)}")

    def _start_r1_monitoring(self):
        """Запуск мониторинга для R1."""
        logger.info("Попытка запуска мониторинга R1...")
        self.ui.update_lines_scheduler_status("Запуск R1...")
        if not self.lines_monitoring_running:
            try:
                self.lines_monitoring_running = True
                self.last_lines_activity_time = time_module.time()
                start_force_capture()
                self.lines_monitoring_thread = threading.Thread(
                    target=start_lines_monitoring,
                    daemon=True
                )
                self.lines_monitoring_thread.start()
                logger.info("Запущен мониторинг R1 по расписанию")
                self.ui.update_lines_scheduler_status("R1 активен")
                
                # Запускаем периодическую проверку новых файлов
                def check_files():
                    while self.lines_monitoring_running:
                        self._check_and_send_new_files()
                        time_module.sleep(30)  # Проверяем каждые 30 секунд
                
                self.check_files_thread = threading.Thread(target=check_files, daemon=True)
                self.check_files_thread.start()
                
                # Останавливаем через 30 минут
                threading.Timer(1800, self._process_and_send_screenshots).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга R1: {e}")
                self.lines_monitoring_running = False
                self.ui.update_lines_scheduler_status(f"Ошибка R1: {str(e)}")
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск R1")
            self.ui.update_lines_scheduler_status("R1 пропущен (уже запущен)")

    def _start_zvezda_monitoring(self):
        """Запуск мониторинга для Zvezda."""
        logger.info("Попытка запуска мониторинга Zvezda...")
        self.ui.update_lines_scheduler_status("Запуск Zvezda...")
        if not self.lines_monitoring_running:
            try:
                self.lines_monitoring_running = True
                self.last_lines_activity_time = time_module.time()
                start_force_capture()
                self.lines_monitoring_thread = threading.Thread(
                    target=start_lines_monitoring,
                    daemon=True
                )
                self.lines_monitoring_thread.start()
                logger.info("Запущен мониторинг Zvezda по расписанию")
                self.ui.update_lines_scheduler_status("Zvezda активен")
                
                # Запускаем периодическую проверку новых файлов
                def check_files():
                    while self.lines_monitoring_running:
                        self._check_and_send_new_files()
                        time_module.sleep(30)  # Проверяем каждые 30 секунд
                
                self.check_files_thread = threading.Thread(target=check_files, daemon=True)
                self.check_files_thread.start()
                
                # Останавливаем через 10 минут
                threading.Timer(600, self._process_and_send_screenshots).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга Zvezda: {e}")
                self.lines_monitoring_running = False
                self.ui.update_lines_scheduler_status(f"Ошибка Zvezda: {str(e)}")
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск Zvezda")
            self.ui.update_lines_scheduler_status("Zvezda пропущен (уже запущен)")

    def _start_other_channels_monitoring(self):
        """Запуск мониторинга для остальных каналов."""
        logger.info("Попытка запуска мониторинга остальных каналов...")
        self.ui.update_lines_scheduler_status("Запуск других каналов...")
        if not self.lines_monitoring_running:
            try:
                self.lines_monitoring_running = True
                self.last_lines_activity_time = time_module.time()
                start_force_capture()
                self.lines_monitoring_thread = threading.Thread(
                    target=start_lines_monitoring,
                    daemon=True
                )
                self.lines_monitoring_thread.start()
                logger.info("Запущен мониторинг остальных каналов по расписанию")
                self.ui.update_lines_scheduler_status("Другие каналы активны")
                
                # Запускаем периодическую проверку новых файлов
                def check_files():
                    while self.lines_monitoring_running:
                        self._check_and_send_new_files()
                        time_module.sleep(30)  # Проверяем каждые 30 секунд
                
                self.check_files_thread = threading.Thread(target=check_files, daemon=True)
                self.check_files_thread.start()
                
                # Останавливаем через 20 минут
                threading.Timer(1200, self._process_and_send_screenshots).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга остальных каналов: {e}")
                self.lines_monitoring_running = False
                self.ui.update_lines_scheduler_status(f"Ошибка других каналов: {str(e)}")
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск остальных каналов")
            self.ui.update_lines_scheduler_status("Другие каналы пропущены (уже запущены)")

    def start_lines_monitoring(self):
        """Запуск мониторинга строк по кнопке."""
        logger.info("Попытка запуска мониторинга по кнопке...")
        if not self.lines_monitoring_running:
            try:
                self.lines_monitoring_running = True
                self.last_lines_activity_time = time_module.time()
                start_force_capture()
                self.lines_monitoring_thread = threading.Thread(
                    target=start_lines_monitoring,
                    daemon=True
                )
                self.lines_monitoring_thread.start()
                self.ui.update_lines_status("Запущен")
                logger.info("Запущен мониторинг строк по кнопке")
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга по кнопке: {e}")
                self.lines_monitoring_running = False
                messagebox.showerror("Ошибка", f"Не удалось запустить мониторинг: {e}")
        else:
            logger.warning("Мониторинг уже запущен")
            messagebox.showwarning("Предупреждение", "Мониторинг строк уже запущен")

    def stop_lines_monitoring(self):
        """Остановка мониторинга строк."""
        if self.lines_monitoring_running:
            self.lines_monitoring_running = False
            stop_force_capture()
            stop_subprocesses()
            if self.lines_monitoring_thread and self.lines_monitoring_thread.is_alive():
                self.lines_monitoring_thread.join(timeout=5.0)
            if hasattr(self, 'check_files_thread') and self.check_files_thread.is_alive():
                self.check_files_thread.join(timeout=5.0)
            self.lines_monitoring_thread = None
            self.ui.update_lines_status("Остановлен")
            logger.info("Остановлен мониторинг строк")
        else:
            messagebox.showwarning("Предупреждение", "Мониторинг строк уже остановлен")

    def start_rbk_mir24(self):
        """Запуск мониторинга RBK и MIR24 (ручной запуск)."""
        try:
            from rbk_mir24_parser import get_current_time_str, load_channels, process_rbk_mir24
            now_str = get_current_time_str()
            channels_data = load_channels()
            video_channels = ['RBK', 'MIR24', 'RenTV', 'NTV', 'TVC']
            channels_in_schedule = []
            channels_in_lines = []
            for name in video_channels:
                info = channels_data.get(name)
                if not info:
                    continue
                schedule_times = set(info.get("schedule", []))
                lines_times = set(info.get("lines", []))
                if now_str in schedule_times:
                    channels_in_schedule.append(name)
                if now_str in lines_times:
                    channels_in_lines.append(name)
            if channels_in_schedule:
                import tkinter
                messagebox.showwarning(
                    "Выпуск новостей",
                    f"Уже идет запись Выпуска новостей на телеканале(ах): {', '.join(channels_in_schedule)}"
                )
                return
            if channels_in_lines:
                import tkinter
                messagebox.showwarning(
                    "Бегущие строки",
                    "Бегущие строки уже записываются"
                )
                return
            # Если нет совпадений с schedule или lines, всегда запускаем crop-запись
            self.recording_channels.clear()
            self.recording_channels.extend(video_channels)
            for channel in video_channels:
                self.ui.update_recording_status(channel, True)
            self.process_list.clear()
            self.ui.update_status("Запуск записи RBK и MIR24 (crop)...")
            self.rbk_mir24_task = asyncio.run_coroutine_threadsafe(
                process_rbk_mir24(self, self.ui, True, channels=video_channels, force_crop=True),
                self.loop
            )
            self.ui.update_rbk_mir24_status("Запущен")
            logger.info("Запущен мониторинг RBK и MIR24 (crop)")
        except Exception as e:
            self.ui.update_rbk_mir24_status("Ошибка")
            self.ui.update_status(f"Ошибка запуска записи: {str(e)}")
            logger.error(f"Ошибка при запуске записи RBK и MIR24: {e}")
            messagebox.showerror("Ошибка", f"Не удалось запустить запись: {str(e)}")

    def stop_rbk_mir24(self):
        """Остановка мониторинга RBK и MIR24."""
        if self.rbk_mir24_running and self.loop is not None:
            try:
                for channel in self.recording_channels:
                    self.ui.update_recording_status(channel, False)
                self.recording_channels.clear()
                self.rbk_mir24_running = False
                self.ui.update_status("Остановка записи RBK и MIR24...")
                
                # Останавливаем задачу
                asyncio.run_coroutine_threadsafe(
                    stop_rbk_mir24(self, self.ui),
                    self.loop
                )
                
                self.ui.update_rbk_mir24_status("Остановлен")
                logger.info("Остановлен мониторинг RBK и MIR24")
            except Exception as e:
                self.ui.update_status(f"Ошибка остановки записи: {str(e)}")
                logger.error(f"Ошибка при остановке записи RBK и MIR24: {e}")
                messagebox.showerror("Ошибка", f"Не удалось остановить запись: {str(e)}")
        else:
            messagebox.showwarning("Предупреждение", "Мониторинг RBK и MIR24 уже остановлен или event loop не инициализирован")

    def save_and_send_lines(self):
        """Запускает полный цикл проверки скриншотов, фильтрации и отправки в Telegram."""
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

    def _save_and_send_lines_task(self):
        """Задача для проверки, фильтрации и отправки скриншотов."""
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
            
            files_with_keywords = []
            file_captions = {}
            
            all_files = list(screenshots_dir.rglob("*.[jp][pn]g")) 
            logger.info(f"Найдено {len(all_files)} скриншотов для обработки.")
            
            keywords = self._load_keywords()
            # Для хранения текстов уже отправленных скриншотов за сегодня
            today_str = datetime.now().strftime('%Y%m%d')
            sent_texts_file = f'sent_texts_{today_str}.txt'
            sent_texts = []
            if os.path.exists(sent_texts_file):
                with open(sent_texts_file, 'r', encoding='utf-8') as f:
                    sent_texts = [line.strip() for line in f if line.strip()]
            session_texts = []  # Для хранения текстов в рамках одной обработки
            for file_path in all_files:
                recognized_text = self._extract_text_from_image(file_path)
                text_lower = recognized_text.lower()
                has_keyword = any(kw in text_lower for kw in keywords)
                is_duplicate = False
                # Проверка на дубликаты по схожести текста (сначала по сегодняшнему файлу, потом по сессии)
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
            # После отправки файлов — добавляем тексты в файл за день
            if files_with_keywords:
                with open(sent_texts_file, 'a', encoding='utf-8') as f:
                    for file_path in files_with_keywords:
                        text = self._extract_text_from_image(file_path).lower()
                        f.write(text + '\n')
            
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

    def _process_and_send_screenshots(self):
        """Обработка и отправка скриншотов."""
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
        """Отправка ежедневного файла в Telegram."""
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
        """Отправка файла с текстами отправленных скриншотов за день в Telegram."""
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            sent_texts_file = f'sent_texts_{today_str}.txt'
            if os.path.exists(sent_texts_file):
                logger.info(f"Отправка файла с текстами скриншотов за день в Telegram: {sent_texts_file}")
                self.ui.update_status("Отправка файла с текстами скриншотов за день в Telegram...")
                from telegram_sender import send_report_files
                send_report_files(sent_texts_file, [])
                self.ui.update_status("Файл с текстами скриншотов за день отправлен в Telegram")
                logger.info("Файл с текстами скриншотов за день успешно отправлен в Telegram")
            else:
                logger.warning("Файл с текстами скриншотов за день не найден для отправки")
                self.ui.update_status("Файл с текстами скриншотов за день не найден")
        except Exception as e:
            logger.error(f"Ошибка при отправке файла с текстами скриншотов за день в Telegram: {e}")
            self.ui.update_status(f"Ошибка отправки файла с текстами скриншотов за день: {str(e)}")

    def _check_and_send_new_files(self):
        """Проверка и отправка новых файлов."""
        try:
            # Проверяем новые скриншоты
            screenshots_dir = "screenshots"
            if os.path.exists(screenshots_dir):
                new_files = []
                for filename in os.listdir(screenshots_dir):
                    if filename.endswith('.jpg') and not filename.startswith('processed_'):
                        file_path = os.path.join(screenshots_dir, filename)
                        # Проверяем, что файл не старше 5 минут
                        if time_module.time() - os.path.getmtime(file_path) < 300:
                            new_files.append(file_path)
                
                if new_files:
                    logger.info(f"Найдено {len(new_files)} новых файлов для отправки")
                    self.ui.update_status(f"Отправка {len(new_files)} файлов...")
                    
                    # Отправляем файлы в Telegram
                    for file_path in new_files:
                        try:
                            send_files([file_path])
                            # Переименовываем файл как обработанный
                            processed_path = os.path.join(screenshots_dir, f"processed_{os.path.basename(file_path)}")
                            os.rename(file_path, processed_path)
                            logger.info(f"Файл {file_path} отправлен и помечен как обработанный")
                        except Exception as e:
                            logger.error(f"Ошибка при отправке файла {file_path}: {e}")
                    
                    self.ui.update_status(f"Отправлено {len(new_files)} файлов")
        except Exception as e:
            logger.error(f"Ошибка при проверке новых файлов: {e}")

    def check_and_send_videos(self):
        """Запускает полный цикл проверки видео и отправки в Telegram."""
        if self.video_recognition_running:
            messagebox.showwarning("Предупреждение", "Проверка видео уже запущена.")
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
            logger.error(f"Ошибка при запуске проверки и отправки видео: {e}")
            self.video_recognition_running = False
            self.ui.update_video_check_status("Ошибка")
            messagebox.showerror("Ошибка", f"Не удалось запустить процесс: {e}")

    def _run_check_and_send_task(self):
        """Задача, выполняющая распознавание, поиск и отправку видео."""
        summary_title = "Результат проверки видео"
        try:
            video_dir = Path("lines_video")
            if not video_dir.exists() or not any(video_dir.glob("**/*.mp4")):
                logger.warning("В папке lines_video нет видео для проверки.")
                self.ui.root.after(0, self.ui.update_status, "Видео для проверки не найдены.")
                self.ui.root.after(0, messagebox.showinfo, summary_title, "В папке `lines_video` нет файлов для проверки.")
                return

            # --- Этап 1: Распознавание текста из видео ---
            logger.info("Начало распознавания текста из видео")
            self.ui.root.after(0, self.ui.update_status, "Распознавание текста из видео...")
            self._recognize_text_in_videos_to_channel_txt(video_dir)
            logger.info("Распознавание завершено.")
            self.ui.root.after(0, self.ui.update_status, "Распознавание текста из видео завершено.")

            # --- Этап 2: Поиск ключевых слов и отправка видео ---
            self.ui.root.after(0, self.ui.update_video_check_status, "Выполняется: Поиск ключевых слов...")
            logger.info("Поиск ключевых слов и их вариаций через Hugging Face API")
            videos_to_send = self._get_videos_with_keywords_hf_channelwise()

            if not videos_to_send:
                self.ui.root.after(0, self.ui.update_status, "Видео с ключевыми словами не найдены. Очистка...")
                logger.info("Видео с ключевыми словами не найдены. Все видеофайлы будут удалены.")
                self._cleanup_video_files()
                self._cleanup_recognized_texts_channelwise()
                self.ui.root.after(0, messagebox.showinfo, summary_title, "Проверка завершена. Видео с ключевыми словами не найдены. Все видеофайлы удалены.")
                return

            logger.info(f"Найдено {len(videos_to_send)} видео с ключевыми словами")
            self.ui.root.after(0, self.ui.update_status, f"Отправка {len(videos_to_send)} видео...")

            sent_count = 0
            for video_info in videos_to_send:
                try:
                    video_path = video_info['video_path']
                    channel_name = video_info['channel']
                    found_keywords = video_info['found_keywords']
                    if self._send_single_video_to_telegram(video_path, channel_name, found_keywords):
                        sent_count += 1
                        logger.info(f"Видео {video_path.name} отправлено в Telegram")
                        video_path.unlink(missing_ok=True)
                        self._remove_video_text_from_channel_txt(video_path.name, channel_name)
                    else:
                        logger.error(f"Не удалось отправить видео {video_path.name}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке видео {video_info.get('video_path', 'unknown')}: {e}")

            self._cleanup_video_files()
            self._cleanup_recognized_texts_channelwise()

            final_status_msg = f"Отправлено {sent_count} из {len(videos_to_send)} видео. Очистка завершена."
            self.ui.root.after(0, self.ui.update_status, final_status_msg)
            logger.info(f"Отправка завершена. Отправлено {sent_count} видео, все файлы удалены")

            summary_message = f"Отправка завершена.\n\nНайдено видео с ключевыми словами: {len(videos_to_send)}\nУспешно отправлено: {sent_count}"
            if sent_count < len(videos_to_send):
                summary_message += "\n\nНекоторые видео не удалось отправить. Подробности смотрите в логах."
            self.ui.root.after(0, messagebox.showinfo, summary_title, summary_message)

        except Exception as e:
            logger.error(f"Ошибка в процессе проверки и отправки видео: {e}")
            self.ui.root.after(0, self.ui.update_status, f"Ошибка: {str(e)}")
            self.ui.root.after(0, self.ui.update_video_check_status, "Ошибка")
            self.ui.root.after(0, messagebox.showerror, "Ошибка", f"В процессе проверки произошла ошибка:\n{e}")
        finally:
            self.video_recognition_running = False
            self.ui.root.after(0, self.ui.update_video_check_status, "Завершено")

    def _recognize_text_in_videos_to_channel_txt(self, video_dir):
        """Распознаёт текст из всех видеофайлов в lines_video и сохраняет результаты в отдельные txt по каналам."""
        recognized_dir = Path("recognized_text")
        recognized_dir.mkdir(exist_ok=True)
        channel_files = {}
        for channel_dir in video_dir.iterdir():
            if not channel_dir.is_dir():
                continue
            channel_name = channel_dir.name
            txt_path = recognized_dir / f"{channel_name}.txt"
            if channel_name not in channel_files:
                channel_files[channel_name] = open(txt_path, 'w', encoding='utf-8')
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
                    recognized_texts = []
                    frame_idx = 0
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        if frame_idx % step == 0:
                            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                            text = pytesseract.image_to_string(gray, lang='rus+eng')
                            recognized_texts.append(text.replace('\n', ' '))
                        frame_idx += 1
                    cap.release()
                    all_text = ' '.join(recognized_texts).replace('\n', ' ')
                    txt_file.write(f"{video_file.name}\t{all_text}\n")
                    logger.info(f"Распознан текст для {video_file.name}")
                except Exception as e:
                    logger.error(f"Ошибка при распознавании текста в {video_file}: {e}")
        for f in channel_files.values():
            f.close()

    def _get_videos_with_keywords_hf_channelwise(self):
        """Проверяет recognized_text/<channel>.txt на наличие ключевых слов и их вариаций через Hugging Face API."""
        recognized_dir = Path("recognized_text")
        keywords = list(self._load_keywords())
        videos_to_send = []
        for txt_path in recognized_dir.glob("*.txt"):
            channel_name = txt_path.stem
            with open(txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        video_file, text = line.strip().split('\t', 1)
                        found_keywords = self._find_keywords_hf(text, keywords)
                        if found_keywords:
                            videos_to_send.append({
                                'video_path': Path("lines_video") / channel_name / video_file,
                                'channel': channel_name,
                                'found_keywords': found_keywords
                            })
                    except Exception as e:
                        logger.error(f"Ошибка при обработке строки recognized_text/{txt_path.name}: {e}")
        return videos_to_send

    def _remove_video_text_from_channel_txt(self, video_file_name, channel_name):
        """Удаляет строку из recognized_text/<channel>.txt по имени видеофайла."""
        txt_path = Path("recognized_text") / f"{channel_name}.txt"
        if not txt_path.exists():
            return
        lines = []
        with open(txt_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(txt_path, 'w', encoding='utf-8') as f:
            for line in lines:
                if not line.startswith(video_file_name + '\t'):
                    f.write(line)

    def _cleanup_recognized_texts_channelwise(self):
        """Удаляет все recognized_text/<channel>.txt файлы."""
        recognized_dir = Path("recognized_text")
        for txt_path in recognized_dir.glob("*.txt"):
            try:
                txt_path.unlink()
            except Exception:
                pass

    def cleanup(self):
        """Очистка ресурсов при закрытии приложения."""
        try:
            logger.info("Начало очистки ресурсов...")
            
            # Останавливаем планировщик
            if self.scheduler_running:
                self.scheduler_running = False
                logger.info("Планировщик остановлен")
            
            # Останавливаем мониторинг строк
            if self.lines_monitoring_running:
                stop_force_capture()
                self.lines_monitoring_running = False
                logger.info("Мониторинг строк остановлен")
            
            # Останавливаем RBK и MIR24
            if self.rbk_mir24_running:
                stop_rbk_mir24()
                self.rbk_mir24_running = False
                logger.info("RBK и MIR24 остановлены")
            
            # Останавливаем распознавание видео
            if self.video_recognition_running:
                self.video_recognition_running = False
                if self.video_recognition_thread and self.video_recognition_thread.is_alive():
                    self.video_recognition_thread.join(timeout=5)
                logger.info("Распознавание видео остановлено")
            
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

    def pause_scheduler(self):
        """Приостановка выполнения задач по расписанию."""
        if not self.scheduler_paused:
            self.scheduler_paused = True
            logger.info("Планировщик приостановлен.")
            self.ui.update_scheduler_status("Приостановлен")
            self.ui.toggle_scheduler_buttons(paused=True)

    def resume_scheduler(self):
        """Возобновление выполнения задач по расписанию."""
        if self.scheduler_paused:
            self.scheduler_paused = False
            logger.info("Планировщик возобновлен.")
            self.ui.update_scheduler_status("Активен")
            self.ui.toggle_scheduler_buttons(paused=False)

    def _check_and_start_idle_monitoring(self):
        """Проверяет время неактивности и запускает мониторинг, если нужно."""
        if self.lines_monitoring_running or self.scheduler_paused:
            return

        idle_timeout = 15 * 60  # 15 минут
        if time_module.time() - self.last_lines_activity_time > idle_timeout:
            logger.info(f"Не было активности мониторинга строк более {idle_timeout / 60:.0f} минут. Запускаю стандартный сеанс мониторинга.")
            self._start_other_channels_monitoring()

    def start_video_processing(self):
        """Запускает скрипт обработки видеосюжетов в отдельном потоке."""
        if self.video_processing_running:
            messagebox.showwarning("Предупреждение", "Обработка сюжетов уже запущена.")
            return

        try:
            self.video_processing_running = True
            self.ui.update_video_processing_status("Выполняется...")
            
            self.video_processing_thread = threading.Thread(
                target=self._run_video_processing_task,
                daemon=True
            )
            self.video_processing_thread.start()
            
        except Exception as e:
            logger.error(f"Ошибка при запуске обработки сюжетов: {e}")
            self.video_processing_running = False
            self.ui.update_video_processing_status("Ошибка")
            messagebox.showerror("Ошибка", f"Не удалось запустить процесс обработки сюжетов: {e}")

    def _run_video_processing_task(self):
        """Задача, выполняющая запуск video_processor.py."""
        try:
            python_executable = sys.executable
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video_processor.py")
            
            process = subprocess.Popen(
                [python_executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            
            # Логируем вывод скрипта в реальном времени
            for line in process.stdout:
                logger.info(f"[VideoProcessor]: {line.strip()}")
            
            stderr_output = process.stderr.read()
            if stderr_output:
                logger.error(f"[VideoProcessor Error]: {stderr_output.strip()}")

            process.wait()

            if process.returncode == 0:
                logger.info("Обработка сюжетов успешно завершена.")
                self.ui.root.after(0, self.ui.update_video_processing_status, "Завершено")
                self.ui.root.after(0, messagebox.showinfo, "Успех", "Обработка видеосюжетов успешно завершена.")
            else:
                logger.error(f"Скрипт обработки сюжетов завершился с ошибкой (код: {process.returncode}).")
                self.ui.root.after(0, self.ui.update_video_processing_status, "Ошибка")
                self.ui.root.after(0, messagebox.showerror, "Ошибка", f"Обработка сюжетов завершилась с ошибкой. Подробности в логах.")

        except Exception as e:
            logger.error(f"Критическая ошибка в задаче обработки сюжетов: {e}")
            self.ui.root.after(0, self.ui.update_video_processing_status, "Критическая ошибка")
        finally:
            self.video_processing_running = False
            # Статус уже обновлен, но можно поставить "Ожидание", если нужно
            # self.ui.root.after(0, self.ui.update_video_processing_status, "Ожидание")

    def _extract_text_from_image(self, image_path):
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
        try:
            with open('keywords.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(word.lower() for word in data['keywords'])
        except Exception as e:
            logger.error(f"Ошибка при загрузке ключевых слов: {e}")
            return set()

    def _find_keywords_hf(self, text, keywords):
        """Использует Hugging Face Inference API (Qwen/Qwen2.5-VL-7B-Instruct) для поиска вариаций ключевых слов в тексте."""
        HF_API_URL = "https://api-inference.huggingface.co/models/Qwen/Qwen2.5-VL-7B-Instruct"
        HF_API_TOKEN = os.environ.get("HF_API_TOKEN")  # Токен должен быть в переменных окружения
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        found = []
        for kw in keywords:
            prompt = (
                f"Instruction: Найди, встречается ли ключевое слово или его смысловая вариация в этом тексте?\n"
                f"Ключевое слово: \"{kw}\"\n"
                f"Текст: \"{text}\"\n"
                f"Ответь только 'yes' или 'no'."
            )
            payload = {"inputs": prompt}
            try:
                response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=60)
                if response.status_code == 200:
                    result = response.json()
                    # Ответ может быть строкой или списком с dict/text
                    answer = ""
                    if isinstance(result, dict) and "generated_text" in result:
                        answer = result["generated_text"].strip().lower()
                    elif isinstance(result, list) and result and "generated_text" in result[0]:
                        answer = result[0]["generated_text"].strip().lower()
                    elif isinstance(result, str):
                        answer = result.strip().lower()
                    if "yes" in answer:
                        found.append(kw)
                else:
                    logger.warning(f"HF API error: {response.status_code} {response.text}")
            except Exception as e:
                logger.error(f"Ошибка Hugging Face API: {e}")
        return found

    def _cleanup_video_files(self):
        """Удаляет все видеофайлы из lines_video, если они остались."""
        video_dir = Path("lines_video")
        if not video_dir.exists():
            return
        for channel_dir in video_dir.iterdir():
            if not channel_dir.is_dir():
                continue
            for video_file in channel_dir.glob("*.mp4"):
                try:
                    video_file.unlink()
                except Exception:
                    pass

class StatusHandler(BaseHTTPRequestHandler):
    def __init__(self, ui_instance, *args, **kwargs):
        self.ui = ui_instance
        super().__init__(*args, **kwargs)

    def do_POST(self):
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