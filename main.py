import tkinter as tk
import logging
import asyncio
import threading
import os
from datetime import datetime
from parser_lines import main as run_parser_lines
from lines_to_csv import process_screenshots, process_rbk_mir24
from telegram_sender import send_files

# Создаем папку logs, если она не существует
os.makedirs("logs", exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/main_log.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MonitoringApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Мониторинг бегущих строк")
        self.root.geometry("400x250")

        self.status_label = tk.Label(self.root, text="Состояние: Ожидание")
        self.status_label.pack(pady=10)

        self.start_button = tk.Button(self.root, text="Мониторинг строк", command=self.start_monitoring)
        self.start_button.pack(pady=5)

        self.stop_button = tk.Button(self.root, text="Остановить парсинг", command=self.stop_monitoring, state="disabled")
        self.stop_button.pack(pady=5)

        self.rbk_mir24_button = tk.Button(self.root, text="Строки РБК и МИР24", command=self.save_rbk_mir24)
        self.rbk_mir24_button.pack(pady=5)

        self.save_button = tk.Button(self.root, text="Сохранение строк", command=self.save_to_csv)
        self.save_button.pack(pady=5)

        # Флаги и объекты для управления парсингом
        self.running = False
        self.loop = None
        self.parser_task = None
        self.asyncio_thread = None

    def start_monitoring(self):
        if not self.running:
            logger.info("Запуск мониторинга")
            self.status_label.config(text="Состояние: Мониторинг запущен")
            self.start_button.config(state="disabled")
            self.stop_button.config(state="normal")
            self.running = True

            # Запускаем asyncio в отдельном потоке
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.asyncio_thread = threading.Thread(target=self.run_asyncio_loop, daemon=True)
            self.asyncio_thread.start()

            # Запускаем задачу парсинга
            self.parser_task = self.loop.create_task(run_parser_lines())

    def stop_monitoring(self):
        if self.running:
            logger.info("Остановка мониторинга")
            self.status_label.config(text="Состояние: Мониторинг остановлен")
            self.start_button.config(state="normal")
            self.stop_button.config(state="disabled")
            self.running = False

            # Останавливаем задачу парсинга
            if self.parser_task:
                self.loop.call_soon_threadsafe(self.parser_task.cancel)
            # Останавливаем цикл событий
            if self.loop:
                self.loop.call_soon_threadsafe(self.loop.stop)

    def save_rbk_mir24(self):
        logger.info("Сохранение строк РБК и МИР24")
        self.status_label.config(text="Состояние: Обработка РБК и МИР24...")
        try:
            output_file, screenshot_files = process_rbk_mir24()
            send_files(output_file, screenshot_files)
            self.status_label.config(text="Состояние: Сохранение РБК и МИР24 завершено")
            logger.info(f"Сохранение строк РБК и МИР24 завершено в {output_file}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении РБК и МИР24: {e}")
            self.status_label.config(text=f"Состояние: Ошибка: {str(e)}")

    def save_to_csv(self):
        logger.info("Сохранение строк остальных каналов")
        self.status_label.config(text="Состояние: Обработка остальных каналов...")
        try:
            output_file, screenshot_files = process_screenshots()
            send_files(output_file, screenshot_files)
            self.status_label.config(text="Состояние: Сохранение остальных каналов завершено")
            logger.info(f"Сохранение строк остальных каналов завершено в {output_file}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении остальных каналов: {e}")
            self.status_label.config(text=f"Состояние: Ошибка: {str(e)}")

    def run_asyncio_loop(self):
        try:
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"Ошибка в цикле asyncio: {e}")
        finally:
            self.loop.close()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = MonitoringApp()
    app.run()




# import tkinter as tk
# import logging
# import asyncio
# import threading
# import os
# from datetime import datetime
#
# from parser_lines import main as run_parser_lines
# from lines_to_csv import process_screenshots
#
# # Создаем папку logs, если она не существует
# os.makedirs("logs", exist_ok=True)
#
# # Настройка логирования
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler("logs/main_log.log"),
#         logging.StreamHandler()
#     ]
# )
# logger = logging.getLogger(__name__)
#
# class MonitoringApp:
#     def __init__(self):
#         self.root = tk.Tk()
#         self.root.title("Мониторинг бегущих строк")
#         self.root.geometry("400x200")
#
#         self.status_label = tk.Label(self.root, text="Состояние: Ожидание")
#         self.status_label.pack(pady=10)
#
#         self.start_button = tk.Button(self.root, text="Мониторинг строк", command=self.start_monitoring)
#         self.start_button.pack(pady=5)
#
#         self.stop_button = tk.Button(self.root, text="Остановить парсинг", command=self.stop_monitoring, state="disabled")
#         self.stop_button.pack(pady=5)
#
#         self.save_button = tk.Button(self.root, text="Сохранение строк", command=self.save_to_csv)
#         self.save_button.pack(pady=5)
#
#         # Флаги и объекты для управления парсингом
#         self.running = False
#         self.loop = None
#         self.parser_task = None
#         self.asyncio_thread = None
#
#     def start_monitoring(self):
#         if not self.running:
#             logger.info("Запуск мониторинга")
#             self.status_label.config(text="Состояние: Мониторинг запущен")
#             self.start_button.config(state="disabled")
#             self.stop_button.config(state="normal")
#             self.running = True
#
#             # Запускаем asyncio в отдельном потоке
#             self.loop = asyncio.new_event_loop()
#             asyncio.set_event_loop(self.loop)
#             self.asyncio_thread = threading.Thread(target=self.run_asyncio_loop, daemon=True)
#             self.asyncio_thread.start()
#
#             # Запускаем задачу парсинга
#             self.parser_task = self.loop.create_task(run_parser_lines())
#
#     def stop_monitoring(self):
#         if self.running:
#             logger.info("Остановка мониторинга")
#             self.status_label.config(text="Состояние: Мониторинг остановлен")
#             self.start_button.config(state="normal")
#             self.stop_button.config(state="disabled")
#             self.running = False
#
#             # Останавливаем задачу парсинга
#             if self.parser_task:
#                 self.loop.call_soon_threadsafe(self.parser_task.cancel)
#             # Останавливаем цикл событий
#             if self.loop:
#                 self.loop.call_soon_threadsafe(self.loop.stop)
#
#     def save_to_csv(self):
#         logger.info("Сохранение строк в CSV")
#         self.status_label.config(text="Состояние: Обработка...")
#         try:
#             # Выполняем код из lines_to_csv.py
#             process_screenshots()
#             # Получаем имя последнего созданного файла
#             timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
#             output_file = f"logs/recognized_text_{timestamp}.csv"
#             self.status_label.config(text="Состояние: Сохранение завершено")
#             logger.info(f"Сохранение успешно завершено в {output_file}")
#         except Exception as e:
#             logger.error(f"Ошибка при сохранении: {e}")
#             self.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
#
#     def run_asyncio_loop(self):
#         try:
#             self.loop.run_forever()
#         except Exception as e:
#             logger.error(f"Ошибка в цикле asyncio: {e}")
#         finally:
#             self.loop.close()
#
#     def run(self):
#         self.root.mainloop()
#
# if __name__ == "__main__":
#     app = MonitoringApp()
#     app.run()