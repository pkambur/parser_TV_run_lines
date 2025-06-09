import asyncio
import json
import os
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/parser_lines_log.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Глобальный список для хранения подпроцессов
subprocesses = []


async def run_ffmpeg(channel_name, channel_info):
    try:
        output_dir = os.path.join("screenshots", channel_name)
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = os.path.join(output_dir, f"{channel_name}_{timestamp}.jpg")

        # Базовая команда FFmpeg
        cmd = [
            "ffmpeg",
            "-i", channel_info["url"],
            "-vframes", "1",
            "-q:v", "2"
        ]

        # Добавляем обрезку, если указано в channel_info
        if "crop" in channel_info:
            cmd.extend(["-vf", channel_info["crop"]])

        cmd.append(output_path)

        logger.info(f"Запуск команды для {channel_name}: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        subprocesses.append(process)  # Сохраняем подпроцесс

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"Ошибка ffmpeg для {channel_name}: {stderr.decode()}")
        else:
            logger.info(f"Скриншот сохранен: {output_path}")
    except Exception as e:
        logger.error(f"Ошибка при создании скриншота для {channel_name}: {e}")


async def stop_subprocesses():
    logger.info("Завершение всех подпроцессов FFmpeg")
    try:
        for process in subprocesses:
            if process.returncode is None:  # Проверяем, что процесс еще активен
                try:
                    logger.info(f"Завершение процесса: {process.pid}")
                    process.terminate()  # Пытаемся завершить мягко
                    await asyncio.sleep(1)  # Ждем немного
                    if process.returncode is None:
                        logger.warning(f"Процесс {process.pid} не завершился, принудительное завершение")
                        process.kill()  # Принудительное завершение
                except Exception as e:
                    logger.error(f"Ошибка при завершении процесса {process.pid}: {e}")
        subprocesses.clear()  # Очищаем список
    except Exception as e:
        logger.error(f"Ошибка при завершении подпроцессов: {e}")


async def main():
    try:
        if not os.path.exists("channels.json"):
            logger.error("Файл channels.json не найден")
            raise FileNotFoundError("Файл channels.json не найден")

        with open("channels.json", "r", encoding="utf-8") as f:
            try:
                channels_data = json.load(f)
                if not isinstance(channels_data, dict):
                    logger.error("channels.json должен содержать словарь с каналами")
                    raise ValueError("Неверный формат channels.json")
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка формата JSON в channels.json: {e}")
                raise

        # Преобразуем словарь в список для удобства обработки
        channels = [
            {"name": name, "url": info["url"], "interval": info.get("interval"), "crop": info.get("crop")}
            for name, info in channels_data.items()
        ]

        if not channels:
            logger.error("В channels.json отсутствуют каналы")
            raise ValueError("Список каналов пуст")

        logger.info(f"Загружены каналы: {channels}")
        while True:
            logger.info("Запуск цикла парсинга")
            tasks = [run_ffmpeg(channel["name"], channel) for channel in channels]
            await asyncio.gather(*tasks, return_exceptions=True)
            # Используем фиксированный интервал 10 секунд, можно сделать настраиваемым
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        logger.info("Парсинг строк остановлен")
        await stop_subprocesses()
        raise
    except Exception as e:
        logger.error(f"Ошибка в парсинге строк: {e}")
        await stop_subprocesses()
        raise


if __name__ == "__main__":
    asyncio.run(main())