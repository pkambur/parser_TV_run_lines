import logging
import threading
import asyncio
import tkinter as tk
from tkinter import ttk, messagebox
import os
import csv
from datetime import datetime, time
import schedule
import time as time_module

from UI import MonitoringUI
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging
from parser_lines import main as start_lines_monitoring, stop_subprocesses, start_force_capture, stop_force_capture
from lines_to_csv import process_screenshots, get_daily_file_path
from telegram_sender import send_files

# Инициализация логирования
logger = setup_logging()

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
        """Отправка файлов в Telegram."""
        try:
            self.ui.update_status("Отправка файлов в Telegram...")
            self.ui.update_processing_status("Подготовка файлов...")
            # Запускаем процесс отправки в отдельном потоке
            thread = threading.Thread(
                target=self._send_to_telegram_task,
                daemon=True
            )
            thread.start()
        except Exception as e:
            logger.error(f"Ошибка при запуске отправки в Telegram: {e}")
            self.ui.update_status("Ошибка при отправке в Telegram")
            self.ui.update_processing_status(f"Ошибка: {str(e)}")
            messagebox.showerror("Ошибка", f"Не удалось отправить файлы в Telegram: {e}")

    def _send_to_telegram_task(self):
        """Задача отправки файлов в Telegram."""
        try:
            files_sent = False
            
            # Проверяем наличие видео файлов
            video_dir = "video"
            if os.path.exists(video_dir) and os.listdir(video_dir):
                self.ui.update_processing_status("Отправка видео файлов...")
                from telegram_sender import send_video_files_sync
                send_video_files_sync()
                self.ui.update_processing_status("Видео файлы отправлены")
                files_sent = True
            else:
                logger.info("Нет видео файлов для отправки")
            
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
                logs_dir = "logs"
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
            logger.error(f"Ошибка при отправке в Telegram: {e}")
            self.ui.update_status("Ошибка при отправке в Telegram")
            self.ui.update_processing_status(f"Ошибка: {str(e)}")
            messagebox.showerror("Ошибка", f"Не удалось отправить файлы в Telegram: {e}")

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
        """Проверка и отправка новых файлов в Telegram."""
        try:
            processed_dir = "screenshots_processed"
            if not os.path.exists(processed_dir):
                return

            # Получаем список файлов из директории screenshots_processed
            screenshot_files = []
            for file in os.listdir(processed_dir):
                if file.endswith(('.jpg', '.jpeg', '.png')):
                    screenshot_files.append([file])

            if screenshot_files:
                # Находим последний Excel файл в папке logs
                logs_dir = "logs"
                excel_files = [f for f in os.listdir(logs_dir) if f.endswith('.xlsx')]
                if excel_files:
                    # Сортируем файлы по времени создания и берем последний
                    latest_excel = max(excel_files, key=lambda x: os.path.getctime(os.path.join(logs_dir, x)))
                    excel_path = os.path.join(logs_dir, latest_excel)

                    # Отправляем скриншоты и Excel в Telegram
                    self.ui.update_processing_status("Отправка новых скриншотов и Excel...")
                    from telegram_sender import send_files
                    
                    # Создаем новый event loop для отправки
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(send_files(excel_path, screenshot_files))
                        self.ui.update_processing_status("Новые скриншоты и Excel отправлены")
                    finally:
                        loop.close()

        except Exception as e:
            logger.error(f"Ошибка при проверке и отправке новых файлов: {e}")
            self.ui.update_processing_status(f"Ошибка: {str(e)}")

    def cleanup(self):
        """Очистка ресурсов при закрытии приложения."""
        try:
            # Останавливаем планировщик
            self.scheduler_running = False
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                self.scheduler_thread.join(timeout=5.0)
            
            # Сначала закрываем UI
            logger.info("Закрытие UI")
            self.ui.cleanup()
            
            if self.rbk_mir24_running:
                logger.info("Остановка мониторинга RBK и MIR24 в cleanup")
                self.stop_rbk_mir24()
            
            if self.lines_monitoring_running:
                logger.info("Остановка мониторинга строк в cleanup")
                self.stop_lines_monitoring()
            
            # Останавливаем event loop
            if self.loop and self.loop.is_running():
                logger.info("Остановка асинхронного цикла")
                try:
                    # Отменяем все задачи
                    for task in asyncio.all_tasks(self.loop):
                        task.cancel()
                    
                    # Останавливаем цикл
                    self.loop.call_soon_threadsafe(self.loop.stop)
                    
                    # Даем время на завершение задач
                    if self.thread and self.thread.is_alive():
                        self.thread.join(timeout=5.0)
                    
                    # Закрываем цикл
                    self.loop.close()
                    logger.info("Асинхронный цикл закрыт")
                except Exception as e:
                    logger.error(f"Ошибка при остановке event loop: {e}")
            
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