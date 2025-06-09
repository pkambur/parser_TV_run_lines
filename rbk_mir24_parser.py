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

# Настройка логирования
logger = logging.getLogger(__name__)

# Папки
base_dir = "screenshots"
processed_dir = "screenshots_processed"

# Загрузка ключевых слов из файла keywords.json
try:
    with open("keywords.json", "r", encoding="utf-8") as f:
        keywords = json.load(f)
    logger.info(f"Ключевые слова успешно загружены: {keywords}")
except FileNotFoundError:
    logger.error("Файл keywords.json не найден")
    keywords = []
except Exception as e:
    logger.error(f"Ошибка при загрузке keywords.json: {e}")
    keywords = []

# Предобработка изображения
def preprocess_image(image_path):
    try:
        img = cv2.imread(image_path)
        if img is None:
            logger.error(f"Не удалось загрузить изображение: {image_path}")
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.convertScaleAbs(gray, alpha=2.0, beta=10)
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 5
        )
        gray = cv2.fastNlMeansDenoising(gray, h=10)
        return gray
    except Exception as e:
        logger.error(f"Ошибка при обработке изображения {image_path}: {e}")
        return None

# Распознавание текста
def recognize_text(image_path):
    try:
        processed_img = preprocess_image(image_path)
        if processed_img is None:
            return ""
        custom_config = r'--oem 3 --psm 6 -l rus+eng --dpi 600'
        text = pytesseract.image_to_string(processed_img, config=custom_config)
        text = text.strip()
        logger.info(f"Распознанный текст для {image_path}: '{text}'")
        valid_text_pattern = re.compile(r'^[a-zA-Zа-яА-Я0-9,.!?\-\s:]+$')
        meaningful_text_pattern = re.compile(r'[a-zA-Zа-яА-Я]{2,}')
        if text and valid_text_pattern.match(text) and meaningful_text_pattern.search(text):
            logger.info(f"Текст прошел фильтрацию: '{text}'")
            return text
        else:
            logger.warning(f"Текст не прошел фильтрацию: '{text}'")
            return text
    except Exception as e:
        logger.error(f"Ошибка при распознавании текста в {image_path}: {e}")
        return ""

# Проверка наличия ключевых слов
def has_keywords(text):
    text_lower = text.lower()
    result = any(keyword.lower() in text_lower for keyword in keywords)
    logger.info(f"Проверка ключевых слов для '{text}': {result}")
    return result

# Базовое объединение текста
def combine_texts(screenshots_data):
    combined_texts = []
    for _, _, filename, text in screenshots_data:
        logger.info(f"Обрабатываем текст из {filename}: '{text}'")
        fragments = text.split("\n")
        if any(has_keywords(fragment.strip()) for fragment in fragments if fragment.strip()):
            combined_texts.append(text.strip())
            logger.info(f"Сохранен полный текст: '{text.strip()}'")
        else:
            logger.info(f"Текст не содержит ключевых слов: '{text}'")
    return combined_texts

async def process_rbk_mir24():
    data = {"Channel": [], "Timestamp": [], "Text": [], "Screenshot": []}
    channels = ["RBK", "MIR24"]

    if not os.path.exists(base_dir):
        logger.error(f"Папка {base_dir} не найдена")
        return None, None

    for channel_name in channels:
        channel_dir = os.path.join(base_dir, channel_name)
        if not os.path.isdir(channel_dir):
            logger.warning(f"Папка {channel_dir} не найдена")
            continue

        logger.info(f"Обработка канала: {channel_name}")
        screenshots = []
        for filename in os.listdir(channel_dir):
            if filename.endswith(".jpg"):
                image_path = os.path.join(channel_dir, filename)
                try:
                    timestamp_str = filename.replace(f"{channel_name}_", "").replace(".jpg", "")
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
                except ValueError as e:
                    logger.warning(f"Не удалось извлечь временную метку из {filename}: {e}")
                    timestamp = datetime.now()
                text = recognize_text(image_path)
                screenshots.append((image_path, timestamp, filename, text))
                # Позволяем отмену задачи
                await asyncio.sleep(0)

        screenshots.sort(key=lambda x: x[1])
        i = 0
        while i < len(screenshots):
            group = [screenshots[i]]
            timestamp = screenshots[i][1]
            j = i + 1
            while j < len(screenshots):
                time_diff = (screenshots[j][1] - timestamp).total_seconds()
                if time_diff > 2:
                    break
                group.append(screenshots[j])
                j += 1

            logger.info(f"Группа скриншотов: {[item[2] for item in group]}")
            combined_texts = combine_texts(group)
            screenshot_files = [item[2] for item in group]

            for combined_text in combined_texts:
                data["Channel"].append(channel_name)
                data["Timestamp"].append(timestamp)
                data["Text"].append(combined_text)
                data["Screenshot"].append(screenshot_files)
                for image_path, _, filename, _ in group:
                    dest_path = os.path.join(processed_dir, filename)
                    if os.path.exists(image_path):
                        shutil.move(image_path, dest_path)
                        logger.info(f"Скриншот перемещен в {dest_path}")
                # Позволяем отмену задачи
                await asyncio.sleep(0)

            i = j

    # Сохранение в CSV
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"logs/recognized_text_rbk_mir24_{timestamp}.csv"
    df = pd.DataFrame(data)
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    logger.info(f"Результаты РБК и МИР24 сохранены в {output_file}")
    return output_file, data["Screenshot"]