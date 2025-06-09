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


def parse_interval(interval_str):
    """Парсит строку интервала (например, '1/7') и возвращает количество секунд."""
    try:
        if not interval_str or '/' not in interval_str:
            logger.warning(f"Некорректный формат интервала: {interval_str}. Используется 10 секунд.")
            return 10
        numerator, denominator = interval_str.split('/')
        interval = int(denominator) / int(numerator)
        if interval <= 0:
            raise ValueError("Интервал должен быть положительным")
        return interval
    except (ValueError, TypeError) as e:
        logger.error(f"Ошибка парсинга интервала {interval_str}: {e}. Используется 10 секунд.")
        return 10


async def run_ffmpeg(channel_name, channel_info):
    """Запускает FFmpeg для создания скриншота с указанного URL."""
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

        # Добавляем обрезку, если указано
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


async def process_channel(channel):
    """Запускает цикл создания скриншотов для одного канала с заданным интервалом."""
    channel_name = channel["name"]
    interval = parse_interval(channel.get("interval", "1/10"))
    logger.info(f"Запуск обработки канала {channel_name} с интервалом {interval} секунд")

    try:
        while True:
            await run_ffmpeg(channel_name, channel)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info(f"Обработка канала {channel_name} остановлена")
        raise


async def stop_subprocesses():
    """Завершает все подпроцессы FFmpeg."""
    logger.info("Завершение всех подпроцессов FFmpeg")
    try:
        for process in subprocesses:
            if process.returncode is None:  # Проверяем, что процесс активен
                try:
                    logger.info(f"Завершение процесса: {process.pid}")
                    process.terminate()  # Мягкое завершение
                    await asyncio.sleep(1)
                    if process.returncode is None:
                        logger.warning(f"Процесс {process.pid} не завершился, принудительное завершение")
                        process.kill()  # Принудительное завершение
                except Exception as e:
                    logger.error(f"Ошибка при завершении процесса {process.pid}: {e}")
        subprocesses.clear()  # Очищаем список
    except Exception as e:
        logger.error(f"Ошибка при завершении подпроцессов: {e}")


async def main():
    """Основная функция для запуска парсинга всех каналов."""
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

        # Преобразуем словарь в список каналов
        channels = [
            {"name": name, "url": info["url"], "interval": info.get("interval"), "crop": info.get("crop")}
            for name, info in channels_data.items()
        ]

        if not channels:
            logger.error("В channels.json отсутствуют каналы")
            raise ValueError("Список каналов пуст")

        logger.info(f"Загружены каналы: {channels}")

        # Создаем отдельную задачу для каждого канала
        tasks = [asyncio.create_task(process_channel(channel)) for channel in channels]

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("Парсинг строк остановлен")
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await stop_subprocesses()
            raise

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