import logging
import threading
import asyncio
import tkinter as tk

from UI import MonitoringUI
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging, run_async_task

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

        # UI с привязкой обработчиков
        self.ui = MonitoringUI(
            start_monitoring=lambda: None,  # пока не реализовано
            stop_monitoring=lambda: None,
            save_rbk_mir24=self.start_rbk_mir24_task,
            stop_rbk_mir24=lambda: run_async_task(self, lambda: stop_rbk_mir24(self, self.ui))(),
            save_to_csv=lambda: None,
            send_strings=lambda: None,
        )

    def ensure_loop(self):
        if self.loop and self.loop.is_running():
            self.logger.info("Использование существующего цикла событий")
            return self.loop

        self.logger.info("Создание нового цикла событий")
        self.loop = asyncio.new_event_loop()

        def start_loop():
            asyncio.set_event_loop(self.loop)
            self.logger.info("Запуск нового потока для цикла событий")
            self.loop.run_forever()

        self.thread = threading.Thread(target=start_loop, daemon=True)
        self.thread.start()
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
                await process_rbk_mir24(self, self.ui, send_files=None)
            finally:
                self.rbk_mir24_running = False
                self.logger.info("Флаг rbk_mir24_running сброшен после завершения задачи")

        run_async_task(self, wrapped_task)()

    def run(self):
        self.ui.run()

if __name__ == "__main__":
    app = MonitoringApp()
    app.run()
