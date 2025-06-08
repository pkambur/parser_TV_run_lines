import os
import logging
import asyncio
import threading
from datetime import datetime

def setup_logging():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/main_log.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def run_asyncio_loop(loop, parser_task):
    try:
        loop.run_forever()
    except Exception as e:
        logging.getLogger(__name__).error(f"Ошибка в цикле asyncio: {e}")
    finally:
        loop.close()

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
        app.asyncio_thread = threading.Thread(target=run_asyncio_loop, args=(app.loop, app.parser_task), daemon=True)
        app.asyncio_thread.start()

        app.parser_task = app.loop.create_task(run_parser_lines())

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

def save_rbk_mir24(app, ui, process_rbk_mir24, send_files):
    logger = logging.getLogger(__name__)
    logger.info("Сохранение строк РБК и МИР24")
    ui.status_label.config(text="Состояние: Обработка РБК и МИР24...")
    try:
        output_file, screenshot_files = process_rbk_mir24()
        send_files(output_file, screenshot_files)
        ui.status_label.config(text="Состояние: Сохранение РБК и МИР24 завершено")
        logger.info(f"Сохранение строк РБК и МИР24 завершено в {output_file}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении РБК и МИР24: {e}")
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")

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