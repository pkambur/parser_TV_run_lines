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
from collections import Counter
from config_manager import config_manager
import threading

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TextDuplicateChecker:
    """
    Класс для проверки дублирования текста по схожести.
    """
    def __init__(self, similarity_threshold: float = 0.8):
        """
        Инициализация чекера дубликатов.
        """
        self.previous_texts: List[str] = []
        self.similarity_threshold = similarity_threshold
        self._lock = threading.Lock()

    def is_duplicate(self, text: str, compare_texts: List[str]) -> bool:
        """
        Проверяет, является ли текст дубликатом среди compare_texts.
        """
        with self._lock:
            for prev_text in compare_texts:
                if not prev_text or not text:
                    continue
                similarity = SequenceMatcher(None, text.lower(), prev_text.lower()).ratio()
                if similarity > self.similarity_threshold:
                    return True
        return False

    def add_text(self, text: str):
        """
        Добавляет текст в историю для последующей проверки.
        """
        with self._lock:
            self.previous_texts.append(text)

def load_keywords() -> List[str]:
    """
    Загрузка ключевых слов через config_manager.
    """
    return config_manager.get_keywords_list()

def preprocess_image(image_path: str) -> np.ndarray:
    """
    Предобработка изображения для OCR.
    """
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
    """
    Распознавание текста на изображении с помощью pytesseract.
    """
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
    Улучшенная локальная проверка читаемости текста без использования API.
    Текст считается читаемым, если:
    - Содержит ≥3 слов.
    - Содержит ≥10 символов (не считая пробелы).
    - Не состоит только из чисел, знаков препинания или случайных символов.
    - Содержит слова длиной ≥3 символов.
    - Содержит хотя бы одно слово из списка часто встречающихся слов.
    - Имеет разумное соотношение гласных/согласных.
    - Не содержит слишком много повторяющихся символов.
    """
    if not text:
        return False

    # Удаляем лишние пробелы и переносы строк
    text = ' '.join(text.split())
    
    # Проверяем минимальную длину текста (без пробелов)
    text_no_spaces = text.replace(' ', '')
    if len(text_no_spaces) < 10:
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

    # Расширенный список часто встречающихся слов (русский и английский)
    common_words = {
        # Русские слова
        'и', 'в', 'на', 'с', 'по', 'для', 'не', 'что', 'как', 'это', 'то', 'так', 'был', 'была', 'были',
        'быть', 'есть', 'был', 'стал', 'стала', 'стали', 'стать', 'может', 'может', 'должен', 'должна',
        'должны', 'нужно', 'надо', 'можно', 'нельзя', 'все', 'всех', 'всем', 'всеми', 'всего', 'всей',
        'всех', 'всегда', 'никогда', 'иногда', 'часто', 'редко', 'очень', 'слишком', 'больше', 'меньше',
        'лучше', 'хуже', 'выше', 'ниже', 'дальше', 'ближе', 'раньше', 'позже', 'сейчас', 'теперь',
        'сегодня', 'завтра', 'вчера', 'утром', 'днем', 'вечером', 'ночью', 'год', 'года', 'лет', 'месяц',
        'месяца', 'неделя', 'недели', 'день', 'дня', 'час', 'часа', 'минута', 'минуты', 'секунда',
        # Английские слова
        'the', 'and', 'to', 'of', 'in', 'for', 'is', 'on', 'that', 'by', 'with', 'he', 'as', 'you', 'do',
        'at', 'this', 'but', 'his', 'from', 'they', 'we', 'say', 'her', 'she', 'or', 'an', 'will', 'my',
        'one', 'all', 'would', 'there', 'their', 'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get',
        'which', 'go', 'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just', 'him', 'know', 'take',
        'people', 'into', 'year', 'your', 'good', 'some', 'could', 'them', 'see', 'other', 'than', 'then',
        'now', 'look', 'only', 'come', 'its', 'over', 'think', 'also', 'back', 'after', 'use', 'two',
        'how', 'our', 'work', 'first', 'well', 'way', 'even', 'new', 'want', 'because', 'any', 'these',
        'give', 'day', 'most', 'us'
    }
    
    # Проверяем наличие хотя бы одного слова из common_words
    if not any(word in common_words for word in words):
        return False

    # Проверяем соотношение гласных/согласных (для русского текста)
    vowels_ru = 'аеёиоуыэюя'
    consonants_ru = 'бвгджзйклмнпрстфхцчшщ'
    vowels_en = 'aeiouy'
    consonants_en = 'bcdfghjklmnpqrstvwxz'
    
    # Определяем язык текста (простая эвристика)
    ru_chars = sum(1 for c in text_no_spaces if c in vowels_ru + consonants_ru)
    en_chars = sum(1 for c in text_no_spaces if c in vowels_en + consonants_en)
    
    if ru_chars > en_chars:  # Русский текст
        vowels = sum(1 for c in text_no_spaces if c in vowels_ru)
        consonants = sum(1 for c in text_no_spaces if c in consonants_ru)
    else:  # Английский текст
        vowels = sum(1 for c in text_no_spaces if c in vowels_en)
        consonants = sum(1 for c in text_no_spaces if c in consonants_en)
    
    total_letters = vowels + consonants
    if total_letters > 0:
        vowel_ratio = vowels / total_letters
        # Проверяем, что соотношение гласных/согласных разумное (20-60%)
        if vowel_ratio < 0.2 or vowel_ratio > 0.6:
            return False

    # Проверяем на слишком много повторяющихся символов
    char_counts = Counter(text_no_spaces)
    most_common_char, most_common_count = char_counts.most_common(1)[0]
    if most_common_count > len(text_no_spaces) * 0.4:  # Один символ не должен занимать более 40% текста
        return False

    # Проверяем на слишком много цифр
    digits = sum(1 for c in text_no_spaces if c.isdigit())
    if digits > len(text_no_spaces) * 0.5:  # Цифры не должны занимать более 50% текста
        return False

    # Проверяем на слишком много знаков препинания
    punctuation = sum(1 for c in text_no_spaces if c in '.,!?()[]{}":;')
    if punctuation > len(text_no_spaces) * 0.3:  # Знаки препинания не должны занимать более 30% текста
        return False

    return True

def is_readable_text(text: str, image_path: str) -> bool:
    """
    Проверка читаемости текста. Использует локальную проверку или Hugging Face API.
    """
    # Импортируем токен из telegram_sender
    try:
        from telegram_sender import HF_TOKEN
    except ImportError:
        # Fallback к переменной окружения
        HF_TOKEN = os.getenv('HF_TOKEN')
    
    # Проверка существования токена HF_TOKEN
    if not HF_TOKEN:
        logger.info("HF_TOKEN не найден в переменных окружения, используется локальная проверка")
        return is_readable_text_local(text)
    
    # Для анализа изображений нужны специальные модели, которые могут быть недоступны
    # Поэтому используем только локальную проверку
    logger.info("Используется локальная проверка читаемости текста")
    return is_readable_text_local(text)

def process_file(image_path: str, keywords: List[str], duplicate_checker: TextDuplicateChecker, daily_file_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Обрабатывает файл: распознаёт текст, фильтрует по ключевым словам и дубликатам.
    """
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
    """
    Сохраняет строку в ежедневный файл.
    """
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
    """
    Обрабатывает скриншоты: распознаёт текст, фильтрует, сохраняет и отправляет.
    """
    keywords = load_keywords()
    duplicate_checker = TextDuplicateChecker()
    screenshots_dir = Path(screenshots_dir)
    processed_dir = Path(processed_dir)
    daily_file_path = Path(daily_file_path)
    
    # Проверка существования директории screenshots
    if not screenshots_dir.exists():
        logger.error(f"Директория screenshots не найдена: {screenshots_dir}")
        return
    
    if not screenshots_dir.is_dir():
        logger.error(f"Путь screenshots не является директорией: {screenshots_dir}")
        return
    
    # Создание директории processed_dir если она не существует
    try:
        processed_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Директория processed_dir создана/проверена: {processed_dir}")
    except Exception as e:
        logger.error(f"Ошибка при создании директории processed_dir: {e}")
        return
    
    # Создание родительской директории для daily_file_path если она не существует
    try:
        daily_file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Родительская директория для daily_file_path создана/проверена: {daily_file_path.parent}")
    except Exception as e:
        logger.error(f"Ошибка при создании родительской директории для daily_file_path: {e}")
        return
    
    for channel_dir in screenshots_dir.iterdir():
        if not channel_dir.is_dir():
            continue
        # Пропускаем определенные каналы
        if channel_dir.name in ['RBK', 'MIR24', 'TVC', 'NTV', 'RenTV']:
            continue
        processed_channel_dir = processed_dir / channel_dir.name
        try:
            processed_channel_dir.mkdir(exist_ok=True)
        except Exception as e:
            logger.error(f"Ошибка при создании директории для канала {channel_dir.name}: {e}")
            continue
        for image_file in channel_dir.iterdir():
            if not image_file.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                continue
            text, valid_image_path = process_file(str(image_file), keywords, duplicate_checker, str(daily_file_path))
            if text and valid_image_path:
                new_path = processed_channel_dir / image_file.name
                try:
                    image_file.rename(new_path)
                    save_to_daily_file(channel_dir.name, text, str(new_path), str(daily_file_path))
                except Exception as e:
                    logger.error(f"Ошибка при перемещении файла {image_file}: {e}")
            else:
                try:
                    image_file.unlink()
                    logger.info(f"Удален файл без ключевых слов: {image_file}")
                except Exception as e:
                    logger.error(f"Ошибка удаления {image_file}: {e}")

def get_daily_file_path():
    """
    Возвращает путь к ежедневному файлу.
    """
    file_path = Path(f"daily_lines_{datetime.now().strftime('%Y-%m-%d')}.xlsx")
    previous_texts = []
    if file_path.exists():
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