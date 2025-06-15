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
from lines_to_csv import process_screenshots
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

        logger.info("Расписание настроено, начинаем выполнение...")
        while self.scheduler_running:
            try:
                schedule.run_pending()
                time_module.sleep(1)
            except Exception as e:
                logger.error(f"Ошибка в планировщике: {e}")

    def _start_r1_monitoring(self):
        """Запуск мониторинга для R1."""
        logger.info("Попытка запуска мониторинга R1...")
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
                # Останавливаем через 30 минут
                threading.Timer(1800, self.stop_lines_monitoring).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга R1: {e}")
                self.lines_monitoring_running = False
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск R1")

    def _start_zvezda_monitoring(self):
        """Запуск мониторинга для Zvezda."""
        logger.info("Попытка запуска мониторинга Zvezda...")
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
                # Останавливаем через 10 минут
                threading.Timer(600, self.stop_lines_monitoring).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга Zvezda: {e}")
                self.lines_monitoring_running = False
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск Zvezda")

    def _start_other_channels_monitoring(self):
        """Запуск мониторинга для остальных каналов."""
        logger.info("Попытка запуска мониторинга остальных каналов...")
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
                # Останавливаем через 20 минут
                threading.Timer(1200, self.stop_lines_monitoring).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга остальных каналов: {e}")
                self.lines_monitoring_running = False
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск остальных каналов")

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
            self.ui.update_status("Сохранение строк в CSV...")
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
        """Отправка строк в Telegram."""
        try:
            self.ui.update_status("Отправка строк в Telegram...")
            # Запускаем процесс сохранения в отдельном потоке
            thread = threading.Thread(
                target=self._send_to_telegram_task,
                daemon=True
            )
            thread.start()
        except Exception as e:
            logger.error(f"Ошибка при запуске отправки в Telegram: {e}")
            self.ui.update_status("Ошибка при отправке в Telegram")
            messagebox.showerror("Ошибка", f"Не удалось отправить строки в Telegram: {e}")

    def _send_to_telegram_task(self):
        """Задача отправки строк в Telegram."""
        try:
            # Проверяем наличие файлов в screenshots_processed
            processed_dir = "screenshots_processed"
            if not os.path.exists(processed_dir):
                os.makedirs(processed_dir)
                logger.info(f"Создана директория {processed_dir}")

            # Получаем список файлов из директории screenshots_processed
            screenshot_files = []
            for file in os.listdir(processed_dir):
                if file.endswith(('.jpg', '.jpeg', '.png')):
                    screenshot_files.append([file])

            if not screenshot_files:
                self.ui.update_status("Нет скриншотов для отправки")
                messagebox.showwarning("Предупреждение", "Нет скриншотов для отправки в Telegram")
                return

            # Находим последний Excel файл в папке logs
            logs_dir = "logs"
            excel_files = [f for f in os.listdir(logs_dir) if f.endswith('.xlsx')]
            if not excel_files:
                self.ui.update_status("Нет Excel файла для отправки")
                messagebox.showwarning("Предупреждение", "Нет Excel файла для отправки в Telegram")
                return

            # Сортируем файлы по времени создания и берем последний
            latest_excel = max(excel_files, key=lambda x: os.path.getctime(os.path.join(logs_dir, x)))
            excel_path = os.path.join(logs_dir, latest_excel)

            # Отправляем файлы в Telegram
            send_files(excel_path, screenshot_files)
            self.ui.update_status("Файлы отправлены в Telegram")
            messagebox.showinfo("Успех", "Файлы успешно отправлены в Telegram")

        except Exception as e:
            logger.error(f"Ошибка при отправке в Telegram: {e}")
            self.ui.update_status("Ошибка при отправке в Telegram")
            messagebox.showerror("Ошибка", f"Не удалось отправить файлы в Telegram: {e}")

    def _start_rbk_mir24_monitoring(self):
        """Запуск мониторинга RBK и MIR24."""
        logger.info("Попытка запуска мониторинга RBK и MIR24...")
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
                logger.info("Запущен мониторинг RBK и MIR24 по расписанию")
                # Останавливаем через 20 минут
                threading.Timer(1200, self.stop_rbk_mir24).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга RBK и MIR24: {e}")
                self.rbk_mir24_running = False
        else:
            logger.warning("Мониторинг RBK и MIR24 уже запущен")

    def _start_rentv_monitoring(self):
        """Запуск мониторинга RenTV."""
        logger.info("Попытка запуска мониторинга RenTV...")
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
                logger.info("Запущен мониторинг RenTV по расписанию")
                # Останавливаем через 10 минут
                threading.Timer(600, self.stop_rbk_mir24).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга RenTV: {e}")
                self.rbk_mir24_running = False
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск RenTV")

    def _start_ntv_monitoring(self):
        """Запуск мониторинга NTV."""
        logger.info("Попытка запуска мониторинга NTV...")
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
                logger.info("Запущен мониторинг NTV по расписанию")
                # Останавливаем через 10 минут
                threading.Timer(600, self.stop_rbk_mir24).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга NTV: {e}")
                self.rbk_mir24_running = False
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск NTV")

    def _start_tvc_monitoring(self):
        """Запуск мониторинга TVC."""
        logger.info("Попытка запуска мониторинга TVC...")
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
                logger.info("Запущен мониторинг TVC по расписанию")
                # Останавливаем через 10 минут
                threading.Timer(600, self.stop_rbk_mir24).start()
            except Exception as e:
                logger.error(f"Ошибка при запуске мониторинга TVC: {e}")
                self.rbk_mir24_running = False
        else:
            logger.warning("Мониторинг уже запущен, пропускаем запуск TVC")

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