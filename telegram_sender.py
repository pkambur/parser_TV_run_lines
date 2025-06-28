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
from pathlib import Path
import cv2
import tempfile

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
processed_dir = Path("screenshots_processed")

# Максимальные размеры для Telegram
MAX_WIDTH = 1280
MAX_HEIGHT = 1280
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB (уменьшено с 2GB для надежности)

def compress_video(input_path, output_path=None, target_size_mb=45):
    """
    Сжимает видео для соответствия лимитам Telegram.
    Возвращает путь к сжатому файлу или None в случае ошибки.
    """
    try:
        if output_path is None:
            # Создаем временный файл
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"compressed_{os.path.basename(input_path)}")
        
        # Открываем исходное видео
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видео для сжатия: {input_path}")
            return None
        
        # Получаем параметры исходного видео
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Вычисляем новые размеры (максимум 1280x720 для Telegram)
        max_width, max_height = 1280, 720
        if width > max_width or height > max_height:
            ratio = min(max_width / width, max_height / height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
        else:
            new_width, new_height = width, height
        
        # Создаем VideoWriter с высоким сжатием
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (new_width, new_height))
        
        if not out.isOpened():
            logger.error(f"Не удалось создать VideoWriter для сжатия: {output_path}")
            cap.release()
            return None
        
        logger.info(f"Начало сжатия видео: {input_path} -> {output_path}")
        logger.info(f"Исходные размеры: {width}x{height}, новые: {new_width}x{new_height}")
        
        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Изменяем размер кадра
            if new_width != width or new_height != height:
                frame = cv2.resize(frame, (new_width, new_height))
            
            # Записываем кадр
            out.write(frame)
            frame_count += 1
            
            # Показываем прогресс каждые 100 кадров
            if frame_count % 100 == 0:
                progress = (frame_count / total_frames) * 100
                logger.info(f"Прогресс сжатия: {progress:.1f}% ({frame_count}/{total_frames})")
        
        # Освобождаем ресурсы
        cap.release()
        out.release()
        
        # Проверяем размер сжатого файла
        compressed_size = os.path.getsize(output_path)
        compressed_size_mb = compressed_size / (1024 * 1024)
        
        logger.info(f"Сжатие завершено: {compressed_size_mb:.2f} MB")
        
        if compressed_size_mb > target_size_mb:
            logger.warning(f"Сжатый файл все еще слишком большой: {compressed_size_mb:.2f} MB > {target_size_mb} MB")
            # Можно добавить дополнительное сжатие или уменьшение качества
            return None
        
        return output_path
        
    except Exception as e:
        logger.error(f"Ошибка при сжатии видео {input_path}: {e}")
        return None

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
        # Проверка существования директории processed_dir
        if not processed_dir.exists():
            logger.warning(f"Директория processed_dir не найдена: {processed_dir}")
            # Создаем директорию если она не существует
            try:
                processed_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Создана директория processed_dir: {processed_dir}")
            except Exception as e:
                logger.error(f"Ошибка при создании директории processed_dir: {e}")
        
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
        recognized_texts = {}
        recognized_channels = {}
        recognized_times = {}
        if os.path.exists(excel_file):
            try:
                # Читаем Excel файл
                df = pd.read_excel(excel_file)
                # Сопоставляем имя файла с текстом, каналом и временем
                for _, row in df.iterrows():
                    if 'Source' in row and 'Text' in row:
                        fname = os.path.basename(str(row['Source']))
                        recognized_texts[fname] = str(row['Text'])
                        recognized_channels[fname] = str(row['Channel']) if 'Channel' in row else ''
                        recognized_times[fname] = str(row['Timestamp']) if 'Timestamp' in row else ''
                
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
                            # Определяем путь и текст
                            if isinstance(screenshot, dict):
                                screenshot_path = screenshot.get('path')
                                caption = screenshot.get('text', '')
                            else:
                                screenshot_path = os.path.join(processed_dir, screenshot)
                                fname = os.path.basename(screenshot_path)
                                text = recognized_texts.get(fname, '')
                                channel = recognized_channels.get(fname, '')
                                timestamp = recognized_times.get(fname, '')
                                # Формируем подпись
                                caption = f"{channel}\n{timestamp}\n{text}".strip()
                            if os.path.exists(screenshot_path):
                                try:
                                    # Отправляем скриншот как документ
                                    with open(screenshot_path, 'rb') as f:
                                        for chat_id in available_chats:
                                            try:
                                                await bot.send_document(
                                                    chat_id=chat_id,
                                                    document=f,
                                                    caption=caption if caption else None,
                                                    parse_mode=ParseMode.HTML
                                                )
                                                logger.info(f"Sent screenshot {screenshot_path} to Telegram chat {chat_id}")
                                            except Exception as e:
                                                logger.error(f"Error sending screenshot to chat {chat_id}: {e}")
                                    sent_files.append(screenshot_path)
                                except Exception as e:
                                    logger.error(f"Error sending screenshot {screenshot_path}: {e}")
                            else:
                                logger.warning(f"Screenshot {screenshot_path} not found")
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

