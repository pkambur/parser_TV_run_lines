import os
import sys
import logging
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from PIL import Image
import io
import shutil
import pandas as pd

# Настройка логирования
def setup_logging():
    """Настройка логирования для telegram_sender."""
    # Получаем путь к директории исполняемого файла
    if getattr(sys, 'frozen', False):
        # Если это исполняемый файл (PyInstaller)
        base_path = os.path.dirname(sys.executable)
    else:
        # Если это скрипт Python
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    # Создаем путь к директории logs относительно исполняемого файла
    logs_dir = os.path.join(base_path, 'logs')
    
    # Создаем директорию logs, если она не существует
    os.makedirs(logs_dir, exist_ok=True)
    
    # Путь к файлу лога
    log_file = os.path.join(logs_dir, 'telegram_sender_log.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# Telegram bot configuration
TELEGRAM_TOKEN = "7014463362:AAEDPF4MzfgxcZBwClW7nTONtJqk_04uJ4g"
CHAT_IDS = [984259692]  # Убраны кавычки, так как это должны быть числа 117436228
processed_dir = "screenshots_processed"
video_dir = "video"

# Максимальные размеры для Telegram
MAX_WIDTH = 1280
MAX_HEIGHT = 1280
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def get_video_files():
    """Получение списка видеофайлов из подпапок."""
    video_files = []
    try:
        for channel_name in os.listdir(video_dir):
            channel_dir = os.path.join(video_dir, channel_name)
            if os.path.isdir(channel_dir):
                for filename in os.listdir(channel_dir):
                    if filename.lower().endswith(('.mp4', '.avi', '.mkv')):
                        video_files.append(os.path.join(channel_dir, filename))
    except Exception as e:
        logger.error(f"Ошибка при получении списка видеофайлов: {e}")
    return video_files

def process_image(image_path):
    """Обработка изображения для соответствия требованиям Telegram."""
    try:
        with Image.open(image_path) as img:
            # Конвертируем в RGB если нужно
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Получаем текущие размеры
            width, height = img.size
            
            # Проверяем минимальные размеры (Telegram требует минимум 10x10)
            if width < 10 or height < 10:
                # Увеличиваем до минимального размера
                new_width = max(width, 10)
                new_height = max(height, 10)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Если изображение слишком большое, уменьшаем его
            if width > MAX_WIDTH or height > MAX_HEIGHT:
                # Вычисляем новые размеры с сохранением пропорций
                ratio = min(MAX_WIDTH / width, MAX_HEIGHT / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                
                # Изменяем размер
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Сохраняем во временный буфер
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)
            
            return buffer
    except Exception as e:
        logger.error(f"Ошибка при обработке изображения {image_path}: {e}")
        raise

async def send_to_telegram(excel_file, screenshot_files):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        sent_files = []  # Список для отслеживания успешно отправленных файлов
        available_chats = []  # Список доступных чатов

        # Проверяем доступность чатов
        for chat_id in CHAT_IDS:
            try:
                await bot.get_chat(chat_id)
                logger.info(f"Chat {chat_id} is available")
                available_chats.append(chat_id)
            except Exception as e:
                logger.error(f"Chat {chat_id} is not available: {e}")
                continue

        if not available_chats:
            logger.error("No available chats found")
            raise Exception("No available chats found")

        # Send Excel file and recognized text
        if os.path.exists(excel_file):
            try:
                # Читаем Excel файл
                df = pd.read_excel(excel_file)
                
                # Формируем сообщение с распознанными строками
                if not df.empty:
                    message = "Распознанные строки:\n\n"
                    for _, row in df.iterrows():
                        message += f"Канал: {row['Channel']}\n"
                        message += f"Время: {row['Timestamp']}\n"
                        message += f"Текст: {row['Text']}\n"
                        message += "-------------------\n"
                    
                    # Отправляем текст
                    for chat_id in available_chats:
                        try:
                            # Разбиваем сообщение на части, если оно слишком длинное
                            max_length = 4000  # Максимальная длина сообщения в Telegram
                            for i in range(0, len(message), max_length):
                                chunk = message[i:i + max_length]
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=chunk,
                                    parse_mode=ParseMode.HTML
                                )
                            logger.info(f"Sent recognized text to Telegram chat {chat_id}")
                        except Exception as e:
                            logger.error(f"Error sending text to chat {chat_id}: {e}")
                
                # Отправляем Excel файл
                with open(excel_file, 'rb') as f:
                    for chat_id in available_chats:
                        try:
                            await bot.send_document(
                                chat_id=chat_id,
                                document=f,
                                caption=f"Running strings report {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                                parse_mode=ParseMode.HTML
                            )
                            logger.info(f"Sent Excel file {excel_file} to Telegram chat {chat_id}")
                        except Exception as e:
                            logger.error(f"Error sending Excel to chat {chat_id}: {e}")
                sent_files.append(excel_file)

                # Отправляем скриншоты как документы
                if screenshot_files:
                    logger.info(f"Found {len(screenshot_files)} screenshot files to send")
                    for screenshots in screenshot_files:
                        for screenshot in screenshots:
                            screenshot_path = os.path.join(processed_dir, screenshot)
                            if os.path.exists(screenshot_path):
                                try:
                                    # Отправляем скриншот как документ
                                    with open(screenshot_path, 'rb') as f:
                                        for chat_id in available_chats:
                                            try:
                                                await bot.send_document(
                                                    chat_id=chat_id,
                                                    document=f,
                                                    caption=f"Screenshot: {screenshot}",
                                                    parse_mode=ParseMode.HTML
                                                )
                                                logger.info(f"Sent screenshot {screenshot} to Telegram chat {chat_id}")
                                            except Exception as e:
                                                logger.error(f"Error sending screenshot to chat {chat_id}: {e}")
                                    sent_files.append(screenshot_path)
                                except Exception as e:
                                    logger.error(f"Error sending screenshot {screenshot}: {e}")
                            else:
                                logger.warning(f"Screenshot {screenshot} not found at {screenshot_path}")
                else:
                    logger.info("No screenshots to send")

            except Exception as e:
                logger.error(f"Error processing Excel file: {e}")
        else:
            logger.warning(f"Excel file not found: {excel_file}")
            raise FileNotFoundError(f"Excel file not found: {excel_file}")

        # Удаляем отправленные файлы
        for file_path in sent_files:
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.info(f"Deleted file after sending: {file_path}")
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    logger.info(f"Deleted directory after sending: {file_path}")
            except Exception as e:
                logger.error(f"Error deleting file {file_path}: {e}")

        # Удаляем пустые директории
        try:
            for channel_name in os.listdir(video_dir):
                channel_dir = os.path.join(video_dir, channel_name)
                if os.path.isdir(channel_dir) and not os.listdir(channel_dir):
                    os.rmdir(channel_dir)
                    logger.info(f"Deleted empty directory: {channel_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up empty directories: {e}")

    except Exception as e:
        logger.error(f"Error sending to Telegram: {e}")
        raise

