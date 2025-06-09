import os
import logging
import json
import asyncio
from datetime import datetime

# Настройка логирования
logger = logging.getLogger(__name__)

# Папка для скриншотов
base_dir = "screenshots"

# Длительность записи видео (в секундах)
VIDEO_DURATION = 20  # Для тестов. В проде — 240

# Загрузка каналов из channels.json
def load_channels():
    try:
        logger.info("Начало загрузки channels.json")
        with open("channels.json", "r", encoding="utf-8") as f:
            channels_data = json.load(f)
        logger.info("channels.json успешно загружен")
        return channels_data
    except FileNotFoundError:
        logger.error("Файл channels.json не найден")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка формата JSON в channels.json: {e}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке channels.json: {e}")
        return {}

# Асинхронная запись видеопотока
async def record_video(channel_name, channel_info, process_list):
    try:
        logger.info(f"Подготовка записи для {channel_name}")
        output_dir = os.path.join(base_dir, channel_name)
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = os.path.join(output_dir, f"{channel_name}_video_{timestamp}.mp4")

        # Команда ffmpeg
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
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=VIDEO_DURATION + 30)
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при записи видео для {channel_name}")
            process.kill()
            await process.wait()
            process_list.remove(process)
            return None, "Таймаут записи"
        except asyncio.CancelledError:
            logger.info(f"Запись видео для {channel_name} отменена")
            process.kill()
            await process.wait()
            process_list.remove(process)
            raise

        process_list.remove(process)

        if process.returncode != 0:
            error_msg = stderr.decode()
            logger.error(f"Ошибка ffmpeg при записи видео для {channel_name}: {error_msg}")
            return None, error_msg
        else:
            logger.info(f"Видео сохранено: {output_path}")
            return output_path, None

    except asyncio.CancelledError:
        logger.info(f"Запись видео для {channel_name} отменена")
        if process in process_list:
            process.kill()
            await process.wait()
            process_list.remove(process)
        raise
    except Exception as e:
        logger.error(f"Ошибка при записи видео для {channel_name}: {e}")
        if process in process_list:
            process_list.remove(process)
        return None, str(e)

# Основной процесс обработки РБК и МИР24
async def process_rbk_mir24(app, ui, send_files):
    logger.info("Запуск записи видеопотоков РБК и МИР24")
    ui.status_label.config(text="Состояние: Запись РБК и МИР24...")
    ui.rbk_mir24_button.config(state="disabled")
    ui.stop_rbk_mir24_button.config(state="normal")

    process_list = []

    try:
        channels_data = load_channels()
        channels = ["RBK", "MIR24"]

        if not channels_data:
            logger.error("Не удалось загрузить channels.json")
            ui.status_label.config(text="Состояние: Ошибка: channels.json не найден")
            return

        record_tasks = []
        for channel_name in channels:
            if channel_name not in channels_data:
                logger.warning(f"Канал {channel_name} отсутствует в channels.json")
                continue
            channel_info = channels_data[channel_name]
            logger.info(f"Запись записи для канала: {channel_name}")
            record_tasks.append(record_video(channel_name, channel_info, process_list))

        results = await asyncio.gather(*record_tasks, return_exceptions=True)

        for channel_name, result in zip(channels, results):
            if isinstance(result, Exception):
                logger.error(f"Исключение при записи {channel_name}: {result}")
                continue
            video_path, error_msg = result
            if not video_path:
                logger.error(f"Не удалось записать видео для {channel_name}: {error_msg}")
                continue
            logger.info(f"Видео для {channel_name} успешно записано: {video_path}")

        logger.info("Запись видеопотоков РБК и МИР24 завершена")
        ui.status_label.config(text="Состояние: Запись РБК и МИР24 завершена")

    except asyncio.CancelledError:
        logger.info("Запись РБК и МИР24 остановлена")
        for process in process_list:
            process.kill()
            await process.wait()
        process_list.clear()
        ui.status_label.config(text="Состояние: Запись РБК и МИР24 остановлена")
        raise
    except Exception as e:
        logger.error(f"Ошибка при записи РБК и МИР24: {e}")
        for process in process_list:
            process.kill()
            await process.wait()
        process_list.clear()
        ui.status_label.config(text=f"Состояние: Ошибка: {str(e)}")
    finally:
        ui.rbk_mir24_button.config(state="normal")
        ui.stop_rbk_mir24_button.config(state="disabled")
        logger.info("Очистка задачи и обновление UI завершены")

# Остановка записи вручную
async def stop_rbk_mir24(app, ui):
    logger.info("Остановка записи РБК и МИР24")
    if app.rbk_mir24_task and not app.rbk_mir24_task.done():
        app.rbk_mir24_task.cancel()
        try:
            await app.rbk_mir24_task
        except asyncio.CancelledError:
            logger.info("Задача записи РБК и МИР24 успешно отменена")
        ui.status_label.config(text="Состояние: Запись РБК и МИР24 остановлена")
    else:
        logger.warning("Нет активной задачи записи РБК и МИР24 для остановки")
        ui.status_label.config(text="Состояние: Нет активной записи РБК и МИР24")

    ui.rbk_mir24_button.config(state="normal")
    ui.stop_rbk_mir24_button.config(state="disabled")
    logger.info("Остановка задачи и обновление UI завершены")