async def send_files_with_caption(file_paths, caption=""):
    """Отправка файлов в Telegram с пользовательским caption."""
    try:
        # Увеличиваем таймаут для отправки больших файлов (5 минут)
        httpx_request = HTTPXRequest(read_timeout=300.0, connect_timeout=300.0)
        bot = Bot(token=TELEGRAM_TOKEN, request=httpx_request)
        sent_files = []  # Список для отслеживания успешно отправленных файлов
        available_chats = []  # Список доступных чатов
        temp_files = []  # Список временных файлов для удаления

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
            file_path = Path(file_path)
            if not file_path.exists():
                logger.warning(f"File not found: {file_path}")
                continue
            
            try:
                file_ext = file_path.suffix.lower()
                file_size = file_path.stat().st_size
                file_size_mb = file_size / (1024 * 1024)
                
                # Обработка видео файлов
                if file_ext in ['.mp4', '.avi', '.mkv', '.mov']:
                    logger.info(f"Обработка видео файла: {file_path} ({file_size_mb:.2f} MB)")
                    
                    # Проверяем размер файла
                    if file_size > MAX_VIDEO_SIZE:
                        logger.info(f"Видео {file_path} превышает лимит Telegram (50 МБ), начинаем сжатие...")
                        
                        # Сжимаем видео
                        compressed_path = compress_video(str(file_path), target_size_mb=45)
                        if compressed_path is None:
                            logger.error(f"Не удалось сжать видео {file_path}")
                            continue
                        
                        # Используем сжатый файл
                        actual_file_path = compressed_path
                        temp_files.append(compressed_path)
                        compressed_size = os.path.getsize(compressed_path)
                        compressed_size_mb = compressed_size / (1024 * 1024)
                        logger.info(f"Видео сжато: {compressed_size_mb:.2f} MB")
                    else:
                        actual_file_path = str(file_path)
                        logger.info(f"Видео {file_path} подходит по размеру ({file_size_mb:.2f} MB)")
                    
                    # Отправляем видео
                    with open(actual_file_path, 'rb') as f:
                        for chat_id in available_chats:
                            try:
                                await bot.send_video(
                                    chat_id=chat_id,
                                    video=f,
                                    caption=caption,
                                    parse_mode=ParseMode.HTML,
                                    supports_streaming=True
                                )
                                logger.info(f"Видео {file_path} успешно отправлено в Telegram chat {chat_id}")
                                sent_files.append(str(file_path))
                                break  # Отправляем только в первый доступный чат
                            except Exception as e:
                                logger.error(f"Ошибка отправки видео в chat {chat_id}: {e}")
                                if "Request Entity Too Large" in str(e):
                                    logger.error(f"Файл все еще слишком большой для Telegram: {actual_file_path}")
                                    break
                                continue
                
                else:
                    # Обработка других файлов (изображения, документы)
                    if file_size > MAX_FILE_SIZE:
                        logger.warning(f"Файл {file_path} превышает лимит Telegram для документов (10 МБ) и не будет отправлен.")
                        continue
                    
                    with file_path.open('rb') as f:
                        for chat_id in available_chats:
                            try:
                                await bot.send_document(
                                    chat_id=chat_id,
                                    document=f,
                                    caption=caption,
                                    parse_mode=ParseMode.HTML
                                )
                                logger.info(f"Файл {file_path} успешно отправлен в Telegram chat {chat_id}")
                                sent_files.append(str(file_path))
                                break  # Отправляем только в первый доступный чат
                            except Exception as e:
                                logger.error(f"Ошибка отправки файла в chat {chat_id}: {e}")
                                continue
                
            except Exception as e:
                logger.error(f"Ошибка обработки файла {file_path}: {e}")
                continue
        
        # Удаляем временные файлы
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.info(f"Удален временный файл: {temp_file}")
            except Exception as e:
                logger.error(f"Ошибка удаления временного файла {temp_file}: {e}")

        return len(sent_files) > 0

    except Exception as e:
        logger.error(f"Ошибка отправки файлов в Telegram: {e}")
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