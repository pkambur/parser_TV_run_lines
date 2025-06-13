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

logger = logging.getLogger(__name__)

# Инициализация Hugging Face API
HF_API_TOKEN = os.getenv("HUGGINGFACE_HUB_TOKEN")
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
    from difflib import SequenceMatcher
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
        # Формируем промпт для исправления текста
        prompt = (
            f"Исправь следующий текст, распознанный с изображения, на русский или английский язык, "
            f"сохраняя его смысл. Если текст бессмысленный или содержит слишком много ошибок, "
            f"укажи, что он нечитаемый. Текст: '{text}'"
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
                "parameters": {"max_new_tokens": 512}
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
                        corrected_text = result[0].get("generated_text", text)
                    else:
                        logger.error(f"Некорректный ответ API: {result}")
                        return len(words) >= 2 and len(clean_text.strip()) >= 5, text

                logger.debug(f"Qwen2.5-VL исправленный текст: {corrected_text}")
                
                # Проверяем, указала ли модель, что текст нечитаемый
                if "нечитаемый" in corrected_text.lower() or "бессмысленный" in corrected_text.lower():
                    logger.debug(f"Qwen2.5-VL определил текст как нечитаемый: {text}")
                    return False, text
                
                # Проверяем исправленный текст на минимальные требования
                clean_corrected = re.sub(r'[^а-яА-Яa-zA-Z\s]', '', corrected_text)
                if len(clean_corrected.strip()) < 5 or len(clean_corrected.strip().split()) < 2:
                    logger.debug(f"Исправленный текст не соответствует требованиям: {corrected_text}")
                    return False, text
                    
                return True, corrected_text
                
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

class TextDuplicateChecker:
    def __init__(self, similarity_threshold=0.9):
        self.similarity_threshold = similarity_threshold
        self.texts_by_channel = defaultdict(set)  # Хранит тексты по каналам
        self.text_hashes = set()  # Хранит хеши всех текстов
        
    async def is_duplicate(self, text, channel_name):
        """Проверяет, является ли текст дубликатом."""
        # Сначала проверяем точное совпадение по хешу
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if text_hash in self.text_hashes:
            return True
            
        # Затем проверяем похожесть текста
        for existing_text in self.texts_by_channel[channel_name]:
            if await is_similar_text(text, existing_text, self.similarity_threshold):
                return True
                
        # Если дубликат не найден, добавляем текст в хранилище
        self.texts_by_channel[channel_name].add(text)
        self.text_hashes.add(text_hash)
        return False

async def process_file(file_path, channel_name, duplicate_checker):
    """Обработка одного файла (скриншота) с проверкой на дубликаты."""
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

async def process_screenshots(base_dir="screenshots"):
    """Основная функция обработки всех каналов и сохранения в CSV и Excel."""
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
        
        # Создаём директорию logs, если не существует
        os.makedirs("logs", exist_ok=True)
        
        # Сохраняем в CSV
        csv_file = f"logs/recognized_text_{timestamp}.csv"
        df = pd.DataFrame(all_results)
        df.to_csv(csv_file, index=False, encoding='utf-8-sig')
        logger.info(f"Результаты сохранены в CSV: {csv_file}")
        
        # Проверяем наличие CSV на диске
        if not os.path.exists(csv_file):
            logger.error(f"CSV-файл {csv_file} не был создан")
            return None, None
            
        # Сохраняем в Excel, если openpyxl установлен
        excel_file = f"logs/recognized_text_{timestamp}.xlsx"
        try:
            df.to_excel(excel_file, index=False, engine='openpyxl')
            logger.info(f"Результаты сохранены в Excel: {excel_file}")
        except ImportError:
            logger.warning("Библиотека openpyxl не установлена, пропуск сохранения в Excel")
        except Exception as e:
            logger.error(f"Ошибка при сохранении в Excel: {e}")
        
        return csv_file, [r["Source"] for r in all_results]

    except Exception as e:
        logger.error(f"Ошибка при обработке файлов: {e}")
        return None, None