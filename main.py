import logging
import threading
import asyncio
import tkinter as tk

from UI import MonitoringUI
from rbk_mir24_parser import process_rbk_mir24, stop_rbk_mir24
from utils import setup_logging, run_async_task
from parser_lines import main as start_lines_monitoring, stop_subprocesses
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
        
        self.lines_monitoring_task = None
        self.lines_monitoring_running = False

        # UI с привязкой обработчиков
        self.ui = MonitoringUI(
            start_monitoring=self.start_lines_monitoring_task,
            stop_monitoring=self.stop_lines_monitoring_task,
            save_rbk_mir24=self.start_rbk_mir24_task,
            stop_rbk_mir24=lambda: run_async_task(self, lambda: stop_rbk_mir24(self, self.ui))(),
            save_to_csv=self.start_save_to_csv_task,
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

    def start_save_to_csv_task(self):
        """Запускает задачу сохранения строк в CSV."""
        self.logger.info("Попытка запуска задачи сохранения в CSV")
        self.ui.status_label.config(text="Состояние: Сохранение строк в CSV...")

        async def wrapped_task():
            try:
                output_file, screenshots = await process_screenshots()
                if output_file:
                    self.ui.status_label.config(text=f"Состояние: Сохранено в {output_file}")
                else:
                    self.ui.status_label.config(text="Состояние: Ошибка сохранения")
            except Exception as e:
                self.logger.error(f"Ошибка при сохранении в CSV: {e}")
                self.ui.status_label.config(text="Состояние: Ошибка сохранения")

        run_async_task(self, wrapped_task)()

    def start_lines_monitoring_task(self):
        """Запускает задачу мониторинга строк через run_async_task."""
        self.logger.info("Попытка запуска задачи мониторинга строк")

        if self.lines_monitoring_running:
            self.logger.warning("Задача мониторинга строк уже выполняется")
            self.ui.status_label.config(text="Состояние: Предыдущий мониторинг еще выполняется")
            return

        self.lines_monitoring_running = True
        self.ui.start_button.config(state="disabled")
        self.ui.stop_button.config(state="normal")

        async def wrapped_task():
            try:
                self.lines_monitoring_task = asyncio.create_task(start_lines_monitoring())
                await self.lines_monitoring_task
            except asyncio.CancelledError:
                self.logger.info("Задача мониторинга строк была отменена")
            finally:
                self.lines_monitoring_running = False
                self.lines_monitoring_task = None
                self.ui.start_button.config(state="normal")
                self.ui.stop_button.config(state="disabled")
                self.logger.info("Флаг lines_monitoring_running сброшен после завершения задачи")

        run_async_task(self, wrapped_task)()

    def stop_lines_monitoring_task(self):
        """Останавливает задачу мониторинга строк."""
        self.logger.info("Попытка остановки задачи мониторинга строк")
        
        if not self.lines_monitoring_running:
            self.logger.warning("Задача мониторинга строк не выполняется")
            return

        async def wrapped_task():
            try:
                if self.lines_monitoring_task:
                    self.lines_monitoring_task.cancel()
                    try:
                        await self.lines_monitoring_task
                    except asyncio.CancelledError:
                        pass
                await stop_subprocesses()
            finally:
                self.lines_monitoring_running = False
                self.lines_monitoring_task = None
                self.ui.start_button.config(state="normal")
                self.ui.stop_button.config(state="disabled")
                self.logger.info("Мониторинг строк остановлен")

        run_async_task(self, wrapped_task)()

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
