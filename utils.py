import asyncio
import logging
import os
import sys
from functools import wraps

logger = logging.getLogger(__name__)


def setup_logging(log_filename='main_log.txt'):
    """Настройка логирования с возможностью указать имя файла лога."""
    # Получаем путь к директории исполняемого файла
    if getattr(sys, 'frozen', False):
        # Если это исполняемый файл (PyInstaller)
        base_path = os.path.dirname(sys.executable)
    else:
        # Если это скрипт Python
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    # Создаем путь к директории logs относительно исполняемого файла
    logs_dir = os.path.join(base_path, 'logs')
    
    # Создаем директорию logs, если она не существует
    os.makedirs(logs_dir, exist_ok=True)
    
    # Путь к файлу лога
    log_file = os.path.join(logs_dir, log_filename)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def start_monitoring(app, ui, callback):
    """Запуск мониторинга."""

    async def process():
        logger.info("Запуск задачи мониторинга")
        ui.status_label.config(text="Состояние: Мониторинг запущен")
        app.running = True
        try:
            await callback()
        except Exception as e:
            logger.error(f"Ошибка при мониторинге: {e}")
            ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
        finally:
            app.running = False
            ui.status_label.config(text="Состояние: Мониторинг остановлен")
            logger.info("Задача мониторинга остановлена")

    return process()


def stop_monitoring(app, ui):
    """Остановка мониторинга."""

    async def stop_process():
        logger.info("Остановка мониторинга")
        if app.running:
            app.running = False
            ui.status_label.config(text="Состояние: Мониторинг остановлен")
            logger.info("Мониторинг остановлен")
        else:
            logger.warning("Мониторинг не запущен")
            ui.status_label.config(text="Состояние: Мониторинг не запущен")

    return stop_process()


def save_to_csv(app, ui, callback, send_files):
    """Сохранение строк в CSV и отправка файлов."""

    async def process():
        logger.info("Запуск задачи сохранения в CSV")
        ui.status_label.config(text="Состояние: Сохранение в CSV...")
        try:
            await callback()
            await send_files()
            ui.status_label.config(text="Состояние: Сохранение в CSV завершено")
            logger.info("Задача сохранения в CSV завершена")
        except Exception as e:
            logger.error(f"Ошибка при сохранении в CSV: {e}")
            ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")

    return process()


def send_strings(app, ui, callback):
    """Отправка строк в Telegram."""

    async def process():
        logger.info("Запуск задачи отправки строк")
        ui.status_label.config(text="Состояние: Отправка строк...")
        try:
            await callback()
            ui.status_label.config(text="Состояние: Отправка строк завершена")
            logger.info("Задача отправки строк завершена")
        except Exception as e:
            logger.error(f"Ошибка при отправке строк: {e}")
            ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")

    return process()


def run_async_task(app, coro_or_func):
    """Запуск асинхронной задачи в цикле событий без блокировки UI."""
    def wrapper():
        loop = app.ensure_loop()
        try:
            coro = coro_or_func() if callable(coro_or_func) else coro_or_func
            logger.info(f"Запуск асинхронной задачи: {getattr(coro, '__name__', str(coro))}")
            asyncio.run_coroutine_threadsafe(coro, loop)  # ✅ запускает задачу немедленно
        except Exception as e:
            logger.error(f"Ошибка при запуске задачи {getattr(coro_or_func, '__name__', str(coro_or_func))}: {e}")
            app.ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
    return wrapper




def start_runnable(func):
    """Декоратор для логирования выполнения функции."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(f"Запуск функции: {func.__name__}")
        result = func(*args, **kwargs)
        logger.info(f"Функция {func.__name__} завершена")
        return result

    return wrapper