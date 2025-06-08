# Импорт функций обработки строк
from parser_lines import main as run_parser_lines  # Основной асинхронный парсер бегущих строк
from lines_to_csv import process_screenshots, process_rbk_mir24  # Обработка строк в CSV-формат

# Импорт функций отправки файлов через Telegram
from telegram_sender import send_files, send_to_telegram  # Отправка файлов и сообщений в Telegram

# Импорт вспомогательных функций и логики управления состоянием
from utils import (
    setup_logging,      # Настройка логирования
    start_monitoring,   # Запуск мониторинга
    stop_monitoring,    # Остановка мониторинга
    save_rbk_mir24,     # Сохранение строк РБК/МИР24
    save_to_csv,        # Сохранение строк других каналов
    stop_rbk_mir24,     # Принудительная остановка обработки РБК/МИР24
    send_strings        # Отправка ранее сохранённых строк в Telegram
)

# Импорт пользовательского интерфейса (Tkinter)
from UI import MonitoringUI

class MonitoringApp:
    """
    Главный класс приложения мониторинга. 
    Инкапсулирует состояние и управляет логикой работы через UI.
    """
    def __init__(self):
        self.logger = setup_logging()   # Инициализация системы логирования
        self.running = False            # Флаг состояния мониторинга
        self.loop = None                # asyncio loop, инициализируется при запуске
        self.parser_task = None         # Объект асинхронной задачи
        self.asyncio_thread = None      # Отдельный поток для запуска asyncio-цикла

        # Инициализация пользовательского интерфейса и передача функций управления
        self.ui = MonitoringUI(
            start_monitoring=lambda: start_monitoring(self, self.ui, run_parser_lines),  # Запуск мониторинга
            stop_monitoring=lambda: stop_monitoring(self, self.ui),                      # Остановка мониторинга
            save_rbk_mir24=lambda: save_rbk_mir24(self, self.ui, process_rbk_mir24, send_files),  # Сохранение строк РБК/МИР24
            save_to_csv=lambda: save_to_csv(self, self.ui, process_screenshots, send_files),      # Сохранение остальных строк
            stop_rbk_mir24=lambda: stop_rbk_mir24(self, self.ui),                                 # Принудительная остановка РБК/МИР24
            send_strings=lambda: send_strings(self, self.ui, send_to_telegram)                    # Отправка сохранённых строк в Telegram
        )

    def run(self):
        """
        Запуск графического интерфейса приложения.
        """
        self.ui.run()

# Точка входа в приложение
if __name__ == "__main__":
    app = MonitoringApp()
    app.run()
