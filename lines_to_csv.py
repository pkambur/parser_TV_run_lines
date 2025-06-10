import os
import cv2
import pytesseract
import pandas as pd
import numpy as np
import logging
import re
import json
from datetime import datetime
import shutil
import asyncio
from difflib import SequenceMatcher
from pyspellchecker import SpellChecker
import warnings
warnings.filterwarnings('ignore')

# Настройка логирования
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/text_recognition_log.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Путь к Tesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Папки
base_dir = "screenshots"
processed_dir = "screenshots_processed"

# Создание папки для обработанных файлов
os.makedirs(processed_dir, exist_ok=True)

# Инициализация проверки орфографии
try:
    spell_checker = SpellChecker(language='ru')
    logger.info("Проверка орфографии успешно инициализирована")
except Exception as e:
    logger.error(f"Ошибка инициализации проверки орфографии: {e}")
    spell_checker = None

def text_similarity(text1, text2):
    """Вычисляет схожесть между двумя текстами."""
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1, text2).ratio()

def is_similar_to_any(text, existing_texts, threshold=0.9):
    """Проверяет, похож ли текст на любой из существующих текстов."""
    for existing_text in existing_texts:
        if text_similarity(text, existing_text) >= threshold:
            return True
    return False

def preprocess_image(image):
    """Предобработка изображения для улучшения распознавания текста."""
    try:
        if image is None:
            return None
            
        # Конвертация в оттенки серого
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Нормализация яркости
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        
        # Двусторонняя фильтрация для сохранения краев
        bilateral = cv2.bilateralFilter(gray, 11, 17, 17)
        
        # Увеличение контраста
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        contrast = clahe.apply(bilateral)
        
        # Адаптивная пороговая обработка
        thresh = cv2.adaptiveThreshold(
            contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 5
        )
        
        # Морфологические операции
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
        morph = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        # Увеличение резкости
        sharpen_kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(morph, -1, sharpen_kernel)
        
        # Масштабирование изображения
        scale_percent = 200
        width = int(sharpened.shape[1] * scale_percent / 100)
        height = int(sharpened.shape[0] * scale_percent / 100)
        scaled = cv2.resize(sharpened, (width, height), interpolation=cv2.INTER_CUBIC)
        
        return scaled
    except Exception as e:
        logger.error(f"Ошибка при обработке изображения: {e}")
        return None

def correct_text(text):
    """Исправление орфографических ошибок с помощью SpellChecker."""
    if not text or not spell_checker:
        return text
    try:
        words = text.split()
        corrected_words = []
        for word in words:
            if spell_checker.unknown([word]):
                correction = spell_checker.correction(word)
                if correction:
                    corrected_words.append(correction)
                else:
                    corrected_words.append(word)
            else:
                corrected_words.append(word)
        corrected = ' '.join(corrected_words)
        logger.info(f"Исправленный текст: '{corrected}'")
        return corrected
    except Exception as e:
        logger.error(f"Ошибка при исправлении текста: {e}")
        return text

def recognize_text(image):
    """Распознавание текста из изображения."""
    try:
        processed_img = preprocess_image(image)
        if processed_img is None:
            return ""
            
        # Попробовать разные режимы PSM для лучшего распознавания
        configs = [
            r'--oem 3 --psm 6 -l rus+eng --dpi 300',  # Блок текста
            r'--oem 3 --psm 3 -l rus+eng --dpi 300',  # Автоопределение
            r'--oem 3 --psm 11 -l rus+eng --dpi 300'  # Разреженный текст
        ]
        
        texts = []
        for config in configs:
            text = pytesseract.image_to_string(processed_img, config=config)
            text = text.strip()
            if text:
                texts.append(text)
        
        # Выбрать наиболее вероятный текст
        if not texts:
            return ""
            
        text = max(texts, key=len)  # Берем самый длинный текст
        
        # Очистка текста
        text = re.sub(r'[^\w\s.,!?;:()\-–—«»""\'\'№]', '', text)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\b[a-zA-Z0-9]\b', '', text)
        
        if re.match(r'^[\d\s\W]+$', text):
            return ""
            
        # Исправление орфографии
        text = correct_text(text)
        
        logger.info(f"Распознанный текст: '{text}'")
        
        if len(text) < 2:
            logger.warning("Текст слишком короткий")
            return ""
            
        if not re.search(r'[а-яА-Я]', text):
            logger.warning("Текст не содержит русских букв")
            return ""
            
        return text
    except Exception as e:
        logger.error(f"Ошибка при распознавании текста: {e}")
        return ""

