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
import pytesseract

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

def extract_text(image):
    """Извлечение текста из изображения с помощью pytesseract."""
    try:
        # Конвертируем изображение в оттенки серого
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Применяем адаптивную пороговую обработку
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                     cv2.THRESH_BINARY, 11, 2)
        
        # Распознаем текст
        text = pytesseract.image_to_string(thresh, lang='rus')
        return text.strip()
    except Exception as e:
        logger.error(f"Ошибка при извлечении текста: {str(e)}")
        return ""

async def process_text_with_qwen(text, image):
    """Обработка текста с помощью Qwen2-VL-7B-Instruct."""
    try:
        # Конвертируем изображение в base64
        image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        # Формируем промпт для обработки текста
        prompt = (
            f"Проанализируй следующий текст, распознанный с изображения бегущей строки новостей. "
            f"Выполни следующие действия:\n"
            f"1. Исправь искаженные слова и названия (например, 'ияракет' -> 'ракет', 'Нетаньяхурасбс' -> 'Нетаньяху расписался')\n"
            f"2. Раздели слипшиеся слова и добавь пробелы\n"
            f"3. Исправь очевидные ошибки распознавания букв\n"
            f"4. Убери специальные символы (|, ', и т.д.), если они не являются частью текста\n"
            f"5. Сохрани правильную пунктуацию\n"
            f"6. Если видишь сокращения, расшифруй их (например, 'прем' -> 'премьер')\n"
            f"7. Если текст нечитаемый или содержит бессмысленные символы, верни пустую строку\n\n"
            f"Примеры исправлений:\n"
            f"- 'ияракет' -> 'ракет'\n"
            f"- 'Канцелярияпремвера' -> 'Канцелярия премьера'\n"
            f"- 'Нетаньяхурасбс' -> 'Нетаньяху расписался'\n\n"
            f"Текст для обработки: '{text}'"
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

        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {HF_API_TOKEN}",
                "Content-Type": "application/json"
            }
            payload = {
                "inputs": messages,
                "parameters": {
                    "max_new_tokens": 512,
                    "temperature": 0.1,  # Низкая температура для более точных результатов
                    "top_p": 0.9,
                    "repetition_penalty": 1.2  # Штраф за повторения
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
                        processed_text = result[0].get("generated_text", "").strip()
                        # Убираем возможные префиксы и примеры из ответа
                        processed_text = re.sub(r'^(Обработанный текст:|Результат:|Текст:|Ответ:|Примеры исправлений:).*?\n', '', processed_text, flags=re.IGNORECASE | re.DOTALL)
                        processed_text = re.sub(r'\n.*?->.*?\n', '\n', processed_text)  # Убираем строки с примерами
                        processed_text = processed_text.strip()
                        logger.debug(f"Оригинальный текст: '{text}'")
                        logger.debug(f"Обработанный текст: '{processed_text}'")
                        return processed_text
                return text
    except Exception as e:
        logger.error(f"Ошибка при обработке текста с Qwen: {str(e)}")
        return text

async def process_video(video_path, channel_name):
    """Обработка одного видео файла."""
    logger.info(f"Обработка видео: {os.path.basename(video_path)}")
    results = []
    all_text = []  # Список для хранения всего распознанного текста
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видео: {video_path}")
            return results

        # Получаем параметры видео
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Замедляем скорость воспроизведения (берем каждый 4-й кадр)
        frame_interval = 4
        frame_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Пропускаем кадры для замедления
            if frame_count % frame_interval != 0:
                frame_count += 1
                continue

            # Извлекаем текст из кадра
            text = extract_text(frame)
            if text:
                # Обрабатываем текст с помощью Qwen
                processed_text = await process_text_with_qwen(text, frame)
                if processed_text:  # Добавляем только если текст не пустой после обработки
                    all_text.append(processed_text)
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    results.append({
                        'channel': channel_name,
                        'timestamp': timestamp,
                        'text': processed_text
                    })

            frame_count += 1

        cap.release()
        
        # Выводим весь распознанный текст для видео
        if all_text:
            combined_text = "\n".join(all_text)
            logger.info(f"\nВесь распознанный текст из видео {os.path.basename(video_path)}:\n{combined_text}\n")
        
        logger.info(f"Обработано {frame_count} кадров, найдено {len(results)} результатов")
        return results

    except Exception as e:
        logger.error(f"Ошибка при обработке видео {video_path}: {str(e)}")
        return results

def merge_and_correct_text(texts):
    """Объединение и исправление распознанного текста."""
    if not texts:
        return ""
    
    # Объединяем все тексты
    combined_text = " ".join(texts)
    
    # Удаляем дубликаты (если один и тот же текст встречается несколько раз подряд)
    combined_text = re.sub(r'\b(\w+)(?:\s+\1\b)+', r'\1', combined_text)
    
    # Исправляем типичные ошибки распознавания
    corrections = {
        r'(\d+)([а-яА-Я])': r'\1 \2',  # Добавляем пробел между цифрами и буквами
        r'([а-яА-Я])(\d+)': r'\1 \2',  # Добавляем пробел между буквами и цифрами
        r'([.!?])([а-яА-Я])': r'\1 \2',  # Добавляем пробел после знаков препинания
        r'\s+': ' ',  # Заменяем множественные пробелы на один
        r'([а-яА-Я])([A-Za-z])': r'\1 \2',  # Добавляем пробел между русскими и английскими буквами
    }
    
    for pattern, replacement in corrections.items():
        combined_text = re.sub(pattern, replacement, combined_text)
    
    return combined_text.strip()

async def process_videos(base_dir="video"):
    """Обработка всех видеофайлов в подпапках."""
    try:
        if not os.path.exists(base_dir):
            logger.error(f"Папка {base_dir} не найдена")
            return

        channel_results = {}  # Словарь для хранения результатов по каналам
        
        # Обработка каждой подпапки
        for channel_name in os.listdir(base_dir):
            channel_dir = os.path.join(base_dir, channel_name)
            if not os.path.isdir(channel_dir):
                continue

            logger.info(f"Обработка канала: {channel_name}")
            channel_texts = []  # Список для хранения всех текстов канала
            
            # Обработка всех видеофайлов в подпапке
            for filename in os.listdir(channel_dir):
                if filename.lower().endswith(('.mp4', '.avi', '.mkv')):
                    video_path = os.path.join(channel_dir, filename)
                    logger.info(f"Обработка видео: {filename}")
                    results = await process_video(video_path, channel_name)
                    
                    # Собираем тексты из результатов
                    for result in results:
                        if result['text']:
                            channel_texts.append(result['text'])
            
            # Объединяем и исправляем тексты для канала
            if channel_texts:
                merged_text = merge_and_correct_text(channel_texts)
                channel_results[channel_name] = {
                    'text': merged_text,
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                logger.info(f"\nОбработанный текст для канала {channel_name}:\n{merged_text}\n")

        if not channel_results:
            logger.warning("Нет результатов для сохранения")
            return

        # Сохраняем результаты в Excel
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        excel_file = f"logs/video_text_{timestamp}.xlsx"
        
        try:
            # Создаем DataFrame из результатов
            data = []
            for channel, result in channel_results.items():
                data.append({
                    'channel': channel,
                    'timestamp': result['timestamp'],
                    'text': result['text']
                })
            
            df = pd.DataFrame(data)
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