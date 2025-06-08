import os
import json
import asyncio
import logging
from asyncio.subprocess import create_subprocess_exec

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/screenshot_log.log"),  # Логи в файл
        logging.StreamHandler()  # Логи в консоль
    ]
)
logger = logging.getLogger(__name__)

# Общая папка для скриншотов
base_dir = "screenshots"

# Убедимся, что базовая папка существует
os.makedirs(base_dir, exist_ok=True)

# Путь к ffmpeg
ffmpeg_path = r"c:/Program Files/ffmpeg/bin/ffmpeg.exe"

# Загрузка конфигурации из файла
with open("channels.json", "r", encoding="utf-8") as f:
    channels = json.load(f)

# Асинхронная функция для проверки доступности потока
async def check_stream_availability(url):
    try:
        process = await create_subprocess_exec(
            ffmpeg_path, "-i", url, "-t", "2", "-f", "null", "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if "Input/output error" in stderr.decode():
            logger.warning(f"Ошибка доступа к потоку: {url}")
            return False
        return True
    except Exception as e:
        logger.error(f"Ошибка при проверке потока {url}: {e}")
        return False

# Асинхронная функция для обработки канала
async def process_channel(channel_name, settings):
    channel_dir = os.path.join(base_dir, channel_name)
    os.makedirs(channel_dir, exist_ok=True)

    # Формат имени файла с временной меткой
    file_name = f"{channel_name}_%Y-%m-%d_%H-%M-%S.jpg"
    screenshots_path = os.path.join(channel_dir, file_name)

    crop = settings.get("crop", "")
    interval = settings["interval"]
    url = settings["url"]

    # Проверка доступности потока
    if not await check_stream_availability(url):
        logger.warning(f"Поток недоступен: {channel_name}")
        return

    # Фильтр для ffmpeg
    vf_filter = f"fps={interval}"
    if crop:
        vf_filter += f",{crop}"

    headers = (
        "Referer: https://tvc.ru\n"
        "User-Agent: Mozilla/5.0"
    )

    # Команда ffmpeg с оптимизацией
    command = [
        ffmpeg_path,
        "-headers", headers,
        "-i", url,
        "-vf", vf_filter,
        "-q:v", "2",  # Высокое качество изображения
        "-preset", "ultrafast",  # Быстрая обработка
        "-strftime", "1",  # Временные метки в имени файла
        "-frames:v", "100",  # Ограничение на 100 скриншотов
        screenshots_path,
        "-hide_banner"
    ]

    logger.info(f"Запуск команды для канала: {channel_name}")
    try:
        process = await create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            logger.info(f"Обработка завершена для канала: {channel_name}")
        else:
            logger.error(f"Ошибка ffmpeg для {channel_name}: {stderr.decode()}")
    except Exception as e:
        logger.error(f"Ошибка при обработке {channel_name}: {e}")
    except FileNotFoundError:
        logger.error(f"Ошибка: путь к ffmpeg не найден: {ffmpeg_path}")

# Главная асинхронная функция
async def main():
    tasks = [process_channel(name, settings) for name, settings in channels.items()]
    await asyncio.gather(*tasks)

# Запуск программы
if __name__ == "__main__":
    asyncio.run(main())









# import os
# import shlex
# import subprocess
# from concurrent.futures import ThreadPoolExecutor
#
# # Словарь телеканалов с URL, областью обрезки и интервалами скриншотов
# channels = {
#     "RBK": {
#         "url": "https://e2-online-video.rbc.ru/online2/rbctvhd_1080p/index.m3u8?e=e2&t=Izzi0I",
#         "interval": "1/14",  # каждую 14-ю секунду
#         "crop": "crop=1500:45:330:960"
#     },
#     "NTV": {
#         "url": "https://river-1.rutube.ru/stream/genetta-521.ost.rutube.ru/scQmYGtQxAGuPUX6d0qN7g/1737020538/c37cd74192c6bc3d6cd6077c0c4fd686/1080p_stream.m3u8",
#         "interval": "1/10",  # каждую 10-ю секунду
#         "crop": "crop=1915:50:2:910"
#     },
#     # "Москва24": {
#     #     "url": "https://www.m24.ru/trans/air/480p.m3u8?e=1736524800&s=Jfm2RCX4H-3SKCR3YZRkIA",
#     #     "interval": "1/10",  # каждую 10-ю секунду
#     # "crop": "crop=650:40:200:430"
#     # },
#
#     # "ОТР": {
#     #     "url": "https://salam-mskth-46.rutube.ru/dive/river-5-515.rutube.ru/JI69YojIIk42GvloWx_qMg/stream/genetta-333.m9.rutube.ru/bJm1Q9mr_ZMb6wsDJxtoZA/1737026139/faa934385b83f9e8a92f5484defae5fa/720p_stream.m3u8",
#     #     "interval": "1/11"  # каждую 11-ю секунду
#     # },
#     "360": {
#         "url": "https://e10-ll.facecast.io/evacoder_hls_hi/UBZfFgtKB1JwTwoDERNQVGGs/1.m3u8",
#         "interval": "1/7",  # каждую 7-ю секунду
#         "crop": "crop=1110:45:120:640"
#     },
#     "Звезда": {
#         "url": "https://tvzvezda.bonus-tv.ru/cdn/tvzvezda/playlist.m3u8",
#         "interval": "1/12",  # каждую 12-ю секунду
#         "crop": "crop=1810:60:370:970"
#     },
#     "MIR24": {
#         "url": "https://hls-mirtv.cdnvideo.ru/mirtv-parampublish/mir24_2500/tracks-v1a1/mono.m3u8?hls_proxy_host=fcf2a4d016d46058e02842aa89871fce",
#         "interval": "1/7",  # каждую 7-ю секунду
#         "crop": "crop=1405:55:515:980"
#     },
#     "Известия": {
#         "url": "http://hls-igi.cdnvideo.ru/igi/igi_hq/tracks-v1a1/mono.m3u8?hls_proxy_host=f4eb0d287702d48f6bbf6e6f56891e63",
#         "interval": "1/11",  # каждую 11-ю секунду
#         "crop": "crop=1280:720:0:0"
#     },
#     "R1": {
#         "url": "https://vgtrkregion-reg.cdnvideo.ru/vgtrk/0/russia1-hd/1080p.m3u8",
#         "interval": "1/11",  # каждую 11-ю секунду
#         "crop": "crop=0:0:1920:1080"
#     },
#     "ТВЦ": {
#         "url": "https://tvc-hls.cdnvideo.ru/tvc-res/smil:vd9221_2.smil/12ed865707c77a12eeecfa3177775684--tvc-res--vd9221_480p_2--tracks-v1a1--mono.m3u8?hls_proxy_host=22b5db40ced763465289cd8236e019fb",
#         "interval": "1/8",  # каждую 8-ю секунду
#         "crop": "crop=1813:60:320:960"
#     },
#     "R24_white_line": {
#         "url": "https://vgtrkregion-reg.cdnvideo.ru/vgtrk/0/russia24-sd/2081200_576p.m3u8",
#         "interval": "1/12",  # каждую 12-ю секунду
#         "crop": "crop=1020:30:2:530"
#     },
#     "R24_blue_line": {
#         "url": "https://vgtrkregion-reg.cdnvideo.ru/vgtrk/0/russia24-sd/2081200_576p.m3u8",
#         "interval": "1/10",  # каждую 10-ю секунду
#         "crop": "crop=1020:30:2:500"
#     # },
#     # "Р24_желтые": {
#     #     "url": "https://vgtrkregion-reg.cdnvideo.ru/vgtrk/0/russia24-sd/2081200_576p.m3u8",
#     #     "interval": "1/3",  # каждую 3-ю секунду
#     #     "crop": "crop=850:50:100:24"
#     }
#     # Добавьте остальные каналы
# }
#
# # Общая папка для скриншотов
# base_dir = "screenshots"
#
# # Убедимся, что базовая папка существует
# os.makedirs(base_dir, exist_ok=True)
#
# # Путь к ffmpeg
# ffmpeg_path = r"c:/Program Files/ffmpeg/bin/ffmpeg.exe"
#
# # Функция для проверки доступности потока
# def check_stream_availability(url):
#     try:
#         result = subprocess.run(
#             [ffmpeg_path, "-i", url, "-t", "2", "-f", "null", "-"],
#             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
#         )
#         if "Input/output error" in result.stderr:
#             print(f"Ошибка доступа к потоку: {url}")
#             return False
#         return True
#     except Exception as e:
#         print(f"Ошибка при проверке потока: {url}, {e}")
#         return False
#
# # Функция для выполнения задачи
# def process_channel(channel_name, settings):
#     channel_dir = os.path.join(base_dir, channel_name)
#     os.makedirs(channel_dir, exist_ok=True)
#
#     # Формат имени файла с временной меткой
#     file_name = f"{channel_name}_%Y-%m-%d_%H-%M-%S.jpg"
#     screenshots_path = os.path.join(channel_dir, file_name)
#
#     crop = settings.get("crop", "")
#     interval = settings["interval"]
#     url = settings["url"]
#
#     # Проверяем доступность потока
#     if not check_stream_availability(url):
#         print(f"Поток недоступен: {channel_name}")
#         return
#
#     vf_filter = f"fps={interval}"
#     if crop:
#         vf_filter += f",{crop}"
#
#     headers = (
#         "Referer: https://tvc.ru\n"
#         "User-Agent: Mozilla/5.0"
#     )
#
#     command = [
#         ffmpeg_path,
#         "-headers", headers,
#         "-i", url,
#         "-vf", vf_filter,
#         "-strftime", "1",  # Включаем поддержку временных меток в имени файла
#         screenshots_path,
#         "-hide_banner"
#     ]
#
#     print(f"Запуск команды для канала: {channel_name}")
#     try:
#         subprocess.run(command, check=True)
#         print(f"Обработка завершена для канала: {channel_name}")
#     except subprocess.CalledProcessError as e:
#         print(f"Ошибка при обработке {channel_name}: {e}")
#     except FileNotFoundError:
#         print(f"Ошибка: путь к ffmpeg не найден: {ffmpeg_path}")
#
# # Запуск задач в параллельном режиме
# with ThreadPoolExecutor() as executor:
#     futures = [executor.submit(process_channel, name, settings) for name, settings in channels.items()]
#     for future in futures:
#         future.result()