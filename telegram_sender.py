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
import json

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

def load_config():
    """Загружает конфигурацию из файла config.json или переменных окружения."""
    config = {
        'telegram_token': None,
        'chat_ids': [],
        'hf_api_token': None,
        'hf_token': None,
        'processed_dir': 'screenshots_processed',
        'max_width': 1280,
        'max_height': 1280,
        'max_file_size': 10 * 1024 * 1024,  # 10MB
        'max_video_size': 50 * 1024 * 1024,  # 50MB
        'telegram_timeout': 600.0,  # 10 минут
        'telegram_connect_timeout': 60.0,  # 1 минута
    }
    
    # Получаем путь к директории исполняемого файла
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    config_file = os.path.join(base_path, 'config.json')
    
    # Пытаемся загрузить конфигурацию из файла
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                config.update(file_config)
                logger.info(f"Конфигурация загружена из файла: {config_file}")
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации из файла: {e}")
    
    # Переменные окружения имеют приоритет над файлом конфигурации
    if os.getenv('TELEGRAM_TOKEN'):
        config['telegram_token'] = os.getenv('TELEGRAM_TOKEN')
        logger.info("Telegram токен загружен из переменной окружения TELEGRAM_TOKEN")
    
    if os.getenv('TELEGRAM_CHAT_IDS'):
        try:
            chat_ids_str = os.getenv('TELEGRAM_CHAT_IDS')
            config['chat_ids'] = [int(chat_id.strip()) for chat_id in chat_ids_str.split(',')]
            logger.info(f"Chat IDs загружены из переменной окружения: {config['chat_ids']}")
        except Exception as e:
            logger.error(f"Ошибка парсинга TELEGRAM_CHAT_IDS: {e}")
    
    if os.getenv('HF_API_TOKEN'):
        config['hf_api_token'] = os.getenv('HF_API_TOKEN')
        logger.info("Hugging Face API токен загружен из переменной окружения HF_API_TOKEN")
    
    if os.getenv('HF_TOKEN'):
        config['hf_token'] = os.getenv('HF_TOKEN')
        logger.info("Hugging Face токен загружен из переменной окружения HF_TOKEN")
    
    # Проверяем обязательные параметры
    if not config['telegram_token']:
        logger.error("Telegram токен не найден! Установите переменную окружения TELEGRAM_TOKEN или добавьте 'telegram_token' в config.json")
        raise ValueError("Telegram токен не найден")
    
    if not config['chat_ids']:
        logger.error("Chat IDs не найдены! Установите переменную окружения TELEGRAM_CHAT_IDS или добавьте 'chat_ids' в config.json")
        raise ValueError("Chat IDs не найдены")
    
    return config

# Загружаем конфигурацию
try:
    config = load_config()
    TELEGRAM_TOKEN = config['telegram_token']
    CHAT_IDS = config['chat_ids']
    HF_API_TOKEN = config['hf_api_token']
    HF_TOKEN = config['hf_token']
    processed_dir = Path(config['processed_dir'])
    
    # Максимальные размеры для Telegram
    MAX_WIDTH = config['max_width']
    MAX_HEIGHT = config['max_height']
    MAX_FILE_SIZE = config['max_file_size']
    MAX_VIDEO_SIZE = config['max_video_size']
    
    # Увеличенные таймауты для отправки больших файлов
    TELEGRAM_TIMEOUT = config['telegram_timeout']
    TELEGRAM_CONNECT_TIMEOUT = config['telegram_connect_timeout']
    
    logger.info("Конфигурация успешно загружена")
    
