import os
import pandas as pd
from datetime import datetime
import logging
import cv2
import pytesseract
import asyncio
import re
import aiohttp
import base64
from PIL import Image
import io
import json
from huggingface_hub import HfApi, InferenceClient
import hashlib
from collections import defaultdict
import shutil
import sys
import easyocr
from difflib import SequenceMatcher
import schedule
import time
from utils import setup_logging

logger = setup_logging('lines_to_csv_log.txt')

# Загрузка ключевых слов
def load_keywords():
    try:
        with open('keywords.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(word.lower() for word in data['keywords'])
    except Exception as e:
        logger.error(f"Ошибка при загрузке ключевых слов: {e}")
        return set()

# Инициализация ключевых слов
KEYWORDS = load_keywords()

# Создание директории для обработанных файлов
def ensure_processed_dir():
    processed_dir = "screenshots_processed"
    if not os.path.exists(processed_dir):
        os.makedirs(processed_dir)
    return processed_dir

# Инициализация Hugging Face API
HF_API_TOKEN = os.getenv("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")
if not HF_API_TOKEN:
    logger.warning("HUGGINGFACE_HUB_TOKEN не установлен. Проверка текста будет ограничена.")
    client = None
else:
    try:
        # Проверяем валидность токена
        api = HfApi()
        api.whoami(token=HF_API_TOKEN)
        client = InferenceClient(model="Qwen/Qwen2-VL-7B-Instruct", token=HF_API_TOKEN)
        logger.info("Успешное подключение к Hugging Face API")
    except Exception as e:
        logger.error(f"Ошибка при инициализации Hugging Face API: {e}")
        logger.warning("Проверка текста будет ограничена")
        client = None

async def preprocess_image(image_path):
    """Предобработка изображения для улучшения распознавания текста."""
    try:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        return img
    except Exception as e:
        logger.error(f"Ошибка при предобработке изображения {image_path}: {e}")
        return None

async def recognize_text(image_path):
    """Распознавание текста на изображении с помощью Tesseract."""
    try:
        img = await preprocess_image(image_path)
        if img is None:
            return ""
        text = pytesseract.image_to_string(img, lang='rus+eng')
        return text.strip()
    except Exception as e:
        logger.error(f"Ошибка при распознавании текста в {image_path}: {e}")
        return ""

async def is_similar_text(text1, text2, threshold=0.9):
    """Проверка схожести двух текстов."""
    return SequenceMatcher(None, text1, text2).ratio() > threshold

async def combine_texts(texts):
    """Объединение текстов, удаляя дубликаты."""
    unique_texts = []
    for text in texts:
        if text and not any(await is_similar_text(text, existing) for existing in unique_texts):
            unique_texts.append(text)
    return unique_texts

async def is_readable_text(text, image_path):
    """Проверка читаемости текста с использованием Qwen2.5-VL через Hugging Face Inference API."""
    if not text:
        logger.debug("Текст пустой")
        return False, text

    # Удаляем специальные символы и цифры для проверки
    clean_text = re.sub(r'[^а-яА-Яa-zA-Z\s]', '', text)
    
    # Проверяем минимальную длину текста
    if len(clean_text.strip()) < 5:
        logger.debug(f"Текст слишком короткий: {clean_text}")
        return False, text

    # Проверяем наличие слов (более одного слова)
    words = clean_text.strip().split()
    if len(words) < 2:
        logger.debug(f"Текст содержит слишком мало слов: {words}")
        return False, text

    # Если нет токена API или клиент не инициализирован, используем базовую проверку
    if not HF_API_TOKEN or client is None:
        logger.debug("Используется базовая проверка текста (без API)")
        return len(words) >= 2 and len(clean_text.strip()) >= 5, text

    # Используем Qwen2.5-VL через Inference API
    try:
        # Формируем промпт для проверки читаемости текста
        prompt = (
            f"Проанализируй следующий текст, распознанный с изображения. "
            f"Определи, является ли он читаемым и осмысленным текстом на русском или английском языке. "
            f"Учитывай, что это бегущая строка новостей. "
            f"Если текст содержит бессмысленные символы, случайные буквы или нечитаемые последовательности, "
            f"укажи, что он нечитаемый. "
            f"Ответь только 'читаемый' или 'нечитаемый' и кратко объясни причину. "
            f"Текст: '{text}'"
        )

        # Конвертируем изображение в base64
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG")
            image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

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

        # Отправляем асинхронный запрос к API
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {HF_API_TOKEN}",
                "Content-Type": "application/json"
            }
            payload = {
                "inputs": messages,
                "parameters": {
                    "max_new_tokens": 512,
                    "temperature": 0.3,  # Уменьшаем температуру для более консистентных ответов
                    "top_p": 0.9
                }
            }
            
            try:
                async with session.post(
                    "https://api-inference.huggingface.co/models/Qwen/Qwen2-VL-7B-Instruct",
                    headers=headers,
                    json=payload,
                    timeout=30
                ) as response:
                    if response.status == 401:
                        logger.error("Ошибка авторизации в Hugging Face API. Проверьте токен.")
                        return len(words) >= 2 and len(clean_text.strip()) >= 5, text
                    elif response.status != 200:
                        logger.error(f"Ошибка API: {response.status} - {await response.text()}")
                        return len(words) >= 2 and len(clean_text.strip()) >= 5, text
                        
                    result = await response.json()
                    if isinstance(result, list) and result:
                        response_text = result[0].get("generated_text", "").lower()
                        logger.debug(f"Ответ Qwen2.5-VL: {response_text}")
                        
                        # Проверяем ответ модели
                        if "нечитаемый" in response_text:
                            logger.debug(f"Qwen2.5-VL определил текст как нечитаемый: {text}")
                            return False, text
                        elif "читаемый" in response_text:
                            # Если текст читаемый, пробуем его исправить
                            correction_prompt = (
                                f"Исправь следующий текст, сохраняя его смысл. "
                                f"Исправь опечатки и форматирование, но сохрани все числа и специальные символы. "
                                f"Текст: '{text}'"
                            )
                            
                            correction_messages = [
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": correction_prompt},
                                        {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_base64}"}
                                    ]
                                }
                            ]
                            
                            payload["inputs"] = correction_messages
                            
                            async with session.post(
                                "https://api-inference.huggingface.co/models/Qwen/Qwen2-VL-7B-Instruct",
                                headers=headers,
                                json=payload,
                                timeout=30
                            ) as correction_response:
                                if correction_response.status == 200:
                                    correction_result = await correction_response.json()
                                    if isinstance(correction_result, list) and correction_result:
                                        corrected_text = correction_result[0].get("generated_text", text)
                                        return True, corrected_text.strip()
                            
                            return True, text
                        else:
                            logger.warning(f"Неожиданный ответ от Qwen2.5-VL: {response_text}")
                            return len(words) >= 2 and len(clean_text.strip()) >= 5, text
                    else:
                        logger.error(f"Некорректный ответ API: {result}")
                        return len(words) >= 2 and len(clean_text.strip()) >= 5, text
                    
            except asyncio.TimeoutError:
                logger.error("Таймаут при обращении к API")
                return len(words) >= 2 and len(clean_text.strip()) >= 5, text
            except Exception as e:
                logger.error(f"Ошибка при обращении к API: {e}")
                return len(words) >= 2 and len(clean_text.strip()) >= 5, text
                
    except Exception as e:
        logger.error(f"Ошибка при проверке текста в Qwen2.5-VL API: {e}")
        logger.info("Используется упрощенная проверка текста")
        return len(words) >= 2 and len(clean_text.strip()) >= 5, text

