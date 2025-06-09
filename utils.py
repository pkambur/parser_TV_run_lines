import os
import logging
import asyncio
import threading
from datetime import datetime

def setup_logging():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
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
        if not loop.is_closed():
            tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in tasks:
                task.cancel()
                try:
                    loop.run_until_complete(task)
                except asyncio.CancelledError:
                    pass
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

async def start_monitoring(app, ui, run_parser_lines):
    if not app.running:
        logger = logging.getLogger(__name__)
        logger.info("Запуск мониторинга")
        ui.status_label.config(text="Состояние: Мониторинг запущен")
        ui.start_button.config(state="disabled")
        ui.stop_button.config(state="normal")
        app.running = True

        if not app.loop or app.loop.is_closed():
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
        if app.parser_task and not app.parser_task.done():
            app.parser_task.cancel()
            try:
                await app.parser_task
            except asyncio.CancelledError:
                logger.info("Задача мониторинга успешно отменена")
        if app.loop and not app.loop.is_closed():
            tasks = [t for t in asyncio.all_tasks(app.loop) if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
                try:
                    app.loop.run_until_complete(task)
                except asyncio.CancelledError:
                    pass
            app.loop.call_soon_threadsafe(app.loop.stop)
            app.loop.run_until_complete(app.loop.shutdown_asyncgens())
            app.loop.close()
            app.loop = None
            app.asyncio_thread = None
        ui.status_label.config(text="Состояние: Мониторинг остановлен")
        ui.start_button.config(state="normal")
        ui.stop_button.config(state="disabled")
        app.running = False

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
    if not app.loop or app.loop.is_closed():
        app.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(app.loop)
        app.asyncio_thread = threading.Thread(target=run_asyncio_loop, args=(app.loop,), daemon=True)
        app.asyncio_thread.start()
    future = asyncio.run_coroutine_threadsafe(coro, app.loop)
    return future