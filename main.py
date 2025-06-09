from parser_lines import main as run_parser_lines
from lines_to_csv import process_screenshots
from telegram_sender import send_files, send_to_telegram
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging, start_monitoring, stop_monitoring, save_to_csv, send_strings, run_async_task
from UI import MonitoringUI
import asyncio
import threading
import logging

class MonitoringApp:
    def __init__(self):
        self.logger = setup_logging()
        self.running = False
        self.loop = None
        self.parser_task = None
        self.rbk_mir24_task = None
        self.asyncio_thread = None
        self.rbk_mir24_running = False  # флаг выполнения записи РБК и МИР24


        # Передаем асинхронные обработчики в UI
        self.ui = MonitoringUI(
            start_monitoring=lambda: run_async_task(self, start_monitoring(self, self.ui, run_parser_lines)),
            stop_monitoring=lambda: run_async_task(self, stop_monitoring(self, self.ui)),
            save_rbk_mir24=lambda: self.start_rbk_mir24_task(),
            stop_rbk_mir24=lambda: run_async_task(self, stop_rbk_mir24(self, self.ui)),
            save_to_csv=lambda: run_async_task(self, save_to_csv(self, self.ui, process_screenshots, send_files)),
            send_strings=lambda: run_async_task(self, send_strings(self, self.ui, send_to_telegram))
        )

    def ensure_loop(self):
        """Создает или восстанавливает цикл событий, если он отсутствует или закрыт."""
        if not self.loop or self.loop.is_closed() or not self.asyncio_thread or not self.asyncio_thread.is_alive():
            if self.loop and not self.loop.is_closed():
                self.logger.info("Закрытие существующего цикла событий")
                self.loop.stop()
                self.loop.close()
            self.logger.info("Создание нового цикла событий")
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.logger.info("Запуск нового потока для цикла событий")
            self.asyncio_thread = threading.Thread(target=self.loop.run_forever, args=(), daemon=True)
            self.asyncio_thread.start()
        else:
            self.logger.info("Использование существующего цикла событий")
        return self.loop

    def start_rbk_mir24_task(self):
        """Запускает задачу обработки РБК и МИР24 через run_async_task."""
        self.logger.info("Попытка запуска задачи РБК и МИР24")

        if self.rbk_mir24_running:
            self.logger.warning("Задача РБК и МИР24 уже выполняется")
            self.ui.status_label.config(text="Состояние: Предыдущая запись еще выполняется")
            return

        self.rbk_mir24_running = True

        async def wrapped_task():
            try:
                await process_rbk_mir24(self, self.ui, send_files)
            finally:
                self.rbk_mir24_running = False
                self.logger.info("Флаг rbk_mir24_running сброшен после завершения задачи")

        run_async_task(self, wrapped_task)()  # запускаем wrapper-функцию

    def run(self):
        try:
            self.ui.run()
        except Exception as e:
            self.logger.error(f"Ошибка в главном приложении: {e}")
            if self.loop and not self.loop.is_closed():
                self.loop.stop()
                self.loop.close()
            raise

    def cleanup_tasks(self):
        """Очищает завершенные задачи, если необходимо."""
        if self.rbk_mir24_task and self.rbk_mir24_task.done():
            self.rbk_mir24_task = None

if __name__ == "__main__":
    try:
        app = MonitoringApp()
        app.run()
    except Exception as e:
        logging.getLogger(__name__).error(f"Ошибка при запуске приложения: {e}")