def send_report_files(excel_file, screenshot_files):
    """Send report files (Excel and screenshots) to Telegram."""
    import asyncio
    try:
        asyncio.run(send_to_telegram(excel_file, screenshot_files))
        logger.info("Files sent and deleted successfully")
    except Exception as e:
        logger.error(f"Failed to send files: {e}")
        raise

async def send_video_files():
    """Отправка только видео файлов в Telegram."""
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        sent_files = []  # Список для отслеживания успешно отправленных файлов
        available_chats = []  # Список доступных чатов

        # Проверяем доступность чатов
        for chat_id in CHAT_IDS:
            try:
                await bot.get_chat(chat_id)
                logger.info(f"Chat {chat_id} is available")
                available_chats.append(chat_id)
            except Exception as e:
                logger.error(f"Chat {chat_id} is not available: {e}")
                continue

        if not available_chats:
            logger.error("No available chats found")
            raise Exception("No available chats found")

        # Send video files
        video_files = get_video_files()
        if video_files:
            for video_path in video_files:
                try:
                    with open(video_path, 'rb') as f:
                        for chat_id in available_chats:
                            try:
                                await bot.send_video(
                                    chat_id=chat_id,
                                    video=f,
                                    caption=f"Video: {os.path.basename(video_path)}",
                                    parse_mode=ParseMode.HTML,
                                    supports_streaming=True
                                )
                                logger.info(f"Sent video {video_path} to Telegram chat {chat_id}")
                            except Exception as e:
                                logger.error(f"Error sending video to chat {chat_id}: {e}")
                    sent_files.append(video_path)
                except Exception as e:
                    logger.error(f"Error sending video {video_path}: {e}")
        else:
            logger.info("No videos to send")

        # Удаляем отправленные файлы
        for file_path in sent_files:
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.info(f"Deleted file after sending: {file_path}")
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    logger.info(f"Deleted directory after sending: {file_path}")
            except Exception as e:
                logger.error(f"Error deleting file {file_path}: {e}")

        # Удаляем пустые директории
        try:
            for channel_name in os.listdir(video_dir):
                channel_dir = os.path.join(video_dir, channel_name)
                if os.path.isdir(channel_dir) and not os.listdir(channel_dir):
                    os.rmdir(channel_dir)
                    logger.info(f"Deleted empty directory: {channel_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up empty directories: {e}")

    except Exception as e:
        logger.error(f"Error sending to Telegram: {e}")
        raise

