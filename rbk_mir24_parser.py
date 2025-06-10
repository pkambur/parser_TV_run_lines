import os
import logging
import json
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)
base_dir = "screenshots"
VIDEO_DURATION = 20  # Для теста, в проде — 240

def load_channels():
    try:
        logger.info("Начало загрузки channels.json")
        with open("channels.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке channels.json: {e}")
        return {}

async def record_video(channel_name, channel_info, process_list):
    try:
        logger.info(f"Подготовка записи для {channel_name}")
        output_dir = os.path.join(base_dir, channel_name)
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = os.path.join(output_dir, f"{channel_name}_video_{timestamp}.mp4")

        cmd = [
            "ffmpeg",
            "-i", channel_info["url"],
            "-t", str(VIDEO_DURATION),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-y"
        ]

        if "crop" in channel_info:
            cmd.extend(["-vf", channel_info["crop"]])

        cmd.append(output_path)

        logger.info(f"Запуск записи видео для {channel_name}: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        process_list.append(process)

        try:
            await process.communicate()
        except asyncio.CancelledError:
            logger.info(f"Запись видео для {channel_name} отменена")
            process.kill()
            await process.wait()
            raise
        finally:
            if process in process_list:
                process_list.remove(process)

        if process.returncode != 0:
            error_msg = (await process.stderr.read()).decode()
            logger.error(f"Ошибка ffmpeg при записи {channel_name}: {error_msg}")
        else:
            logger.info(f"Видео сохранено: {output_path}")

    except Exception as e:
        logger.error(f"Ошибка при записи {channel_name}: {e}")

async def process_rbk_mir24(app, ui, send_files):
    logger.info("Запуск записи видеопотоков РБК и МИР24")
    ui.status_label.config(text="Состояние: Запись РБК и МИР24...")
    ui.rbk_mir24_button.config(state="disabled")
    ui.stop_rbk_mir24_button.config(state="normal")

    process_list = []
    record_tasks = []

    try:
        channels_data = load_channels()
        channels = ["RBK", "MIR24"]

        for name in channels:
            if name in channels_data:
                task = asyncio.create_task(record_video(name, channels_data[name], process_list))
                record_tasks.append(task)

        await asyncio.gather(*record_tasks)

        ui.status_label.config(text="Состояние: Запись РБК и МИР24 завершена")
        logger.info("Запись видеопотоков РБК и МИР24 завершена")

    except asyncio.CancelledError:
        logger.info("Отмена всех задач записи")
        for task in record_tasks:
            task.cancel()
        await asyncio.gather(*record_tasks, return_exceptions=True)

        for proc in process_list:
            proc.kill()
            await proc.wait()

        process_list.clear()
        ui.status_label.config(text="Состояние: Запись РБК и МИР24 остановлена")
        raise

    finally:
        ui.rbk_mir24_button.config(state="normal")
        ui.stop_rbk_mir24_button.config(state="disabled")
        logger.info("Очистка задачи и обновление UI завершены")

async def stop_rbk_mir24(app, ui):
    logger.info("Остановка записи РБК и МИР24")
    if app.rbk_mir24_task and not app.rbk_mir24_task.done():
        app.rbk_mir24_task.cancel()
        try:
            await app.rbk_mir24_task
        except asyncio.CancelledError:
            logger.info("Задача записи успешно отменена")
        ui.status_label.config(text="Состояние: Запись остановлена")
    else:
        ui.status_label.config(text="Состояние: Нет активной записи")
    ui.rbk_mir24_button.config(state="normal")
    ui.stop_rbk_mir24_button.config(state="disabled")
