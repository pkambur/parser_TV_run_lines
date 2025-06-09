from parser_lines import main as run_parser_lines
from lines_to_csv import process_screenshots, process_rbk_mir24
from telegram_sender import send_files, send_to_telegram
from utils import setup_logging, start_monitoring, stop_monitoring, save_rbk_mir24, stop_rbk_mir24, save_to_csv, send_strings, run_async_task
from UI import MonitoringUI

class MonitoringApp:
    def __init__(self):
        self.logger = setup_logging()
        self.running = False
        self.loop = None
        self.parser_task = None
        self.rbk_mir24_task = None
        self.asyncio_thread = None

        # Передаем асинхронные обработчики в UI
        self.ui = MonitoringUI(
            start_monitoring=lambda: run_async_task(self, start_monitoring(self, self.ui, run_parser_lines)),
            stop_monitoring=lambda: run_async_task(self, stop_monitoring(self, self.ui)),
            save_rbk_mir24=lambda: run_async_task(self, save_rbk_mir24(self, self.ui, process_rbk_mir24, send_files)),
            stop_rbk_mir24=lambda: run_async_task(self, stop_rbk_mir24(self, self.ui)),
            save_to_csv=lambda: run_async_task(self, save_to_csv(self, self.ui, process_screenshots, send_files)),
            send_strings=lambda: run_async_task(self, send_strings(self, self.ui, send_to_telegram))
        )

    def run(self):
        self.ui.run()

if __name__ == "__main__":
    app = MonitoringApp()
    app.run()