except Exception as e:
    logger.error(f"Ошибка загрузки конфигурации: {e}")
    # Fallback значения для совместимости
    TELEGRAM_TOKEN = None
    CHAT_IDS = []
    HF_API_TOKEN = None
    HF_TOKEN = None
    processed_dir = Path("screenshots_processed")
    MAX_WIDTH = 1280
    MAX_HEIGHT = 1280
    MAX_FILE_SIZE = 10 * 1024 * 1024
    MAX_VIDEO_SIZE = 50 * 1024 * 1024
    TELEGRAM_TIMEOUT = 600.0
    TELEGRAM_CONNECT_TIMEOUT = 60.0

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
        
        # Более агрессивное сжатие для crop-видео
        # Для crop-видео (бегущие строки) можно использовать меньшие размеры
        max_width, max_height = 800, 450  # Уменьшаем максимальные размеры еще больше
        
        # Вычисляем новые размеры с более агрессивным сжатием
        if width > max_width or height > max_height:
            ratio = min(max_width / width, max_height / height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
        else:
            # Если размеры уже небольшие, уменьшаем их еще больше
            new_width = int(width * 0.7)
            new_height = int(height * 0.7)
        
        # Убеждаемся, что размеры четные (требование для некоторых кодеков)
        new_width = new_width if new_width % 2 == 0 else new_width - 1
        new_height = new_height if new_height % 2 == 0 else new_height - 1
        
        # Убеждаемся, что размеры не меньше минимальных
        new_width = max(new_width, 320)
        new_height = max(new_height, 180)
        
        # Уменьшаем FPS для экономии места
        new_fps = min(fps, 15)  # Максимум 15 FPS
        
        # Используем более эффективный кодек H.264
        fourcc = cv2.VideoWriter_fourcc(*'H264')
        out = cv2.VideoWriter(output_path, fourcc, new_fps, (new_width, new_height))
        
        if not out.isOpened():
            # Если H.264 не поддерживается, используем MP4V
            logger.warning("H.264 не поддерживается, используем MP4V")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, new_fps, (new_width, new_height))
            
            if not out.isOpened():
                logger.error(f"Не удалось создать VideoWriter для сжатия: {output_path}")
                cap.release()
                return None
        
        logger.info(f"Начало сжатия видео: {input_path} -> {output_path}")
        logger.info(f"Исходные размеры: {width}x{height}, новые: {new_width}x{new_height}")
        logger.info(f"Исходный FPS: {fps}, новый: {new_fps}")
        
        frame_count = 0
        frame_skip = max(1, int(fps / new_fps))  # Пропускаем кадры для снижения FPS
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Пропускаем кадры для снижения FPS
            if frame_count % frame_skip == 0:
                # Изменяем размер кадра
                if new_width != width or new_height != height:
                    frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
                
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
        
        # Если файл все еще слишком большой, пробуем дополнительное сжатие
        if compressed_size_mb > target_size_mb:
            logger.warning(f"Сжатый файл все еще слишком большой: {compressed_size_mb:.2f} MB > {target_size_mb} MB")
            
            # Пробуем еще более агрессивное сжатие
            return _compress_video_aggressive(input_path, output_path, target_size_mb)
        
        return output_path
        
    except Exception as e:
        logger.error(f"Ошибка при сжатии видео {input_path}: {e}")
        return None

