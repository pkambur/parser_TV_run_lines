import os
import logging
import asyncio
import threading
from datetime import datetime

# Установка конфигурации логгера (в файл + консоль)
def setup_logging():
    os.makedirs("logs", exist_ok=True)  # Создаём папку logs, если её нет
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/main_log.log"),  # Лог в файл
            logging.StreamHandler()                   # Лог в консоль
        ]
    )
    return logging.getLogger(__name__)  # Возвращаем логгер текущего модуля

# Отдельный поток для запуска asyncio-цикла
def run_asyncio_loop(loop, parser_task):
    try:
        loop.run_forever()  # Запускаем бесконечный цикл событий
    except Exception as e:
        logging.getLogger(__name__).error(f"Ошибка в цикле asyncio: {e}")
    finally:
        loop.close()

# Запуск основного мониторинга
def start_monitoring(app, ui, run_parser_lines):
    if not app.running:
        logger = logging.getLogger(__name__)
        logger.info("Запуск мониторинга")
        ui.status_label.config(text="Состояние: Мониторинг запущен")
        ui.start_button.config(state="disabled")
        ui.stop_button.config(state="normal")
        app.running = True

        app.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(app.loop)
        app.asyncio_thread = threading.Thread(
            target=run_asyncio_loop,
            args=(app.loop, app.parser_task),
            daemon=True
        )
        app.asyncio_thread.start()

        # Запуск задачи в новом asyncio-цикле
        app.parser_task = app.loop.create_task(run_parser_lines())

# Остановка мониторинга
def stop_monitoring(app, ui):
    if app.running:
        logger = logging.getLogger(__name__)
        logger.info("Остановка мониторинга")
        ui.status_label.config(text="Состояние: Мониторинг остановлен")
        ui.start_button.config(state="normal")
        ui.stop_button.config(state="disabled")
        app.running = False

        if app.parser_task:
            app.loop.call_soon_threadsafe(app.parser_task.cancel)
        if app.loop:
            app.loop.call_soon_threadsafe(app.loop.stop)

# Обработка строк РБК и МИР24
def save_rbk_mir24(app, ui, process_rbk_mir24, send_files):
    logger = logging.getLogger(__name__)
    logger.info("Сохранение строк РБК и МИР24")
    ui.status_label.config(text="Состояние: Обработка РБК и МИР24...")
    ui.rbk_mir24_button.config(state="disabled")
    ui.stop_rbk_mir24_button.config(state="normal")
    try:
        output_file, screenshot_files = process_rbk_mir24()
        send_files(output_file, screenshot_files)
        ui.status_label.config(text="Состояние: Сохранение РБК и МИР24 завершено")
        logger.info(f"Сохранение строк РБК и МИР24 завершено в {output_file}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении РБК и МИР24: {e}")
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
    finally:
        ui.rbk_mir24_button.config(state="normal")
        ui.stop_rbk_mir24_button.config(state="disabled")

# Принудительная остановка обработки РБК/МИР24
def stop_rbk_mir24(app, ui):
    logger = logging.getLogger(__name__)
    logger.info("Остановка парсинга РБК и МИР24")
    ui.status_label.config(text="Состояние: Парсинг РБК и МИР24 остановлен")
    ui.rbk_mir24_button.config(state="normal")
    ui.stop_rbk_mir24_button.config(state="disabled")

    # Попытка отменить задачу, если она существует и активна
    if hasattr(app, 'rbk_mir24_task') and app.rbk_mir24_task:
        if not app.rbk_mir24_task.done():
            logger.info("Отмена асинхронной задачи РБК/МИР24")
            app.loop.call_soon_threadsafe(app.rbk_mir24_task.cancel)
        app.rbk_mir24_task = None

def save_to_csv(app, ui, process_screenshots, send_files):
    logger = logging.getLogger(__name__)
    logger.info("Сохранение строк остальных каналов")
    ui.status_label.config(text="Состояние: Обработка остальных каналов...")
    try:
        output_file, screenshot_files = process_screenshots()
        send_files(output_file, screenshot_files)
        ui.status_label.config(text="Состояние: Сохранение остальных каналов завершено")
        logger.info(f"Сохранение строк остальных каналов завершено в {output_file}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении остальных каналов: {e}")
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")

async def send_strings_async(app, ui, send_to_telegram):
    logger = logging.getLogger(__name__)
    logger.info("Отправка строк в Telegram")
    ui.status_label.config(text="Состояние: Отправка строк...")
    ui.send_strings_button.config(state="disabled")
    try:
        await send_to_telegram()  # Вызов асинхронной функции
        ui.status_label.config(text="Состояние: Отправка строк завершена")
        logger.info("Отправка строк в Telegram завершена")
    except Exception as e:
        logger.error(f"Ошибка при отправке строк в Telegram: {e}")
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
    finally:
        ui.send_strings_button.config(state="normal")

def send_strings(app, ui, send_to_telegram):
    if app.loop and app.loop.is_running():
        # Если цикл уже запущен, используем его
        asyncio.run_coroutine_threadsafe(send_strings_async(app, ui, send_to_telegram), app.loop)
    else:
        # Создаем новый цикл для выполнения асинхронной функции
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(send_strings_async(app, ui, send_to_telegram))
        finally:
            loop.close()
