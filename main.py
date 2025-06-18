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

from UI import MonitoringUI
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging
from parser_lines import main as start_lines_monitoring, stop_subprocesses, start_force_capture, stop_force_capture
from lines_to_csv import process_screenshots, get_daily_file_path
from telegram_sender import send_files
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

        self.rbk_mir24_task = None
        self.rbk_mir24_running = False
        self.process_list = []
        
        self.lines_monitoring_thread = None
        self.lines_monitoring_running = False

        # Переменные для распознавания видео
        self.video_recognition_thread = None
        self.video_recognition_running = False
        self.video_recognizer = None

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
        
        # Запускаем планировщик
        self.start_scheduler()

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
        """Выполнение планировщика задач."""
        logger.info("Настройка расписания задач...")
        self.ui.update_scheduler_status("Настройка расписания...")
        
        # Настройка расписания для R1
        for hour in range(5, 10):
            for minute in [0, 30]:
                time_str = f"{hour:02d}:{minute:02d}"
                schedule.every().day.at(time_str).do(self._start_r1_monitoring)
                logger.info(f"Добавлено расписание для R1: {time_str}")

        # Настройка расписания для Zvezda
        for time_str in ["09:00", "13:00", "17:00", "19:00"]:
            schedule.every().day.at(time_str).do(self._start_zvezda_monitoring)
            logger.info(f"Добавлено расписание для Zvezda: {time_str}")

        # Настройка расписания для остальных каналов
        schedule.every(20).minutes.do(self._start_other_channels_monitoring)
        logger.info("Добавлено расписание для остальных каналов: каждые 20 минут")

        # Настройка расписания для RBK и MIR24
        schedule.every(20).minutes.do(self._start_rbk_mir24_monitoring)
        logger.info("Добавлено расписание для RBK и MIR24: каждые 20 минут")

        # Настройка расписания для RenTV
        for time_str in ["08:30", "12:30", "16:30", "19:30", "23:00"]:
            schedule.every().day.at(time_str).do(self._start_rentv_monitoring)
            logger.info(f"Добавлено расписание для RenTV: {time_str}")

        # Настройка расписания для NTV
        for time_str in ["08:00", "10:00", "13:00", "16:00", "19:00"]:
            schedule.every().day.at(time_str).do(self._start_ntv_monitoring)
            logger.info(f"Добавлено расписание для NTV: {time_str}")

        # Настройка расписания для TVC
        for time_str in ["11:30", "14:30", "17:50", "22:00"]:
            schedule.every().day.at(time_str).do(self._start_tvc_monitoring)
            logger.info(f"Добавлено расписание для TVC: {time_str}")

        # Настройка отправки ежедневного файла в Telegram
        schedule.every().day.at("22:00").do(self._send_daily_file_to_telegram)
        logger.info("Добавлено расписание отправки ежедневного файла в Telegram: 22:00")

        logger.info("Расписание настроено, начинаем выполнение...")
        self.ui.update_scheduler_status("Активен")
        while self.scheduler_running:
            try:
                schedule.run_pending()
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
        """Запуск мониторинга RBK и MIR24."""
        if not self.rbk_mir24_running and self.loop is not None:
            try:
                self.rbk_mir24_running = True
                self.process_list.clear()
                self.ui.update_status("Запуск записи RBK и MIR24...")
                
                # Запускаем запись
                self.rbk_mir24_task = asyncio.run_coroutine_threadsafe(
                    process_rbk_mir24(self, self.ui, True),
                    self.loop
                )
                
                self.ui.update_rbk_mir24_status("Запущен")
                logger.info("Запущен мониторинг RBK и MIR24")
            except Exception as e:
                self.rbk_mir24_running = False
                self.ui.update_rbk_mir24_status("Ошибка")
                self.ui.update_status(f"Ошибка запуска записи: {str(e)}")
                logger.error(f"Ошибка при запуске записи RBK и MIR24: {e}")
                messagebox.showerror("Ошибка", f"Не удалось запустить запись: {str(e)}")
        else:
            messagebox.showwarning("Предупреждение", "Мониторинг RBK и MIR24 уже запущен или event loop не инициализирован")

    def stop_rbk_mir24(self):
        """Остановка мониторинга RBK и MIR24."""
        if self.rbk_mir24_running and self.loop is not None:
            try:
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

    def start_save_to_csv(self):
        """Запуск сохранения строк в CSV."""
        try:
            self.ui.update_status("Сохранение строк...")
            
            # Останавливаем текущий мониторинг, если он запущен
            if self.lines_monitoring_running:
                self.stop_lines_monitoring()
                # Даем время на корректное завершение предыдущего мониторинга
                time_module.sleep(2)
            
            # Запускаем принудительный захват
            start_force_capture()
            
            # Запускаем мониторинг в отдельном потоке
            self.lines_monitoring_running = True
            self.lines_monitoring_thread = threading.Thread(
                target=start_lines_monitoring,
                daemon=True
            )
            self.lines_monitoring_thread.start()
            
            # Ждем 30 секунд для сбора данных
            time_module.sleep(30)
            
            # Останавливаем мониторинг
            self.stop_lines_monitoring()
            
            # Запускаем процесс сохранения в отдельном потоке
            thread = threading.Thread(
                target=self._save_to_csv_task,
                daemon=True
            )
            thread.start()
        except Exception as e:
            logger.error(f"Ошибка при запуске сохранения в CSV: {e}")
            self.ui.update_status("Ошибка при сохранении в CSV")
            messagebox.showerror("Ошибка", f"Не удалось сохранить строки в CSV: {e}")

    def _save_to_csv_task(self):
        """Задача сохранения строк в CSV."""
        try:
            # Используем существующий event loop для запуска process_screenshots
            future = asyncio.run_coroutine_threadsafe(process_screenshots(), self.loop)
            result = future.result(timeout=60)  # Ждем завершения задачи с таймаутом 60 секунд
            logger.info(f"Результат process_screenshots: {result}")
            
            if isinstance(result, tuple) and len(result) == 2:
                output_file, screenshots = result
                if output_file:
                    self.ui.update_status(f"Сохранено в {output_file}")
                    messagebox.showinfo("Успех", f"Строки сохранены в файл: {output_file}")
                else:
                    self.ui.update_status("Ошибка сохранения: результат пустой")
                    messagebox.showerror("Ошибка", "Не удалось сохранить строки в CSV: пустой результат")
            else:
                logger.error(f"Некорректный формат результата: {result}")
                self.ui.update_status("Ошибка: неверный формат результата")
                messagebox.showerror("Ошибка", f"Неверный формат результата при сохранении в CSV: {result}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении в CSV: {e}")
            self.ui.update_status("Ошибка при сохранении в CSV")
            messagebox.showerror("Ошибка", f"Не удалось сохранить строки в CSV: {e}")

    def send_to_telegram(self):
        """Отправка строк (скриншотов и Excel) в Telegram."""
        try:
            self.ui.update_status("Отправка строк в Telegram...")
            self.ui.update_processing_status("Подготовка файлов...")
            # Запускаем процесс отправки в отдельном потоке
            thread = threading.Thread(
                target=self._send_to_telegram_task,
                daemon=True
            )
            thread.start()
        except Exception as e:
            logger.error(f"Ошибка при запуске отправки строк в Telegram: {e}")
            self.ui.update_status("Ошибка при отправке строк в Telegram")
            self.ui.update_processing_status(f"Ошибка: {str(e)}")
            messagebox.showerror("Ошибка", f"Не удалось отправить строки в Telegram: {e}")

    def _send_to_telegram_task(self):
        """Задача отправки строк в Telegram."""
        try:
            files_sent = False
            
            # Проверяем наличие скриншотов
            processed_dir = "screenshots_processed"
            if not os.path.exists(processed_dir):
                os.makedirs(processed_dir)
                logger.info(f"Создана директория {processed_dir}")

            # Получаем список файлов из директории screenshots_processed
            screenshot_files = []
            if os.path.exists(processed_dir):
                for file in os.listdir(processed_dir):
                    if file.endswith(('.jpg', '.jpeg', '.png')):
                        screenshot_files.append([file])

            if screenshot_files:
                # Находим последний Excel файл в папке logs
                logs_dir = get_logs_dir()
                excel_files = [f for f in os.listdir(logs_dir) if f.endswith('.xlsx')]
                if excel_files:
                    # Сортируем файлы по времени создания и берем последний
                    latest_excel = max(excel_files, key=lambda x: os.path.getctime(os.path.join(logs_dir, x)))
                    excel_path = os.path.join(logs_dir, latest_excel)

                    # Отправляем скриншоты и Excel в Telegram
                    self.ui.update_processing_status("Отправка скриншотов и Excel...")
                    from telegram_sender import send_files
                    
                    # Создаем новый event loop для отправки
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(send_files(excel_path, screenshot_files))
                        self.ui.update_processing_status("Скриншоты и Excel отправлены")
                        files_sent = True
                    finally:
                        loop.close()
                else:
                    logger.info("Нет Excel файла для отправки")
            else:
                logger.info("Нет скриншотов для отправки")

            if files_sent:
                self.ui.update_status("Файлы отправлены в Telegram")
                self.ui.update_processing_status("Отправка завершена")
                messagebox.showinfo("Успех", "Файлы успешно отправлены в Telegram")
            else:
                self.ui.update_status("Нет новых файлов для отправки")
                self.ui.update_processing_status("Нет новых файлов для отправки")
                messagebox.showinfo("Информация", "Нет новых файлов для отправки в Telegram")

        except Exception as e:
            logger.error(f"Ошибка при отправке строк в Telegram: {e}")
            self.ui.update_status("Ошибка при отправке строк в Telegram")
            self.ui.update_processing_status(f"Ошибка: {str(e)}")
            messagebox.showerror("Ошибка", f"Не удалось отправить строки в Telegram: {e}")

    def _start_rbk_mir24_monitoring(self):
        """Запуск мониторинга RBK и MIR24."""
        logger.info("Попытка запуска мониторинга RBK и MIR24...")
        self.ui.update_rbk_mir24_scheduler_status("Запуск RBK и MIR24...")
        if not self.rbk_mir24_running:
            try:
                self.rbk_mir24_running = True
                self.process_list.clear()
                self.ui.update_status("Запуск записи RBK и MIR24...")
                
                # Запускаем запись
                self.rbk_mir24_task = asyncio.run_coroutine_threadsafe(
                    process_rbk_mir24(self, self.ui, True),
                    self.loop
                )
                
                self.ui.update_rbk_mir24_status("Запущен")
                self.ui.update_rbk_mir24_scheduler_status("RBK и MIR24 активны")
                logger.info("Запущен мониторинг RBK и MIR24 по расписанию")
                # Останавливаем через 20 минут и отправляем файлы
                threading.Timer(1200, self._process_and_send_video_files).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга RBK и MIR24: {e}")
                self.rbk_mir24_running = False
                self.ui.update_rbk_mir24_scheduler_status(f"Ошибка RBK и MIR24: {str(e)}")
        else:
            logger.warning("Мониторинг RBK и MIR24 уже запущен")
            self.ui.update_rbk_mir24_scheduler_status("RBK и MIR24 пропущены (уже запущены)")

    def _start_rentv_monitoring(self):
        """Запуск мониторинга RenTV."""
        logger.info("Попытка запуска мониторинга RenTV...")
        self.ui.update_rbk_mir24_scheduler_status("Запуск RenTV...")
        if not self.rbk_mir24_running:
            try:
                self.rbk_mir24_running = True
                self.process_list.clear()
                self.ui.update_status("Запуск записи RenTV...")
                
                # Запускаем запись
                self.rbk_mir24_task = asyncio.run_coroutine_threadsafe(
                    process_rbk_mir24(self, self.ui, True, channels=['RenTV']),
                    self.loop
                )
                
                self.ui.update_rbk_mir24_status("Запущен")
                self.ui.update_rbk_mir24_scheduler_status("RenTV активен")
                logger.info("Запущен мониторинг RenTV по расписанию")
                # Останавливаем через 10 минут и отправляем файлы
                threading.Timer(600, self._process_and_send_video_files).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга RenTV: {e}")
                self.rbk_mir24_running = False
                self.ui.update_rbk_mir24_scheduler_status(f"Ошибка RenTV: {str(e)}")
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск RenTV")
            self.ui.update_rbk_mir24_scheduler_status("RenTV пропущен (уже запущен)")

    def _start_ntv_monitoring(self):
        """Запуск мониторинга NTV."""
        logger.info("Попытка запуска мониторинга NTV...")
        self.ui.update_rbk_mir24_scheduler_status("Запуск NTV...")
        if not self.rbk_mir24_running:
            try:
                self.rbk_mir24_running = True
                self.process_list.clear()
                self.ui.update_status("Запуск записи NTV...")
                
                # Запускаем запись
                self.rbk_mir24_task = asyncio.run_coroutine_threadsafe(
                    process_rbk_mir24(self, self.ui, True, channels=['NTV']),
                    self.loop
                )
                
                self.ui.update_rbk_mir24_status("Запущен")
                self.ui.update_rbk_mir24_scheduler_status("NTV активен")
                logger.info("Запущен мониторинг NTV по расписанию")
                # Останавливаем через 10 минут и отправляем файлы
                threading.Timer(600, self._process_and_send_video_files).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга NTV: {e}")
                self.rbk_mir24_running = False
                self.ui.update_rbk_mir24_scheduler_status(f"Ошибка NTV: {str(e)}")
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск NTV")
            self.ui.update_rbk_mir24_scheduler_status("NTV пропущен (уже запущен)")

    def _start_tvc_monitoring(self):
        """Запуск мониторинга TVC."""
        logger.info("Попытка запуска мониторинга TVC...")
        self.ui.update_rbk_mir24_scheduler_status("Запуск TVC...")
        if not self.rbk_mir24_running:
            try:
                self.rbk_mir24_running = True
                self.process_list.clear()
                self.ui.update_status("Запуск записи TVC...")
                
                # Запускаем запись
                self.rbk_mir24_task = asyncio.run_coroutine_threadsafe(
                    process_rbk_mir24(self, self.ui, True, channels=['TVC']),
                    self.loop
                )
                
                self.ui.update_rbk_mir24_status("Запущен")
                self.ui.update_rbk_mir24_scheduler_status("TVC активен")
                logger.info("Запущен мониторинг TVC по расписанию")
                # Останавливаем через 10 минут и отправляем файлы
                threading.Timer(600, self._process_and_send_video_files).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга TVC: {e}")
                self.rbk_mir24_running = False
                self.ui.update_rbk_mir24_scheduler_status(f"Ошибка TVC: {str(e)}")
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск TVC")
            self.ui.update_rbk_mir24_scheduler_status("TVC пропущен (уже запущен)")

    def _process_and_send_video_files(self):
        """Обработка и отправка видео файлов."""
        try:
            # Останавливаем запись
            self.stop_rbk_mir24()
            self.ui.update_processing_status("Обработка видео файлов...")
            
            # Отправляем файлы в Telegram
            self.send_to_telegram()
            self.ui.update_processing_status("Видео файлы отправлены")
            logger.info("Видео файлы обработаны и отправлены")
        except Exception as e:
            logger.error(f"Ошибка при обработке и отправке видео файлов: {e}")
            self.ui.update_processing_status(f"Ошибка: {str(e)}")

    def _process_and_send_screenshots(self):
        """Обработка и отправка скриншотов."""
        try:
            # Останавливаем мониторинг
            self.stop_lines_monitoring()
            self.ui.update_processing_status("Обработка скриншотов...")
            
            # Обрабатываем скриншоты и отправляем в Telegram
            self.start_save_to_csv()
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
                send_files(file_path, [])
                
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

    def start_video_recognition(self):
        """Запуск распознавания текста из видео."""
        if not self.video_recognition_running:
            try:
                self.video_recognition_running = True
                self.ui.update_video_check_status("Выполняется")
                self.ui.update_status("Запуск распознавания видео...")
                
                # Создаем распознаватель
                self.video_recognizer = VideoTextRecognizer(
                    video_dir="video",
                    output_dir="recognized_text",
                    keep_screenshots=False
                )
                
                # Запускаем распознавание в отдельном потоке
                self.video_recognition_thread = threading.Thread(
                    target=self._run_video_recognition,
                    daemon=True
                )
                self.video_recognition_thread.start()
                
                logger.info("Запущено распознавание видео")
                
            except Exception as e:
                logger.error(f"Ошибка при запуске распознавания видео: {e}")
                self.video_recognition_running = False
                self.ui.update_video_check_status("Ошибка")
                self.ui.update_status(f"Ошибка: {str(e)}")
        else:
            logger.warning("Распознавание видео уже запущено")
            self.ui.update_status("Распознавание видео уже запущено")

    def stop_video_recognition(self):
        """Остановка распознавания текста из видео."""
        if self.video_recognition_running:
            try:
                self.video_recognition_running = False
                self.ui.update_video_check_status("Остановка...")
                self.ui.update_status("Остановка распознавания видео...")
                
                # Ждем завершения потока
                if self.video_recognition_thread and self.video_recognition_thread.is_alive():
                    self.video_recognition_thread.join(timeout=5)
                
                self.ui.update_video_check_status("Остановлен")
                self.ui.update_status("Распознавание видео остановлено")
                logger.info("Распознавание видео остановлено")
                
            except Exception as e:
                logger.error(f"Ошибка при остановке распознавания видео: {e}")
                self.ui.update_video_check_status("Ошибка остановки")
                self.ui.update_status(f"Ошибка остановки: {str(e)}")
        else:
            logger.warning("Распознавание видео не запущено")

    def _run_video_recognition(self):
        """Выполнение распознавания видео в отдельном потоке."""
        try:
            logger.info("Начало распознавания текста из видео")
            self.ui.update_status("Распознавание текста из видео...")
            
            # Обрабатываем все каналы
            results = self.video_recognizer.process_all_channels()
            
            # Подсчитываем общее количество распознанных текстов
            total_texts = sum(len(texts) for texts in results.values())
            
            if total_texts > 0:
                self.ui.update_status(f"Распознано {total_texts} текстов из видео")
                logger.info(f"Распознавание завершено. Найдено {total_texts} текстов")
                
                # Показываем статистику по каналам
                for channel, texts in results.items():
                    if texts:
                        logger.info(f"Канал {channel}: {len(texts)} текстов")
            else:
                self.ui.update_status("Тексты в видео не найдены")
                logger.info("Распознавание завершено. Тексты не найдены")
            
            self.ui.update_video_check_status("Завершено")
            
        except Exception as e:
            logger.error(f"Ошибка при распознавании видео: {e}")
            self.ui.update_video_check_status("Ошибка")
            self.ui.update_status(f"Ошибка распознавания: {str(e)}")
        finally:
            self.video_recognition_running = False

    def send_video_to_telegram(self):
        """Отправка видео с ключевыми словами в Telegram."""
        try:
            self.ui.update_status("Подготовка видео для отправки в Telegram...")
            
            # Запускаем отправку в отдельном потоке
            send_thread = threading.Thread(
                target=self._send_video_to_telegram_task,
                daemon=True
            )
            send_thread.start()
            
            logger.info("Запущена отправка видео в Telegram")
            
        except Exception as e:
            logger.error(f"Ошибка при запуске отправки видео: {e}")
            self.ui.update_status(f"Ошибка: {str(e)}")

    def _send_video_to_telegram_task(self):
        """Выполнение отправки видео в Telegram в отдельном потоке."""
        try:
            logger.info("Начало обработки видео для отправки в Telegram")
            self.ui.update_status("Обработка видео для отправки...")
            
            # Получаем список видео файлов с ключевыми словами
            videos_with_keywords = self._get_videos_with_keywords()
            
            if not videos_with_keywords:
                self.ui.update_status("Видео с ключевыми словами не найдены")
                logger.info("Видео с ключевыми словами не найдены")
                return
            
            logger.info(f"Найдено {len(videos_with_keywords)} видео с ключевыми словами")
            self.ui.update_status(f"Отправка {len(videos_with_keywords)} видео в Telegram...")
            
            # Отправляем видео в Telegram
            sent_count = 0
            for video_info in videos_with_keywords:
                try:
                    video_path = video_info['video_path']
                    channel_name = video_info['channel']
                    found_keywords = video_info['found_keywords']
                    
                    # Отправляем видео
                    success = self._send_single_video_to_telegram(video_path, channel_name, found_keywords)
                    
                    if success:
                        sent_count += 1
                        logger.info(f"Видео {video_path.name} отправлено в Telegram")
                    else:
                        logger.error(f"Не удалось отправить видео {video_path.name}")
                        
                except Exception as e:
                    logger.error(f"Ошибка при отправке видео {video_info.get('video_path', 'unknown')}: {e}")
            
            # Удаляем все видео файлы (отправленные и неотправленные)
            self._cleanup_video_files()
            
            self.ui.update_status(f"Отправлено {sent_count} видео в Telegram. Все видео удалены.")
            logger.info(f"Отправка завершена. Отправлено {sent_count} видео, все файлы удалены")
            
        except Exception as e:
            logger.error(f"Ошибка при отправке видео в Telegram: {e}")
            self.ui.update_status(f"Ошибка отправки: {str(e)}")

    def _get_videos_with_keywords(self):
        """Получение списка видео файлов с ключевыми словами."""
        videos_with_keywords = []
        
        try:
            # Проверяем папку video
            video_dir = Path("video")
            if not video_dir.exists():
                logger.warning("Папка video не найдена")
                return videos_with_keywords
            
            # Проходим по всем подпапкам каналов
            for channel_dir in video_dir.iterdir():
                if not channel_dir.is_dir():
                    continue
                    
                channel_name = channel_dir.name
                
                # Ищем видео файлы в папке канала
                for video_file in channel_dir.glob("*.mp4"):
                    try:
                        # Проверяем, есть ли для этого видео распознанный текст с ключевыми словами
                        if self._video_has_keywords(video_file, channel_name):
                            videos_with_keywords.append({
                                'video_path': video_file,
                                'channel': channel_name,
                                'found_keywords': self._get_video_keywords(video_file, channel_name)
                            })
                            logger.info(f"Видео {video_file.name} содержит ключевые слова")
                    except Exception as e:
                        logger.error(f"Ошибка при проверке видео {video_file}: {e}")
            
            logger.info(f"Найдено {len(videos_with_keywords)} видео с ключевыми словами")
            
        except Exception as e:
            logger.error(f"Ошибка при поиске видео с ключевыми словами: {e}")
        
        return videos_with_keywords

    def _video_has_keywords(self, video_file, channel_name):
        """Проверка, содержит ли видео ключевые слова."""
        try:
            # Ищем JSON файлы с результатами распознавания
            recognized_dir = Path("recognized_text")
            if not recognized_dir.exists():
                return False
            
            # Ищем файлы, содержащие имя видео
            video_name = video_file.stem
            for json_file in recognized_dir.glob(f"*{video_name}*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Проверяем, есть ли тексты с ключевыми словами
                    if isinstance(data, list):
                        for item in data:
                            if (item.get('video_file') == video_file.name and 
                                item.get('found_keywords') and 
                                len(item.get('found_keywords', [])) > 0):
                                return True
                    
                except Exception as e:
                    logger.error(f"Ошибка при чтении файла {json_file}: {e}")
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка при проверке ключевых слов для {video_file}: {e}")
            return False

    def _get_video_keywords(self, video_file, channel_name):
        """Получение списка ключевых слов для видео."""
        try:
            recognized_dir = Path("recognized_text")
            if not recognized_dir.exists():
                return []
            
            video_name = video_file.stem
            all_keywords = []
            
            for json_file in recognized_dir.glob(f"*{video_name}*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if isinstance(data, list):
                        for item in data:
                            if item.get('video_file') == video_file.name:
                                keywords = item.get('found_keywords', [])
                                all_keywords.extend(keywords)
                    
                except Exception as e:
                    logger.error(f"Ошибка при чтении ключевых слов из {json_file}: {e}")
            
            # Удаляем дубликаты
            return list(set(all_keywords))
            
        except Exception as e:
            logger.error(f"Ошибка при получении ключевых слов для {video_file}: {e}")
            return []

    def _send_single_video_to_telegram(self, video_path, channel_name, found_keywords):
        """Отправка одного видео файла в Telegram."""
        try:
            # Формируем сообщение с информацией о ключевых словах
            keywords_text = ", ".join(found_keywords) if found_keywords else "не указаны"
            caption = f"Канал: {channel_name}\nКлючевые слова: {keywords_text}\nФайл: {video_path.name}"
            
            # Отправляем видео через telegram_sender
            from telegram_sender import send_files
            success = send_files([str(video_path)], caption=caption)
            
            return success
            
        except Exception as e:
            logger.error(f"Ошибка при отправке видео {video_path}: {e}")
            return False

    def _cleanup_video_files(self):
        """Удаление всех видео файлов после обработки."""
        try:
            video_dir = Path("video")
            if not video_dir.exists():
                return
            
            deleted_count = 0
            
            # Удаляем все видео файлы из всех подпапок
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
            
            logger.info("Очистка ресурсов завершена")
            
        except Exception as e:
            logger.error(f"Ошибка при очистке ресурсов: {e}")

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