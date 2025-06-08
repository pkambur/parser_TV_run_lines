# Импорт основных функций и компонентов приложения
from parser_lines import main as run_parser_lines  # Основная функция для запуска парсера строк
from lines_to_csv import process_screenshots, process_rbk_mir24  # Обработка строк в CSV и для РБК/МИР24
from telegram_sender import send_files  # Отправка файлов через Telegram

# Импорт вспомогательных функций (логирование, логика мониторинга и сохранения)
from utils import (
    setup_logging,          # Настройка логирования
    start_monitoring,       # Функция запуска мониторинга
    stop_monitoring,        # Функция остановки мониторинга
    save_rbk_mir24,         # Обработка и сохранение строк РБК/МИР24
    save_to_csv             # Обработка и сохранение остальных строк
)

from UI import MonitoringUI  # Класс пользовательского интерфейса (Tkinter)

class MonitoringApp:
    """
    Главный класс приложения мониторинга.
    Отвечает за инициализацию логики, состояния и интерфейса.
    """
    def __init__(self):
        self.logger = setup_logging()   # Инициализация системы логирования
        self.running = False            # Флаг, указывающий, активен ли мониторинг
        self.loop = None                # asyncio event loop (будет создан при запуске)
        self.parser_task = None         # Асинхронная задача парсинга
        self.asyncio_thread = None      # Отдельный поток для запуска asyncio цикла

        # Инициализация пользовательского интерфейса (UI)
        # Передаём функции-обработчики как замыкания с передачей текущего состояния (self) и UI
        self.ui = MonitoringUI(
            start_monitoring=lambda: start_monitoring(self, self.ui, run_parser_lines),
            stop_monitoring=lambda: stop_monitoring(self, self.ui),
            save_rbk_mir24=lambda: save_rbk_mir24(self, self.ui, process_rbk_mir24, send_files),
            save_to_csv=lambda: save_to_csv(self, self.ui, process_screenshots, send_files)
        )

    def run(self):
        """
        Запуск основного цикла интерфейса (Tkinter).
        """
        self.ui.run()

# Точка входа в приложение
if __name__ == "__main__":
    app = MonitoringApp()
    app.run()