def _compress_video_aggressive(input_path, output_path, target_size_mb=45):
    """
    Дополнительное агрессивное сжатие видео.
    """
    try:
        # Создаем новый временный файл
        temp_dir = tempfile.gettempdir()
        aggressive_output = os.path.join(temp_dir, f"aggressive_{os.path.basename(input_path)}")
        
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            return None
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Очень агрессивное уменьшение размера
        new_width = 480  # Уменьшаем еще больше
        new_height = int(height * (480 / width))
        
        # Убеждаемся, что размеры четные
        new_width = new_width if new_width % 2 == 0 else new_width - 1
        new_height = new_height if new_height % 2 == 0 else new_height - 1
        
        # Убеждаемся, что размеры не меньше минимальных
        new_width = max(new_width, 320)
        new_height = max(new_height, 180)
        
        # Уменьшаем FPS для экономии места
        new_fps = min(fps, 10)  # Максимум 10 FPS
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(aggressive_output, fourcc, new_fps, (new_width, new_height))
        
        if not out.isOpened():
            cap.release()
            return None
        
        logger.info(f"Агрессивное сжатие: {new_width}x{new_height}, {new_fps} FPS")
        
        frame_count = 0
        frame_skip = max(1, int(fps / new_fps))  # Пропускаем кадры для снижения FPS
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Пропускаем кадры для снижения FPS
            if frame_count % frame_skip == 0:
                # Изменяем размер кадра
                frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
                out.write(frame)
            
            frame_count += 1
            
            if frame_count % 100 == 0:
                progress = (frame_count / total_frames) * 100
                logger.info(f"Агрессивное сжатие: {progress:.1f}% ({frame_count}/{total_frames})")
        
        cap.release()
        out.release()
        
        # Проверяем размер
        compressed_size = os.path.getsize(aggressive_output)
        compressed_size_mb = compressed_size / (1024 * 1024)
        
        logger.info(f"Агрессивное сжатие завершено: {compressed_size_mb:.2f} MB")
        
        if compressed_size_mb <= target_size_mb:
            # Заменяем оригинальный файл
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(aggressive_output, output_path)
            return output_path
        else:
            # Удаляем временный файл
            if os.path.exists(aggressive_output):
                os.remove(aggressive_output)
            logger.error(f"Не удалось сжать видео до требуемого размера: {compressed_size_mb:.2f} MB")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при агрессивном сжатии видео: {e}")
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
        # Проверяем конфигурацию
        if not TELEGRAM_TOKEN:
            logger.error("Telegram токен не настроен! Проверьте конфигурацию.")
            raise ValueError("Telegram токен не настроен")
        
        if not CHAT_IDS:
            logger.error("Chat IDs не настроены! Проверьте конфигурацию.")
            raise ValueError("Chat IDs не настроены")
        
        # Проверка существования директории processed_dir
        if not processed_dir.exists():
            logger.warning(f"Директория processed_dir не найдена: {processed_dir}")
            # Создаем директорию если она не существует
            try:
                processed_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Создана директория processed_dir: {processed_dir}")
            except Exception as e:
                logger.error(f"Ошибка при создании директории processed_dir: {e}")
        
        # Используем увеличенные таймауты
        httpx_request = HTTPXRequest(read_timeout=TELEGRAM_TIMEOUT, connect_timeout=TELEGRAM_CONNECT_TIMEOUT)
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
                    
                    # Отправляем текст с повторными попытками
                    max_retries = 3
                    for i in range(0, len(message), 4000):
                        chunk = message[i:i + 4000]
                        text_sent = False
                        
                        for attempt in range(max_retries):
                            try:
                                for chat_id in available_chats:
                                    try:
                                        await bot.send_message(
                                            chat_id=chat_id,
                                            text=chunk,
                                            parse_mode=ParseMode.HTML
                                        )
                                        logger.info(f"Sent recognized text to Telegram chat {chat_id} (попытка {attempt + 1})")
                                        text_sent = True
                                        break
                                    except Exception as e:
                                        logger.error(f"Error sending text to chat {chat_id} (попытка {attempt + 1}): {e}")
                                        continue
                                
                                if text_sent:
                                    break
                                    
                            except Exception as e:
                                error_msg = str(e)
                                logger.error(f"Ошибка при попытке {attempt + 1} отправки текста: {error_msg}")
                                if "Timed out" in error_msg and attempt < max_retries - 1:
                                    logger.info(f"Таймаут при отправке текста, повторная попытка {attempt + 2}/{max_retries}")
                                    import asyncio
                                    await asyncio.sleep(2)
                                    continue
                                elif attempt == max_retries - 1:
                                    logger.error(f"Все попытки отправки текста исчерпаны")
                
                # Отправляем Excel файл с повторными попытками
                excel_sent = False
                max_retries = 3
                
                for attempt in range(max_retries):
                    try:
                        with open(excel_file, 'rb') as f:
                            for chat_id in available_chats:
                                try:
                                    await bot.send_document(
                                        chat_id=chat_id,
                                        document=f,
                                        caption=f"Running strings report {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                                        parse_mode=ParseMode.HTML
                                    )
                                    logger.info(f"Sent Excel file {excel_file} to Telegram chat {chat_id} (попытка {attempt + 1})")
                                    sent_files.append(excel_file)
                                    excel_sent = True
                                    break
                                except Exception as e:
                                    logger.error(f"Error sending Excel to chat {chat_id} (попытка {attempt + 1}): {e}")
                                    continue
                        
                        if excel_sent:
                            break
                            
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"Ошибка при попытке {attempt + 1} отправки Excel файла: {error_msg}")
                        if "Timed out" in error_msg and attempt < max_retries - 1:
                            logger.info(f"Таймаут при отправке Excel, повторная попытка {attempt + 2}/{max_retries}")
                            import asyncio
                            await asyncio.sleep(2)
                            continue
                        elif attempt == max_retries - 1:
                            logger.error(f"Все попытки отправки Excel файла исчерпаны")

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
                                    # Отправляем скриншот как документ с повторными попытками
                                    screenshot_sent = False
                                    max_retries = 3
                                    
                                    for attempt in range(max_retries):
                                        try:
                                            with open(screenshot_path, 'rb') as f:
                                                for chat_id in available_chats:
                                                    try:
                                                        await bot.send_document(
                                                            chat_id=chat_id,
                                                            document=f,
                                                            caption=caption if caption else None,
                                                            parse_mode=ParseMode.HTML
                                                        )
                                                        logger.info(f"Sent screenshot {screenshot_path} to Telegram chat {chat_id} (попытка {attempt + 1})")
                                                        sent_files.append(screenshot_path)
                                                        screenshot_sent = True
                                                        break
                                                    except Exception as e:
                                                        logger.error(f"Error sending screenshot to chat {chat_id} (попытка {attempt + 1}): {e}")
                                                        continue
                                            
                                            if screenshot_sent:
                                                break
                                                
                                        except Exception as e:
                                            error_msg = str(e)
                                            logger.error(f"Ошибка при попытке {attempt + 1} отправки скриншота {screenshot_path}: {error_msg}")
                                            if "Timed out" in error_msg and attempt < max_retries - 1:
                                                logger.info(f"Таймаут при отправке скриншота, повторная попытка {attempt + 2}/{max_retries}")
                                                import asyncio
                                                await asyncio.sleep(2)
                                                continue
                                            elif attempt == max_retries - 1:
                                                logger.error(f"Все попытки отправки скриншота {screenshot_path} исчерпаны")
                                    
                                    if not screenshot_sent:
                                        logger.warning(f"Не удалось отправить скриншот {screenshot_path} после {max_retries} попыток")
                                        
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
        # Проверяем существование Excel файла
        if not os.path.exists(excel_file):
            logger.error(f"Excel файл не найден: {excel_file}")
            return False
        
        # Проверяем размер Excel файла
        excel_size = os.path.getsize(excel_file)
        excel_size_mb = excel_size / (1024 * 1024)
        if excel_size_mb > 10:  # Telegram лимит для документов
            logger.warning(f"Excel файл слишком большой ({excel_size_mb:.2f} MB)")
        
        # Проверяем скриншоты
        valid_screenshots = []
        if screenshot_files:
            for screenshots in screenshot_files:
                for screenshot in screenshots:
                    if isinstance(screenshot, dict):
                        screenshot_path = screenshot.get('path')
                    else:
                        screenshot_path = os.path.join(processed_dir, screenshot)
                    
                    if os.path.exists(screenshot_path):
                        screenshot_size = os.path.getsize(screenshot_path)
                        screenshot_size_mb = screenshot_size / (1024 * 1024)
                        if screenshot_size_mb <= 10:  # Telegram лимит для документов
                            valid_screenshots.append(screenshots)
                            break
                        else:
                            logger.warning(f"Скриншот слишком большой ({screenshot_size_mb:.2f} MB): {screenshot_path}")
                    else:
                        logger.warning(f"Скриншот не найден: {screenshot_path}")
        
        logger.info(f"Подготовлено для отправки: Excel файл + {len(valid_screenshots)} групп скриншотов")
        
        asyncio.run(send_to_telegram(excel_file, valid_screenshots))
        logger.info("Files sent and deleted successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to send files: {e}")
        return False