def load_daily_texts():
    """Загружает все тексты, распознанные за текущий день из daily_lines_YYYY-MM-DD.xlsx."""
    file_path = get_daily_file_path()
    if os.path.exists(file_path):
        try:
            df = pd.read_excel(file_path)
            return set(str(t).strip() for t in df['Text'].dropna())
        except Exception as e:
            logger.error(f"Ошибка при загрузке ежедневного файла: {e}")
            return set()
    return set()

class TextDuplicateChecker:
    def __init__(self, similarity_threshold=0.8):
        self.similarity_threshold = similarity_threshold
        self.texts_by_channel = defaultdict(set)  # Хранит тексты по каналам (текущая сессия)
        self.text_hashes = set()  # Хранит хеши всех текстов (текущая сессия)
        self.daily_texts = load_daily_texts()  # Тексты за день

    async def is_duplicate(self, text, channel_name):
        """Проверяет, является ли текст дубликатом (по базе за день и текущей сессии)."""
        # Проверка по базе за день
        for old_text in self.daily_texts:
            if SequenceMatcher(None, text, old_text).ratio() > self.similarity_threshold:
                logger.info(f"Обнаружен дубликат с текстом из daily_lines: {old_text[:50]}...")
                return True
        # Проверка по текущей сессии (точный хеш и схожесть)
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if text_hash in self.text_hashes:
            return True
        for existing_text in self.texts_by_channel[channel_name]:
            if await is_similar_text(text, existing_text, self.similarity_threshold):
                return True
        # Если дубликат не найден, добавляем текст в хранилище
        self.texts_by_channel[channel_name].add(text)
        self.text_hashes.add(text_hash)
        return False

