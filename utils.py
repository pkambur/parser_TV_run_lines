import asyncio
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def setup_logging():
    """Настройка логирования."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/main_log.txt', encoding='utf-8'),
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


def run_async_task(app, coro):
    """Запуск асинхронной задачи в цикле событий."""

    def wrapper():
        loop = app.ensure_loop()
        task = None
        try:
            logger.info(f"Запуск асинхронной задачи: {coro.__name__}")
            task = loop.create_task(coro)
            # Запускаем задачу в цикле событий без блокировки
            future = asyncio.run_coroutine_threadsafe(task, loop)
            future.result(timeout=600)  # Ожидаем завершения с таймаутом 10 минут
            logger.info(f"Асинхронная задача {coro.__name__} завершена")
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при выполнении задачи {coro.__name__}")
            if task:
                task.cancel()
            app.ui.status_label.config(text=f"Состояние: Таймаут задачи {coro.__name__}")
        except asyncio.CancelledError:
            logger.info(f"Задача {coro.__name__} отменена")
            app.ui.status_label.config(text=f"Состояние: Задача {coro.__name__} отменена")
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи {coro.__name__}: {e}")
            app.ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
        finally:
            if task and not task.done():
                task.cancel()
            logger.info(f"Очистка задачи {coro.__name__}")

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