def has_keywords(text):
    """Проверка наличия ключевых слов в тексте."""
    return True

def combine_texts(texts):
    """Объединение текстов с проверкой ключевых слов."""
    combined_texts = []
    for text in texts:
        if not text:
            continue
            
        logger.info(f"Обрабатываем текст: '{text}'")
        combined_texts.append(text.strip())
        logger.info(f"Сохранен текст: '{text.strip()}'")
    return combined_texts

def extract_frames(video_path, interval=1):
    """Извлечение кадров из видео с заданным интервалом."""
    frames = []
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видео: {video_path}")
            return frames
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_interval = int(fps * interval)
        frame_count = 0
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
                
            if frame_count % frame_interval == 0:
                frames.append(frame)
            frame_count += 1
            
        cap.release()
        logger.info(f"Извлечено {len(frames)} кадров из видео {video_path}")
        return frames
    except Exception as e:
        logger.error(f"Ошибка при извлечении кадров из видео {video_path}: {e}")
        return []

async def process_file(file_path, channel_name, timestamp, existing_texts):
    """Обработка одного файла (скриншот или видео)."""
    try:
        texts = []
        if file_path.endswith(('.jpg', '.jpeg', '.png')):
            image = cv2.imread(file_path)
            if image is not None:
                text = recognize_text(image)
                if text and not is_similar_to_any(text, existing_texts):
                    texts.append(text)
                else:
                    logger.info(f"Текст похож на существующий или пустой, файл будет удален: {file_path}")
                    os.remove(file_path)
                    return []
        elif file_path.endswith(('.mp4', '.avi', '.mov')):
            frames = extract_frames(file_path)
            for frame in frames:
                text = recognize_text(frame)
                if text and not is_similar_to_any(text, existing_texts):
                    texts.append(text)
            if not texts:
                logger.info(f"Не найдено новых текстов в видео, файл будет удален: {file_path}")
                os.remove(file_path)
        
        return texts
    
    except Exception as e:
        logger.error(f"Ошибка при обработке файла {file_path}: {e}")
        return []

async def process_channel(channel_name):
    """Обработка всех файлов одного канала."""
    channel_dir = os.path.join(base_dir, channel_name)
    if not os.path.isdir(channel_dir):
        return []

    results = []
    existing_texts = []

    for filename in os.listdir(channel_dir):
        if filename.endswith(('.jpg', '.jpeg', '.png', '.mp4', '.avi', '.mov')):
            try:
                timestamp_str = filename.replace(f"{channel_name}_", "").replace(".jpg", "").replace(".mp4", "")
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
                
                file_path = os.path.join(channel_dir, filename)
                texts = await process_file(file_path, channel_name, timestamp, existing_texts)
                
                if texts:
                    combined_texts = combine_texts(texts)
                    for text in combined_texts:
                        results.append({
                            "Channel": channel_name,
                            "Timestamp": timestamp,
                            "Text": text,
                            "Source": filename
                        })
                        existing_texts.append(text)
                    
                    dest_path = os.path.join(processed_dir, filename)
                    if os.path.exists(file_path):
                        shutil.move(file_path, dest_path)
                        logger.info(f"Файл перемещен в {dest_path}")
                
                await asyncio.sleep(0)
                
            except Exception as e:
                logger.error(f"Ошибка при обработке файла {filename}: {e}")
                continue

    return results

async def process_screenshots():
    """Основная функция обработки всех каналов."""
    try:
        if not os.path.exists(base_dir):
            logger.error(f"Папка {base_dir} не найдена")
            return None, None

        all_results = []
        for channel_name in os.listdir(base_dir):
            channel_dir = os.path.join(base_dir, channel_name)
            if os.path.isdir(channel_dir):
                logger.info(f"Обработка канала: {channel_name}")
                results = await process_channel(channel_name)
                all_results.extend(results)

        if not all_results:
            logger.warning("Нет результатов для сохранения")
            return None, None

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file = f"logs/recognized_text_{timestamp}.csv"
        df = pd.DataFrame(all_results)
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        logger.info(f"Результаты сохранены в {output_file}")
        return output_file, [r["Source"] for r in all_results]

    except Exception as e:
        logger.error(f"Ошибка при обработке файлов: {e}")
        return None, None