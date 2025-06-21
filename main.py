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

from UI import MonitoringUI
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging
from parser_lines import main as start_lines_monitoring, stop_subprocesses, start_force_capture, stop_force_capture
from lines_to_csv import process_screenshots, get_daily_file_path
from telegram_sender import send_files, send_report_files
from video_text_recognition import VideoTextRecognizer

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

        # Переменные для распознавания видео
        self.video_recognition_thread = None
        self.video_recognition_running = False
        self.video_recognizer = None
        
        # Для запуска auto_recorder.py
        self.auto_recorder_process = None

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
            times = info.get("lines", [])
            if not times:
                continue
            method = channel_methods.get(channel)
            if method:
                for t in times:
                    schedule.every().day.at(t).do(method)
                    logger.info(f"Добавлено расписание для {channel}: {t}")

        # Настройка отправки ежедневного файла в Telegram
        schedule.every().day.at("22:00").do(self._send_daily_file_to_telegram)
        logger.info("Добавлено расписание отправки ежедневного файла в Telegram: 22:00")

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

    def _recognize_text_from_image(self, recognizer: VideoTextRecognizer, image_path: str) -> List[str]:
        """Распознает текст на изображении и проверяет наличие ключевых слов."""
        try:
            frame = cv2.imread(image_path)
            if frame is None:
                logger.warning(f"Не удалось прочитать изображение: {image_path}")
                return []
            
            results = recognizer.easyocr_reader.readtext(frame)
            
            found_keywords = []
            full_text = " ".join([res[1] for res in results])
            text_lower = full_text.lower()

            for keyword in recognizer.keywords:
                if keyword.lower() in text_lower:
                    found_keywords.append(keyword)
            
            if found_keywords:
                logger.info(f"Найдены ключевые слова {found_keywords} в файле {image_path}")
            return list(set(found_keywords))
            
        except Exception as e:
            logger.error(f"Ошибка при распознавании текста с изображения {image_path}: {e}")
            return []

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
            
            recognizer = VideoTextRecognizer() 
            files_with_keywords = []
            
            all_files = list(screenshots_dir.rglob("*.[jp][pn]g")) 
            logger.info(f"Найдено {len(all_files)} скриншотов для обработки.")
            
            for file_path in all_files:
                keywords_found = self._recognize_text_from_image(recognizer, str(file_path))
                if keywords_found:
                    try:
                        new_path = processed_dir / file_path.name
                        file_path.rename(new_path)
                        files_with_keywords.append(new_path)
                        logger.info(f"Файл {file_path.name} перемещен в {processed_dir}")
                    except Exception as e:
                        logger.error(f"Не удалось переместить файл {file_path.name}: {e}")
                else:
                    try:
                        file_path.unlink() 
                        logger.info(f"Файл {file_path.name} удален (нет ключевых слов).")
                    except Exception as e:
                        logger.error(f"Не удалось удалить файл {file_path.name}: {e}")
            
            if not files_with_keywords:
                self.ui.root.after(0, messagebox.showinfo, summary_title, "Обработка завершена. Файлов с ключевыми словами не найдено.")
                self.ui.root.after(0, self.ui.update_processing_status, "Ожидание")
                return

            self.ui.root.after(0, self.ui.update_processing_status, f"Отправка {len(files_with_keywords)} файлов в Telegram...")
            sent_count = 0
            
            for file_path in files_with_keywords:
                caption = f"Обнаружены ключевые слова в файле: {file_path.name}"
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
            # Предварительная проверка на наличие видеофайлов
            video_dir = Path("lines_video")
            if not video_dir.exists() or not any(video_dir.glob("**/*.mp4")):
                logger.warning("В папке lines_video нет видео для проверки.")
                self.ui.root.after(0, self.ui.update_status, "Видео для проверки не найдены.")
                self.ui.root.after(0, messagebox.showinfo, summary_title, "В папке `lines_video` нет файлов для проверки.")
                return

            # --- Этап 1: Распознавание текста из видео ---
            logger.info("Начало распознавания текста из видео")
            self.ui.root.after(0, self.ui.update_status, "Распознавание текста из видео...")
            
            recognizer = VideoTextRecognizer(
                video_dir="lines_video",
                output_dir="recognized_text",
                keep_screenshots=False
            )
            results = recognizer.process_all_channels()
            
            total_texts = sum(len(texts) for texts in results.values())
            if total_texts > 0:
                logger.info(f"Распознавание завершено. Найдено {total_texts} текстов")
                self.ui.root.after(0, self.ui.update_status, f"Распознано {total_texts} текстов.")
            else:
                logger.info("Распознавание завершено. Тексты не найдены.")
                self.ui.root.after(0, self.ui.update_status, "Тексты в видео не найдены.")

            # --- Этап 2: Отправка видео с ключевыми словами в Telegram ---
            self.ui.root.after(0, self.ui.update_video_check_status, "Выполняется: Отправка в ТГ...")
            logger.info("Начало обработки видео для отправки в Telegram")
            self.ui.root.after(0, self.ui.update_status, "Поиск видео с ключевыми словами...")
            
            videos_with_keywords = self._get_videos_with_keywords()
            
            if not videos_with_keywords:
                self.ui.root.after(0, self.ui.update_status, "Видео с ключевыми словами не найдены. Очистка...")
                logger.info("Видео с ключевыми словами не найдены. Все видеофайлы будут удалены.")
                self._cleanup_video_files()
                self.ui.root.after(0, messagebox.showinfo, summary_title, "Проверка завершена. Видео с ключевыми словами не найдены. Все видеофайлы удалены.")
                return
            
            logger.info(f"Найдено {len(videos_with_keywords)} видео с ключевыми словами")
            self.ui.root.after(0, self.ui.update_status, f"Отправка {len(videos_with_keywords)} видео...")
            
            sent_count = 0
            total_to_send = len(videos_with_keywords)
            for video_info in videos_with_keywords:
                try:
                    video_path = video_info['video_path']
                    channel_name = video_info['channel']
                    found_keywords = video_info['found_keywords']
                    
                    if self._send_single_video_to_telegram(video_path, channel_name, found_keywords):
                        sent_count += 1
                        logger.info(f"Видео {video_path.name} отправлено в Telegram")
                    else:
                        logger.error(f"Не удалось отправить видео {video_path.name}")
                        
                except Exception as e:
                    logger.error(f"Ошибка при отправке видео {video_info.get('video_path', 'unknown')}: {e}")
            
            self._cleanup_video_files()
            
            final_status_msg = f"Отправлено {sent_count} из {total_to_send} видео. Очистка завершена."
            self.ui.root.after(0, self.ui.update_status, final_status_msg)
            logger.info(f"Отправка завершена. Отправлено {sent_count} видео, все файлы удалены")
            
            summary_message = f"Отправка завершена.\n\nНайдено видео с ключевыми словами: {total_to_send}\nУспешно отправлено: {sent_count}"
            if sent_count < total_to_send:
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

    def _get_videos_with_keywords(self):
        """Получение списка видео файлов с ключевыми словами."""
        videos_with_keywords = []
        video_dir = Path("lines_video") # Используем lines_video
        
        try:
            if not video_dir.exists():
                logger.warning("Папка lines_video не найдена")
                return videos_with_keywords
            
            for channel_dir in video_dir.iterdir():
                if not channel_dir.is_dir():
                    continue
                channel_name = channel_dir.name
                
                for video_file in channel_dir.glob("*.mp4"):
                    try:
                        keywords = self._get_video_keywords(video_file)
                        if keywords:
                            videos_with_keywords.append({
                                'video_path': video_file,
                                'channel': channel_name,
                                'found_keywords': keywords
                            })
                            logger.info(f"Видео {video_file.name} содержит ключевые слова: {keywords}")
                    except Exception as e:
                        logger.error(f"Ошибка при проверке видео {video_file}: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка при поиске видео с ключевыми словами: {e}")
        
        return videos_with_keywords

    def _get_video_keywords(self, video_file):
        """Получение списка ключевых слов для видео."""
        all_keywords = set()
        recognized_dir = Path("recognized_text")
        if not recognized_dir.exists():
            return []
        
        video_name_stem = video_file.stem
        
        try:
            # Ищем JSON-файл, который соответствует видео
            # Имя файла с результатами может быть длиннее, например, video_name_channel_timestamp.json
            for json_file in recognized_dir.glob(f"*{video_name_stem}*.json"):
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Структура JSON: список словарей
                if isinstance(data, list):
                    for item in data:
                        # Убедимся, что это результат для нашего видеофайла
                        if item.get('video_file') == video_file.name:
                            found_keywords = item.get('found_keywords', [])
                            if found_keywords:
                                all_keywords.update(found_keywords)
        except Exception as e:
            logger.error(f"Ошибка при чтении ключевых слов из JSON для видео {video_file.name}: {e}")
        
        return list(all_keywords)

    def _send_single_video_to_telegram(self, video_path, channel_name, found_keywords):
        """Отправка одного видео файла в Telegram."""
        try:
            keywords_text = ", ".join(found_keywords) if found_keywords else "не указаны"
            caption = f"Канал: {channel_name}\nКлючевые слова: {keywords_text}\nФайл: {video_path.name}"
            
            from telegram_sender import send_files
            return send_files([str(video_path)], caption=caption)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке видео {video_path}: {e}")
            return False

    def _cleanup_video_files(self):
        """Удаление всех видео файлов после обработки из lines_video."""
        try:
            video_dir = Path("lines_video")
            if not video_dir.exists():
                return
            
            deleted_count = 0
            
            for channel_dir in video_dir.iterdir():
                if not channel_dir.is_dir():
                    continue
                
                for video_file in channel_dir.glob("*.mp4"):
                    try:
                        video_file.unlink()
                        deleted_count += 1
                        logger.info(f"Удален видео файл: {video_file}")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении {video_file}: {e}")
            
            logger.info(f"Удалено {deleted_count} видео файлов")
            
        except Exception as e:
            logger.error(f"Ошибка при очистке видео файлов: {e}")

    def cleanup(self):
        """Очистка ресурсов при закрытии приложения."""
        try:
            logger.info("Начало очистки ресурсов...")
            
            # Останавливаем auto_recorder
            if self.auto_recorder_process:
                logger.info("Остановка процесса auto_recorder.py...")
                self.auto_recorder_process.terminate()
                self.auto_recorder_process.wait(timeout=5)
                logger.info("Процесс auto_recorder.py остановлен.")
            
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