import os
import cv2
import pandas as pd
from datetime import datetime
import logging
import asyncio
import aiohttp
import base64
from PIL import Image
import io
import json
from huggingface_hub import HfApi, InferenceClient
import shutil
from dotenv import load_dotenv
import re

# Load environment variables from .env file
load_dotenv()

# Настройка логирования
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/video_processor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация Hugging Face API
HF_API_TOKEN = os.getenv("HUGGINGFACE_HUB_TOKEN")
if not HF_API_TOKEN:
    logger.warning("HUGGINGFACE_HUB_TOKEN не установлен. Проверка текста будет ограничена.")
    client = None
else:
    try:
        api = HfApi()
        api.whoami(token=HF_API_TOKEN)
        client = InferenceClient(model="Qwen/Qwen2-VL-7B-Instruct", token=HF_API_TOKEN)
        logger.info("Успешное подключение к Hugging Face API")
    except Exception as e:
        logger.error(f"Ошибка при инициализации Hugging Face API: {e}")
        logger.warning("Проверка текста будет ограничена")
        client = None

async def extract_frame(video_path, frame_number):
    """Извлекает кадр из видео."""
    try:
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        cap.release()
        if ret:
            return frame
        return None
    except Exception as e:
        logger.error(f"Ошибка при извлечении кадра из {video_path}: {e}")
        return None

async def is_readable_text(text, image):
    """Проверка читаемости текста с использованием Qwen2.5-VL."""
    if not text:
        logger.debug("is_readable_text: Текст пустой")
        return False, text

    # Если нет токена API или клиент не инициализирован, используем базовую проверку
    if not HF_API_TOKEN or client is None:
        # Базовая проверка текста
        clean_text = re.sub(r'[^а-яА-Яa-zA-Z\s]', '', text)
        words = clean_text.strip().split()
        # Убрана проверка на минимальную длину текста
        logger.debug(f"is_readable_text (базовая проверка): Текст: '{text}', количество слов: {len(words)}")
        return len(words) >= 2, text

    try:
        # Конвертируем изображение в base64
        image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        # Формируем промпт
        prompt = (
            f"Проанализируй следующий текст, распознанный с изображения. "
            f"Определи, является ли он читаемым и осмысленным текстом на русском или английском языке. "
            f"Учитывай, что это бегущая строка новостей. "
            f"Если текст содержит бессмысленные символы, случайные буквы или нечитаемые последовательности, "
            f"укажи, что он нечитаемый. "
            f"Ответь только 'читаемый' или 'нечитаемый' и кратко объясни причину. "
            f"Текст: '{text}'"
        )

        # Формируем данные для API
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_base64}"}
                ]
            }
        ]

        # Отправляем запрос к API
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {HF_API_TOKEN}",
                "Content-Type": "application/json"
            }
            payload = {
                "inputs": messages,
                "parameters": {
                    "max_new_tokens": 512,
                    "temperature": 0.3,
                    "top_p": 0.9
                }
            }
            
            async with session.post(
                "https://api-inference.huggingface.co/models/Qwen/Qwen2-VL-7B-Instruct",
                headers=headers,
                json=payload,
                timeout=30
            ) as response:
                if response.status != 200:
                    logger.error(f"Ошибка API: {response.status}")
                    return False, text
                    
                result = await response.json()
                if isinstance(result, list) and result:
                    response_text = result[0].get("generated_text", "").lower()
                    logger.debug(f"is_readable_text (API): Текст: '{text}', ответ API: '{response_text}'")
                    return "читаемый" in response_text, text

        return False, text
    except Exception as e:
        logger.error(f"Ошибка при проверке текста: {e}")
        return False, text

async def process_video(video_path, channel_name):
    """Обработка видеофайла."""
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видео: {video_path}")
            return []

        # Получаем информацию о видео
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()

        # Извлекаем кадры с интервалом в 1 секунду
        frame_interval = int(fps)
        results = []

        for frame_number in range(0, total_frames, frame_interval):
            frame = await extract_frame(video_path, frame_number)
            if frame is None:
                continue

            # Конвертируем кадр в текст с помощью Qwen2-VL
            try:
                # Конвертируем изображение в base64
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                buffered = io.BytesIO()
                image.save(buffered, format="JPEG")
                image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

                # Формируем промпт для распознавания текста
                prompt = "Распознай текст на изображении. Это бегущая строка новостей. Верни только распознанный текст, без дополнительных комментариев."

                # Формируем данные для API
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_base64}"}
                        ]
                    }
                ]

                async with aiohttp.ClientSession() as session:
                    headers = {
                        "Authorization": f"Bearer {HF_API_TOKEN}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "inputs": messages,
                        "parameters": {
                            "max_new_tokens": 512,
                            "temperature": 0.3,
                            "top_p": 0.9
                        }
                    }
                    
                    async with session.post(
                        "https://api-inference.huggingface.co/models/Qwen/Qwen2-VL-7B-Instruct",
                        headers=headers,
                        json=payload,
                        timeout=30
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            if isinstance(result, list) and result:
                                text = result[0].get("generated_text", "").strip()
                                is_readable, corrected_text = await is_readable_text(text, frame)
                                
                                if is_readable:
                                    timestamp = datetime.fromtimestamp(frame_number / fps)
                                    results.append({
                                        "Channel": channel_name,
                                        "Timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                                        "Text": corrected_text,
                                        "Source": video_path
                                    })

            except Exception as e:
                logger.error(f"Ошибка при обработке кадра {frame_number}: {e}")
                continue

        return results

    except Exception as e:
        logger.error(f"Ошибка при обработке видео {video_path}: {e}")
        return []

async def process_videos(base_dir="video"):
    """Обработка всех видеофайлов в подпапках."""
    try:
        if not os.path.exists(base_dir):
            logger.error(f"Папка {base_dir} не найдена")
            return

        all_results = []
        
        # Обработка каждой подпапки
        for channel_name in os.listdir(base_dir):
            channel_dir = os.path.join(base_dir, channel_name)
            if not os.path.isdir(channel_dir):
                continue

            logger.info(f"Обработка канала: {channel_name}")
            
            # Обработка всех видеофайлов в подпапке
            for filename in os.listdir(channel_dir):
                if filename.lower().endswith(('.mp4', '.avi', '.mkv')):
                    video_path = os.path.join(channel_dir, filename)
                    logger.info(f"Обработка видео: {filename}")
                    results = await process_video(video_path, channel_name)
                    all_results.extend(results)

        if not all_results:
            logger.warning("Нет результатов для сохранения")
            return

        # Сохраняем результаты в Excel
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        excel_file = f"logs/video_text_{timestamp}.xlsx"
        
        try:
            df = pd.DataFrame(all_results)
            df.to_excel(excel_file, index=False, engine='openpyxl')
            logger.info(f"Результаты сохранены в Excel: {excel_file}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении в Excel: {e}")

    except Exception as e:
        logger.error(f"Ошибка при обработке видеофайлов: {e}")

def main():
    """Основная функция."""
    try:
        asyncio.run(process_videos())
    except Exception as e:
        logger.error(f"Ошибка в main: {e}")

if __name__ == "__main__":
    main() 