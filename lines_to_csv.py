import os
import json
import cv2
import pytesseract
from PIL import Image
import pandas as pd
from datetime import datetime
import re
import time
import requests
from difflib import SequenceMatcher
import logging
from pathlib import Path
from typing import List, Tuple, Optional
import numpy as np

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TextDuplicateChecker:
    def __init__(self, similarity_threshold: float = 0.8):
        self.previous_texts: List[str] = []
        self.similarity_threshold = similarity_threshold

    def is_duplicate(self, text: str, compare_texts: List[str]) -> bool:
        for prev_text in compare_texts:
            if not prev_text or not text:
                continue
            similarity = SequenceMatcher(None, text.lower(), prev_text.lower()).ratio()
            if similarity > self.similarity_threshold:
                return True
        return False

    def add_text(self, text: str):
        self.previous_texts.append(text)

def load_keywords() -> List[str]:
    try:
        with open('keywords.json', 'r', encoding='utf-8') as f:
            keywords = json.load(f)
        return keywords
    except Exception as e:
        logger.error(f"Ошибка загрузки keywords.json: {e}")
        return []

def preprocess_image(image_path: str) -> np.ndarray:
    try:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Не удалось загрузить изображение: {image_path}")
        _, thresh = cv2.threshold(img, 150, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh
    except Exception as e:
        logger.error(f"Ошибка предобработки изображения {image_path}: {e}")
        return None

def recognize_text(image_path: str) -> str:
    try:
        img = preprocess_image(image_path)
        if img is None:
            return ""
        text = pytesseract.image_to_string(img, lang='rus+eng')
        return text.strip()
    except Exception as e:
        logger.error(f"Ошибка распознавания текста в {image_path}: {e}")
        return ""

def is_readable_text_local(text: str) -> bool:
    """
    Локальная проверка читаемости текста без использования API.
    Текст считается читаемым, если:
    - Содержит ≥3 слов.
    - Содержит ≥10 символов (не считая пробелы).
    - Не состоит только из чисел, знаков препинания или случайных символов.
    - Содержит слова длиной ≥3 символов.
    - Содержит хотя бы одно слово из списка часто встречающихся слов.
    """
    if not text:
        return False

    # Удаляем лишние пробелы и переносы строк
    text = ' '.join(text.split())
    
    # Проверяем минимальную длину текста (без пробелов)
    if len(text.replace(' ', '')) < 10:
        return False

    # Разбиваем на слова
    words = [word.strip('.,!?()[]{}":;').lower() for word in text.split()]
    words = [word for word in words if word]  # Удаляем пустые слова после очистки

    # Проверяем количество слов
    if len(words) < 3:
        return False

    # Проверяем, что текст не состоит только из чисел или знаков препинания
    if re.match(r'^[\d\s.,!?()[]{}":;]+$', text):
        return False

    # Проверяем длину слов (хотя бы одно слово ≥3 символов)
    if not any(len(word) >= 3 for word in words):
        return False

    # Список часто встречающихся слов (русский и английский)
    common_words = {
        'и', 'в', 'на', 'с', 'по', 'для', 'не', 'что', 'как', 'это',
        'the', 'and', 'to', 'of', 'in', 'for', 'is', 'on', 'that', 'by'
    }
    
    # Проверяем наличие хотя бы одного слова из common_words
    if not any(word in common_words for word in words):
        return False

    return True

def is_readable_text(text: str, image_path: str) -> bool:
    """
    Проверка читаемости текста. Сначала пытается использовать Hugging Face API,
    при недоступности API использует локальную проверку.
    """
    try:
        # Проверка через Hugging Face API
        headers = {"Authorization": f"Bearer {os.getenv('HF_TOKEN')}"}
        payload = {
            "inputs": [
                {
                    "image": image_path,
                    "text": "Is the text in the image readable and meaningful? Answer with 'Yes' or 'No'."
                }
            ]
        }
        response = requests.post(
            "https://api-inference.huggingface.co/models/Qwen/Qwen2.5-VL-7B-Instruct",
            headers=headers,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        return result.get('text', '').lower() == 'yes'
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        logger.warning(f"API Hugging Face недоступен ({e}), используется локальная проверка")
        return is_readable_text_local(text)
    except Exception as e:
        logger.error(f"Неизвестная ошибка при обращении к API: {e}")
        return is_readable_text_local(text)

def process_file(image_path: str, keywords: List[str], duplicate_checker: TextDuplicateChecker, daily_file_path: str) -> Tuple[Optional[str], Optional[str]]:
    text = recognize_text(image_path)
    if not text:
        return None, None

    if not is_readable_text(text, image_path):
        return None, None

    daily_texts = []
    if os.path.exists(daily_file_path):
        try:
            df = pd.read_excel(daily_file_path)
            daily_texts = df['Text'].tolist()
        except Exception as e:
            logger.error(f"Ошибка чтения {daily_file_path}: {e}")

    if duplicate_checker.is_duplicate(text, daily_texts + duplicate_checker.previous_texts):
        return None, None

    if any(keyword.lower() in text.lower() for keyword in keywords):
        duplicate_checker.add_text(text)
        return text, image_path
    return None, None

def save_to_daily_file(channel: str, text: str, image_path: str, daily_file_path: str):
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data = {'Timestamp': timestamp, 'Channel': channel, 'Text': text, 'ImagePath': image_path}
        
        if os.path.exists(daily_file_path):
            df = pd.read_excel(daily_file_path)
            df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
        else:
            df = pd.DataFrame([data])
        
        df.to_excel(daily_file_path, index=False)
        logger.info(f"Сохранено в {daily_file_path}: {text}")
    except Exception as e:
        logger.error(f"Ошибка сохранения в {daily_file_path}: {e}")

def process_screenshots(screenshots_dir: str, processed_dir: str, daily_file_path: str):
    keywords = load_keywords()
    duplicate_checker = TextDuplicateChecker()

    for channel_dir in os.listdir(screenshots_dir):
        channel_path = os.path.join(screenshots_dir, channel_dir)
        if not os.path.isdir(channel_path):
            continue

        # Пропускаем определенные каналы
        if channel_dir in ['RBK', 'MIR24', 'TVC', 'NTV', 'RenTV']:
            continue

        processed_channel_dir = os.path.join(processed_dir, channel_dir)
        os.makedirs(processed_channel_dir, exist_ok=True)

        for image_file in os.listdir(channel_path):
            image_path = os.path.join(channel_path, image_file)
            if not image_file.endswith(('.png', '.jpg', '.jpeg')):
                continue

            text, valid_image_path = process_file(image_path, keywords, duplicate_checker, daily_file_path)
            if text and valid_image_path:
                new_path = os.path.join(processed_channel_dir, image_file)
                os.rename(image_path, new_path)
                save_to_daily_file(channel_dir, text, new_path, daily_file_path)
            else:
                try:
                    os.remove(image_path)
                    logger.info(f"Удален файл без ключевых слов: {image_path}")
                except Exception as e:
                    logger.error(f"Ошибка удаления {image_path}: {e}")

def get_daily_file_path():
    """
    Возвращает путь к ежедневному файлу с бегущими строками и список ранее распознанных текстов за день.
    Путь формируется по текущей дате. Если файл существует, возвращает также список текстов из него.
    """
    file_path = f"daily_lines_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    previous_texts = []
    if os.path.exists(file_path):
        try:
            df = pd.read_excel(file_path)
            if 'Text' in df.columns:
                previous_texts = df['Text'].astype(str).tolist()
        except Exception as e:
            logger.error(f"Ошибка чтения {file_path}: {e}")
    return file_path, previous_texts

if __name__ == "__main__":
    screenshots_dir = "screenshots"
    processed_dir = "screenshots_processed"
    daily_file_path, previous_texts = get_daily_file_path()
    process_screenshots(screenshots_dir, processed_dir, daily_file_path)