import os
import logging
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from PIL import Image
import io

# Настройка логирования
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/telegram_sender_log.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Telegram bot configuration
TELEGRAM_TOKEN = "7014463362:AAEDPF4MzfgxcZBwClW7nTONtJqk_04uJ4g"
CHAT_ID = "984259692"
processed_dir = "screenshots_processed"

# Максимальные размеры для Telegram
MAX_WIDTH = 1280
MAX_HEIGHT = 1280
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def process_image(image_path):
    """Обработка изображения для соответствия требованиям Telegram."""
    try:
        with Image.open(image_path) as img:
            # Конвертируем в RGB если нужно
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Получаем текущие размеры
            width, height = img.size
            
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

        # Send Excel file
        if os.path.exists(excel_file):
            with open(excel_file, 'rb') as f:
                await bot.send_document(
                    chat_id=CHAT_ID,
                    document=f,
                    caption=f"Running strings report {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Sent Excel file {excel_file} to Telegram")
                sent_files.append(excel_file)
        else:
            logger.warning(f"Excel file not found: {excel_file}")
            raise FileNotFoundError(f"Excel file not found: {excel_file}")

        # Send screenshots
        if screenshot_files:
            for screenshots in screenshot_files:
                for screenshot in screenshots:
                    screenshot_path = os.path.join(processed_dir, screenshot)
                    if os.path.exists(screenshot_path):
                        try:
                            with open(screenshot_path, 'rb') as f:
                                await bot.send_document(
                                    chat_id=CHAT_ID,
                                    document=f,
                                    caption=f"Screenshot: {screenshot}",
                                    parse_mode=ParseMode.HTML
                                )
                                logger.info(f"Sent screenshot {screenshot} to Telegram")
                                sent_files.append(screenshot_path)
                        except Exception as e:
                            logger.error(f"Error sending screenshot {screenshot}: {e}")
                    else:
                        logger.warning(f"Screenshot {screenshot} not found at {screenshot_path}")
        else:
            logger.info("No screenshots to send")

        # Удаляем отправленные файлы
        for file_path in sent_files:
            try:
                os.remove(file_path)
                logger.info(f"Deleted file after sending: {file_path}")
            except Exception as e:
                logger.error(f"Error deleting file {file_path}: {e}")

    except Exception as e:
        logger.error(f"Error sending to Telegram: {e}")
        raise


def send_files(excel_file, screenshot_files):
    """Send files to Telegram."""
    import asyncio
    try:
        # Создаем новый event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем отправку
        loop.run_until_complete(send_to_telegram(excel_file, screenshot_files))
        logger.info("Files sent and deleted successfully")
    except Exception as e:
        logger.error(f"Failed to send files: {e}")
        raise
    finally:
        loop.close()


if __name__ == "__main__":
    pass