async def process_file(file_path, channel_name, duplicate_checker):
    """Обработка одного файла (скриншота) с проверкой на дубликаты и ключевые слова."""
    try:
        # Извлекаем timestamp из имени файла
        file_name = os.path.basename(file_path)
        try:
            date_pattern = r'(\d{8})_(\d{6})'
            match = re.search(date_pattern, file_name)
            
            if match:
                date_str = match.group(1)  # YYYYMMDD
                time_str = match.group(2)  # HHMMSS
                
                try:
                    timestamp = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                except ValueError:
                    timestamp = datetime.now()
                    logger.warning(f"Не удалось распарсить дату из имени файла {file_name}, используется текущее время")
            else:
                timestamp = datetime.now()
                logger.warning(f"Не найден формат даты в имени файла {file_name}, используется текущее время")
                
        except Exception as e:
            logger.warning(f"Ошибка при парсинге даты из имени файла {file_name}: {e}")
            timestamp = datetime.now()

        text = await recognize_text(file_path)
        if not text:
            logger.warning(f"Не удалось распознать текст в файле {file_path}")
            os.remove(file_path)
            logger.info(f"Удален файл с нечитаемым текстом: {file_path}")
            return None
            
        is_readable, corrected_text = await is_readable_text(text, file_path)
        if not is_readable:
            logger.warning(f"Распознан нечитаемый текст в файле {file_path}: {text}")
            os.remove(file_path)
            logger.info(f"Удален файл с нечитаемым текстом: {file_path}")
            return None

        # Проверяем на дубликаты
        if await duplicate_checker.is_duplicate(corrected_text, channel_name):
            logger.info(f"Обнаружен дубликат текста в файле {file_path}: {corrected_text[:50]}...")
            os.remove(file_path)
            logger.info(f"Удален файл с дубликатом текста: {file_path}")
            return None

        # Проверяем наличие ключевых слов
        text_words = set(re.findall(r'\b\w+\b', corrected_text.lower()))
        has_keywords = bool(text_words & KEYWORDS)

        if has_keywords:
            # Перемещаем файл в папку screenshots_processed
            processed_dir = ensure_processed_dir()
            new_path = os.path.join(processed_dir, file_name)
            shutil.move(file_path, new_path)
            logger.info(f"Файл перемещен в {new_path} (найдены ключевые слова)")
            file_path = new_path
        else:
            # Удаляем файл, если нет ключевых слов
            os.remove(file_path)
            logger.info(f"Удален файл без ключевых слов: {file_path}")
            return None
            
        return {
            "Channel": channel_name,
            "Timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "Text": corrected_text,
            "Source": file_path
        }
    except Exception as e:
        logger.error(f"Ошибка при обработке файла {file_path}: {e}")
        return None

async def process_channel(channel_name, base_dir="screenshots", duplicate_checker=None):
    """Обработка всех файлов в папке канала."""
    results = []
    channel_dir = os.path.join(base_dir, channel_name)
    if not os.path.isdir(channel_dir):
        logger.warning(f"Папка {channel_dir} не является директорией")
        return results
    logger.info(f"Найдено файлов в папке {channel_dir}: {len(os.listdir(channel_dir))}")
    for file_name in os.listdir(channel_dir):
        file_path = os.path.join(channel_dir, file_name)
        if os.path.isfile(file_path) and file_name.lower().endswith(('.png', '.jpg', '.jpeg')):
            result = await process_file(file_path, channel_name, duplicate_checker)
            if result:
                results.append(result)
    logger.info(f"Обработано файлов для канала {channel_name}: {len(results)}")
    return results

def get_daily_file_path():
    """Get the path for today's daily file."""
    today = datetime.now().strftime("%Y-%m-%d")
    logs_dir = get_logs_dir()
    return os.path.join(logs_dir, f"daily_lines_{today}.xlsx")

def load_daily_file():
    """Load today's daily file if it exists."""
    file_path = get_daily_file_path()
    if os.path.exists(file_path):
        try:
            return pd.read_excel(file_path)
        except Exception as e:
            logger.error(f"Error loading daily file: {e}")
            return pd.DataFrame(columns=["Channel", "Timestamp", "Text", "Source"])
    return pd.DataFrame(columns=["Channel", "Timestamp", "Text", "Source"])