async def send_files_with_caption(file_paths, caption=""):
    """Отправка файлов в Telegram с пользовательским caption."""
    try:
        # Проверяем конфигурацию
        if not TELEGRAM_TOKEN:
            logger.error("Telegram токен не настроен! Проверьте конфигурацию.")
            raise ValueError("Telegram токен не настроен")
        
        if not CHAT_IDS:
            logger.error("Chat IDs не настроены! Проверьте конфигурацию.")
            raise ValueError("Chat IDs не настроены")
        
        # Увеличиваем таймаут для отправки больших файлов
        httpx_request = HTTPXRequest(read_timeout=TELEGRAM_TIMEOUT, connect_timeout=TELEGRAM_CONNECT_TIMEOUT)
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
                            logger.error(f"Не удалось сжать видео {file_path} до требуемого размера")
                            # Продолжаем с следующим файлом
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
                    
                    # Отправляем видео с повторными попытками
                    video_sent = False
                    max_retries = 3
                    
                    for attempt in range(max_retries):
                        try:
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
                                        logger.info(f"Видео {file_path} успешно отправлено в Telegram chat {chat_id} (попытка {attempt + 1})")
                                        sent_files.append(str(file_path))
                                        video_sent = True
                                        break  # Отправляем только в первый доступный чат
                                    except Exception as e:
                                        error_msg = str(e)
                                        logger.error(f"Ошибка отправки видео в chat {chat_id} (попытка {attempt + 1}): {error_msg}")
                                        if "Request Entity Too Large" in error_msg:
                                            logger.error(f"Файл все еще слишком большой для Telegram: {actual_file_path}")
                                            break
                                        continue
                            
                            if video_sent:
                                break  # Выходим из цикла попыток, если отправка успешна
                                
                        except Exception as e:
                            error_msg = str(e)
                            logger.error(f"Ошибка при попытке {attempt + 1} отправки видео {file_path}: {error_msg}")
                            if "Timed out" in error_msg and attempt < max_retries - 1:
                                logger.info(f"Таймаут при отправке, повторная попытка {attempt + 2}/{max_retries}")
                                import asyncio
                                await asyncio.sleep(2)  # Пауза перед повторной попыткой
                                continue
                            elif attempt == max_retries - 1:
                                logger.error(f"Все попытки отправки видео {file_path} исчерпаны")
                    
                    if not video_sent:
                        logger.warning(f"Не удалось отправить видео {file_path} ни в один чат после {max_retries} попыток")
                
                else:
                    # Обработка других файлов (изображения, документы)
                    if file_size > MAX_FILE_SIZE:
                        logger.warning(f"Файл {file_path} превышает лимит Telegram для документов (10 МБ) и не будет отправлен.")
                        continue
                    
                    file_sent = False
                    max_retries = 3
                    
                    for attempt in range(max_retries):
                        try:
                            with file_path.open('rb') as f:
                                for chat_id in available_chats:
                                    try:
                                        await bot.send_document(
                                            chat_id=chat_id,
                                            document=f,
                                            caption=caption,
                                            parse_mode=ParseMode.HTML
                                        )
                                        logger.info(f"Файл {file_path} успешно отправлен в Telegram chat {chat_id} (попытка {attempt + 1})")
                                        sent_files.append(str(file_path))
                                        file_sent = True
                                        break  # Отправляем только в первый доступный чат
                                    except Exception as e:
                                        logger.error(f"Ошибка отправки файла в chat {chat_id} (попытка {attempt + 1}): {e}")
                                        continue
                            
                            if file_sent:
                                break  # Выходим из цикла попыток, если отправка успешна
                                
                        except Exception as e:
                            error_msg = str(e)
                            logger.error(f"Ошибка при попытке {attempt + 1} отправки файла {file_path}: {error_msg}")
                            if "Timed out" in error_msg and attempt < max_retries - 1:
                                logger.info(f"Таймаут при отправке, повторная попытка {attempt + 2}/{max_retries}")
                                import asyncio
                                await asyncio.sleep(2)  # Пауза перед повторной попыткой
                                continue
                            elif attempt == max_retries - 1:
                                logger.error(f"Все попытки отправки файла {file_path} исчерпаны")
                    
                    if not file_sent:
                        logger.warning(f"Не удалось отправить файл {file_path} ни в один чат после {max_retries} попыток")
                
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
        # Проверяем файлы перед отправкой
        valid_files = []
        for file_path in file_paths:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.warning(f"Файл не найден: {file_path}")
                continue
            
            file_size = file_path.stat().st_size
            file_size_mb = file_size / (1024 * 1024)
            
            if file_size_mb > 50:  # Telegram лимит для видео
                logger.warning(f"Файл {file_path} слишком большой ({file_size_mb:.2f} MB), будет сжат")
            
            valid_files.append(str(file_path))
        
        if not valid_files:
            logger.warning("Нет валидных файлов для отправки")
            return False
        
        logger.info(f"Подготовлено {len(valid_files)} файлов для отправки")
        success = asyncio.run(send_files_with_caption(valid_files, caption))
        if success:
            logger.info("Files sent successfully")
        else:
            logger.warning("No files were sent")
        return success
    except Exception as e:
        logger.error(f"Failed to send files: {e}")
        # Возвращаем False вместо вызова raise, чтобы приложение не падало
        return False

if __name__ == "__main__":
    pass