def send_video_files_sync():
    """Send video files to Telegram."""
    import asyncio
    try:
        asyncio.run(send_video_files())
        logger.info("Video files sent and deleted successfully")
    except Exception as e:
        logger.error(f"Failed to send video files: {e}")
        raise

async def send_files_with_caption(file_paths, caption=""):
    """Отправка файлов в Telegram с пользовательским caption."""
    try:
        # Увеличиваем таймаут для отправки больших файлов (5 минут)
        httpx_request = HTTPXRequest(read_timeout=300.0, connect_timeout=300.0)
        bot = Bot(token=TELEGRAM_TOKEN, request=httpx_request)
        sent_files = []  # Список для отслеживания успешно отправленных файлов
        available_chats = []  # Список доступных чатов

        # Проверяем доступность чатов
        for chat_id in CHAT_IDS:
            try:
                await bot.get_chat(chat_id)
                logger.info(f"Chat {chat_id} is available")
                available_chats.append(chat_id)
            except Exception as e:
                logger.error(f"Chat {chat_id} is not available: {e}")
                continue

        if not available_chats:
            logger.error("No available chats found")
            raise Exception("No available chats found")

        # Отправляем файлы
        for file_path in file_paths:
            if not os.path.exists(file_path):
                logger.warning(f"File not found: {file_path}")
                continue
                
            try:
                file_ext = os.path.splitext(file_path)[1].lower()
                
                with open(file_path, 'rb') as f:
                    for chat_id in available_chats:
                        try:
                            if file_ext in ['.mp4', '.avi', '.mkv', '.mov']:
                                # Отправляем как видео
                                await bot.send_video(
                                    chat_id=chat_id,
                                    video=f,
                                    caption=caption,
                                    parse_mode=ParseMode.HTML,
                                    supports_streaming=True
                                )
                            else:
                                # Отправляем как документ
                                await bot.send_document(
                                    chat_id=chat_id,
                                    document=f,
                                    caption=caption,
                                    parse_mode=ParseMode.HTML
                                )
                            logger.info(f"Sent file {file_path} to Telegram chat {chat_id}")
                        except Exception as e:
                            logger.error(f"Error sending file to chat {chat_id}: {e}")
                
                sent_files.append(file_path)
                
            except Exception as e:
                logger.error(f"Error sending file {file_path}: {e}")

        return len(sent_files) > 0

    except Exception as e:
        logger.error(f"Error sending files to Telegram: {e}")
        raise

def send_files(file_paths, caption=""):
    """Send files to Telegram with custom caption."""
    import asyncio
    try:
        success = asyncio.run(send_files_with_caption(file_paths, caption))
        if success:
            logger.info("Files sent successfully")
        else:
            logger.warning("No files were sent")
        return success
    except Exception as e:
        logger.error(f"Failed to send files: {e}")
        raise

if __name__ == "__main__":
    pass