def save_to_daily_file(new_data):
    """Save new data to daily file and return only new entries."""
    try:
        file_path = get_daily_file_path()
        daily_df = load_daily_file()
        
        # Convert new data to DataFrame if it's a list
        if isinstance(new_data, list):
            new_df = pd.DataFrame(new_data)
        else:
            new_df = new_data
            
        # Find new entries by comparing with existing data
        if not daily_df.empty:
            # Create a set of existing texts for faster lookup
            existing_texts = set(daily_df['Text'].str.lower())
            # Filter out entries that already exist
            new_entries = new_df[~new_df['Text'].str.lower().isin(existing_texts)]
        else:
            new_entries = new_df
            
        # Combine with existing data
        combined_df = pd.concat([daily_df, new_entries], ignore_index=True)
        
        # Remove duplicates based on Text column
        combined_df = combined_df.drop_duplicates(subset=['Text'], keep='first')
        
        # Sort by Timestamp
        combined_df = combined_df.sort_values('Timestamp')
        
        # Save to file
        combined_df.to_excel(file_path, index=False, engine='openpyxl')
        logger.info(f"Saved {len(new_entries)} new entries to daily file")
        
        # Return the new entries and their sources
        return file_path, new_entries
    except Exception as e:
        logger.error(f"Error saving to daily file: {e}")
        return None, pd.DataFrame()

def get_logs_dir():
    """Получение пути к директории logs относительно исполняемого файла."""
    if getattr(sys, 'frozen', False):
        # Если это исполняемый файл (PyInstaller)
        base_path = os.path.dirname(sys.executable)
    else:
        # Если это скрипт Python
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    logs_dir = os.path.join(base_path, 'logs')
    # Создаем директорию logs, если она не существует
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir

async def process_screenshots(base_dir="screenshots"):
    """Основная функция обработки всех каналов и сохранения в Excel."""
    try:
        if not os.path.exists(base_dir):
            logger.error(f"Папка {base_dir} не найдена")
            return None, None

        all_results = []
        duplicate_checker = TextDuplicateChecker()  # Инициализируем проверку дубликатов
        logger.info(f"Сканирование директории: {base_dir}")
        logger.info(f"Найдено каналов: {len(os.listdir(base_dir))}")
        
        # Список папок, которые нужно исключить
        excluded_folders = ["RBK", "MIR24", "TVC", "NTV"]
        
        # Даем небольшую паузу для завершения записи файлов
        await asyncio.sleep(2)
        
        for channel_name in os.listdir(base_dir):
            if channel_name in excluded_folders:
                logger.info(f"Пропуск папки {channel_name} (исключена из обработки)")
                continue
                
            channel_dir = os.path.join(base_dir, channel_name)
            if os.path.isdir(channel_dir):
                logger.info(f"Обработка канала: {channel_name}")
                results = await process_channel(channel_name, base_dir, duplicate_checker)
                logger.info(f"Результаты для канала {channel_name}: {len(results)} записей")
                all_results.extend(results)

        if not all_results:
            logger.warning("Нет результатов для сохранения")
            return None, None

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        # Получаем путь к директории logs
        logs_dir = get_logs_dir()
        
        # Сохраняем в Excel
        excel_file = os.path.join(logs_dir, f"recognized_text_{timestamp}.xlsx")
        try:
            df = pd.DataFrame(all_results)
            df.to_excel(excel_file, index=False, engine='openpyxl')
            logger.info(f"Результаты сохранены в Excel: {excel_file}")
            
            # Save to daily file and get new entries
            daily_file, new_entries = save_to_daily_file(df)
            if daily_file:
                logger.info(f"Results also saved to daily file: {daily_file}")
                if not new_entries.empty:
                    logger.info(f"Found {len(new_entries)} new entries to send to Telegram")
                    return excel_file, [r["Source"] for r in new_entries.to_dict('records')]
                else:
                    logger.info("No new entries to send to Telegram")
                    return excel_file, []
            
        except ImportError:
            logger.error("Библиотека openpyxl не установлена, невозможно сохранить результаты")
            return None, None
        except Exception as e:
            logger.error(f"Ошибка при сохранении в Excel: {e}")
            return None, None
        
        return excel_file, []

    except Exception as e:
        logger.error(f"Ошибка при обработке файлов: {e}")
        return None, None

def delete_daily_file():
    """Удаляет ежедневный файл за текущий день."""
    file_path = get_daily_file_path()
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info(f"Удалён ежедневный файл: {file_path}")
        except Exception as e:
            logger.error(f"Ошибка при удалении ежедневного файла: {e}")
    else:
        logger.info(f"Файл для удаления не найден: {file_path}")

if __name__ == "__main__":
    # ... существующий код ...
    # Планировщик для удаления ежедневного файла в 23:50
    schedule.every().day.at("23:50").do(delete_daily_file)
    while True:
        schedule.run_pending()
        time.sleep(30)
    # ... existing code ...