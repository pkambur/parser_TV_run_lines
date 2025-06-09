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

def run_asyncio_loop(loop):
    try:
        loop.run_forever()
    except Exception as e:
        logging.getLogger(__name__).error(f"Ошибка в цикле asyncio: {e}")
    finally:
        loop.close()

async def start_monitoring(app, ui, run_parser_lines):
    if not app.running:
        logger = logging.getLogger(__name__)
        logger.info("Запуск мониторинга")
        ui.status_label.config(text="Состояние: Мониторинг запущен")
        ui.start_button.config(state="disabled")
        ui.stop_button.config(state="normal")
        app.running = True

        app.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(app.loop)
        app.asyncio_thread = threading.Thread(target=run_asyncio_loop, args=(app.loop,), daemon=True)
        app.asyncio_thread.start()

        app.parser_task = app.loop.create_task(run_parser_lines())
        try:
            await app.parser_task
        except asyncio.CancelledError:
            logger.info("Мониторинг остановлен")
            ui.status_label.config(text="Состояние: Мониторинг остановлен")
            ui.start_button.config(state="normal")
            ui.stop_button.config(state="disabled")
            app.running = False

async def stop_monitoring(app, ui):
    if app.running:
        logger = logging.getLogger(__name__)
        logger.info("Остановка мониторинга")
        if app.parser_task:
            app.parser_task.cancel()
        if app.loop:
            app.loop.call_soon_threadsafe(app.loop.stop)

async def save_rbk_mir24(app, ui, process_rbk_mir24, send_files):
    logger = logging.getLogger(__name__)
    logger.info("Сохранение строк РБК и МИР24")
    ui.status_label.config(text="Состояние: Обработка РБК и МИР24...")
    ui.rbk_mir24_button.config(state="disabled")
    ui.stop_rbk_mir24_button.config(state="normal")
    try:
        app.rbk_mir24_task = app.loop.create_task(process_rbk_mir24())
        output_file, screenshot_files = await app.rbk_mir24_task
        if output_file and screenshot_files:
            await send_files(output_file, screenshot_files)
        ui.status_label.config(text="Состояние: Сохранение РБК и МИР24 завершено")
        logger.info(f"Сохранение строк РБК и МИР24 завершено в {output_file}")
    except asyncio.CancelledError:
        logger.info("Парсинг РБК и МИР24 остановлен")
        ui.status_label.config(text="Состояние: Парсинг РБК и МИР24 остановлен")
    except Exception as e:
        logger.error(f"Ошибка при сохранении РБК и МИР24: {e}")
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
    finally:
        ui.rbk_mir24_button.config(state="normal")
        ui.stop_rbk_mir24_button.config(state="disabled")
        app.rbk_mir24_task = None

async def stop_rbk_mir24(app, ui):
    logger = logging.getLogger(__name__)
    logger.info("Остановка парсинга РБК и МИР24")
    if app.rbk_mir24_task:
        app.rbk_mir24_task.cancel()
        try:
            await app.rbk_mir24_task
        except asyncio.CancelledError:
            pass

async def save_to_csv(app, ui, process_screenshots, send_files):
    logger = logging.getLogger(__name__)
    logger.info("Сохранение строк остальных каналов")
    ui.status_label.config(text="Состояние: Обработка остальных каналов...")
    try:
        output_file, screenshot_files = await process_screenshots()
        if output_file and screenshot_files:
            await send_files(output_file, screenshot_files)
        ui.status_label.config(text="Состояние: Сохранение остальных каналов завершено")
        logger.info(f"Сохранение строк остальных каналов завершено в {output_file}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении остальных каналов: {e}")
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")

async def send_strings(app, ui, send_to_telegram):
    logger = logging.getLogger(__name__)
    logger.info("Отправка строк в Telegram")
    ui.status_label.config(text="Состояние: Отправка строк...")
    ui.send_strings_button.config(state="disabled")
    try:
        await send_to_telegram()
        ui.status_label.config(text="Состояние: Отправка строк завершена")
        logger.info("Отправка строк в Telegram завершена")
    except Exception as e:
        logger.error(f"Ошибка при отправке строк в Telegram: {e}")
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
    finally:
        ui.send_strings_button.config(state="normal")

def run_async_task(app, coro):
    if not app.loop or not app.loop.is_running():
        app.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(app.loop)
        app.asyncio_thread = threading.Thread(target=run_asyncio_loop, args=(app.loop,), daemon=True)
        app.asyncio_thread.start()
    asyncio.run_coroutine_threadsafe(coro, app.loop)