import logging
import threading
import asyncio
import tkinter as tk
from tkinter import ttk, messagebox

from UI import MonitoringUI
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging
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

    def start_lines_monitoring(self):
        """Запуск мониторинга строк."""
        if not self.lines_monitoring_running:
            self.lines_monitoring_running = True
            start_force_capture()
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
            stop_force_capture()
            stop_subprocesses()
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

    def cleanup(self):
        """Очистка ресурсов при закрытии приложения."""
        try:
            # Сначала закрываем UI
            logger.info("Закрытие UI")
            self.ui.cleanup()
            
            if self.rbk_mir24_running:
                logger.info("Остановка мониторинга RBK и MIR24 в cleanup")
                self.stop_rbk_mir24()
            
            if self.lines_monitoring_running:
                logger.info("Остановка мониторинга строк в cleanup")
                self.stop_lines_monitoring()
            
            if self.loop and self.loop.is_running():
                logger.info("Остановка асинхронного цикла")
                self.loop.call_soon_threadsafe(self.loop.stop)
                # Ждем завершения всех задач
                pending = asyncio.all_tasks(self.loop)
                if pending:
                    self.loop.run_until_complete(asyncio.wait(pending, timeout=5.0))
                # Закрываем цикл
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                self.loop.close()
                logger.info("Асинхронный цикл закрыт")
            
            if self.thread and self.thread.is_alive():
                logger.info("Ожидание завершения потока")
                self.thread.join(timeout=5.0)
                
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