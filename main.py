import logging
import threading
import asyncio
import tkinter as tk
from tkinter import ttk, messagebox

from UI import MonitoringUI
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging, run_async_task
from parser_lines import main as start_lines_monitoring, stop_subprocesses, start_force_capture, stop_force_capture
from lines_to_csv import process_screenshots

# Инициализация логирования
logger = setup_logging()

class MonitoringApp:
    def __init__(self):
        self.logger = logger
        self.loop = None
        self.thread = None
        self.running = False

        self.rbk_mir24_task = None
        self.rbk_mir24_running = False
        
        self.lines_monitoring_thread = None
        self.lines_monitoring_running = False

        # Создаем и запускаем UI
        self.ui = MonitoringUI(self)
        self.ui.run()

    def start_rbk_mir24(self):
        """Запуск мониторинга RBK и MIR24."""
        if not self.rbk_mir24_running:
            self.rbk_mir24_running = True
            self.rbk_mir24_task = asyncio.run_coroutine_threadsafe(
                process_rbk_mir24(),
                self.loop
            )
            self.ui.update_rbk_mir24_status("Запущен")
            logger.info("Запущен мониторинг RBK и MIR24")
        else:
            messagebox.showwarning("Предупреждение", "Мониторинг RBK и MIR24 уже запущен")

    def stop_rbk_mir24(self):
        """Остановка мониторинга RBK и MIR24."""
        if self.rbk_mir24_running:
            self.rbk_mir24_running = False
            asyncio.run_coroutine_threadsafe(
                stop_rbk_mir24(),
                self.loop
            )
            self.ui.update_rbk_mir24_status("Остановлен")
            logger.info("Остановлен мониторинг RBK и MIR24")
        else:
            messagebox.showwarning("Предупреждение", "Мониторинг RBK и MIR24 уже остановлен")

    def start_lines_monitoring(self):
        """Запуск мониторинга строк."""
        if not self.lines_monitoring_running:
            self.lines_monitoring_running = True
            # Запускаем принудительный захват скриншотов
            start_force_capture()
            # Запускаем поток мониторинга
            self.lines_monitoring_thread = threading.Thread(
                target=start_lines_monitoring,
                daemon=True
            )
            self.lines_monitoring_thread.start()
            self.ui.update_lines_status("Запущен")
            logger.info("Запущен мониторинг строк")
        else:
            messagebox.showwarning("Предупреждение", "Мониторинг строк уже запущен")

    def stop_lines_monitoring(self):
        """Остановка мониторинга строк."""
        if self.lines_monitoring_running:
            self.lines_monitoring_running = False
            # Останавливаем принудительный захват
            stop_force_capture()
            # Останавливаем все процессы
            stop_subprocesses()
            # Ждем завершения потока мониторинга
            if self.lines_monitoring_thread and self.lines_monitoring_thread.is_alive():
                self.lines_monitoring_thread.join(timeout=5.0)
            self.lines_monitoring_thread = None
            self.ui.update_lines_status("Остановлен")
            logger.info("Остановлен мониторинг строк")
        else:
            messagebox.showwarning("Предупреждение", "Мониторинг строк уже остановлен")

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
            output_file, screenshots = process_screenshots()
            if output_file:
                self.ui.update_status(f"Сохранено в {output_file}")
                messagebox.showinfo("Успех", f"Строки сохранены в файл: {output_file}")
            else:
                self.ui.update_status("Ошибка сохранения")
                messagebox.showerror("Ошибка", "Не удалось сохранить строки в CSV")
        except Exception as e:
            logger.error(f"Ошибка при сохранении в CSV: {e}")
            self.ui.update_status("Ошибка при сохранении в CSV")
            messagebox.showerror("Ошибка", f"Не удалось сохранить строки в CSV: {e}")

    def run(self):
        """Запуск приложения."""
        try:
            # Создаем новый event loop
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Запускаем event loop в отдельном потоке
            self.thread = threading.Thread(
                target=self.loop.run_forever,
                daemon=True
            )
            self.thread.start()
            
            # Запускаем UI
            self.ui.run()
            
        except Exception as e:
            logger.error(f"Ошибка при запуске приложения: {e}")
            if self.loop:
                self.loop.stop()
            if self.thread:
                self.thread.join()

    def cleanup(self):
        """Очистка ресурсов при закрытии приложения."""
        try:
            # Останавливаем мониторинг RBK и MIR24
            if self.rbk_mir24_running:
                self.stop_rbk_mir24()
            
            # Останавливаем мониторинг строк
            if self.lines_monitoring_running:
                self.stop_lines_monitoring()
            
            # Останавливаем event loop
            if self.loop:
                self.loop.stop()
            
            # Ждем завершения потока
            if self.thread:
                self.thread.join()
                
        except Exception as e:
            logger.error(f"Ошибка при очистке ресурсов: {e}")

if __name__ == "__main__":
    app = MonitoringApp()
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения работы")
    finally:
        app.cleanup()
