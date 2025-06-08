import os
import telegram
from telegram.ext import Updater
import logging
from datetime import datetime

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
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"  # Replace with your bot token
CHAT_ID = "YOUR_CHAT_ID"  # Replace with your chat ID
processed_dir = "screenshots_processed"


async def send_to_telegram(csv_file, screenshot_files):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)

        # Send CSV file
        with open(csv_file, 'rb') as f:
            await bot.send_document(
                chat_id=CHAT_ID,
                document=f,
                caption=f"Running strings report {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            logger.info(f"Sent CSV file {csv_file} to Telegram")

        # Send screenshots
        for screenshots in screenshot_files:
            for screenshot in screenshots:
                screenshot_path = os.path.join(processed_dir, screenshot)
                if os.path.exists(screenshot_path):
                    with open(screenshot_path, 'rb') as f:
                        await bot.send_photo(
                            chat_id=CHAT_ID,
                            photo=f,
                            caption=f"Screenshot: {screenshot}"
                        )
                        logger.info(f"Sent screenshot {screenshot} to Telegram")
                else:
                    logger.warning(f"Screenshot {screenshot} not found at {screenshot_path}")

    except Exception as e:
        logger.error(f"Error sending to Telegram: {e}")


def send_files(csv_file, screenshot_files):
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(send_to_telegram(csv_file, screenshot_files))
    finally:
        loop.close()


if __name__ == "__main__":
    # Example usage
    csv_file = "logs/recognized_text_others_2025-06-04_16-01-00.csv"
    screenshot_files = [["channel_2025-06-04_16-01-00.jpg"]]
    send_files(csv_file, screenshot_files)