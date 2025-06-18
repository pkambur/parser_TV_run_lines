#!/usr/bin/env python3
"""
Модуль для распознавания текста из записанного видео с каналов RBK и MIR24
Использует OpenCV для извлечения кадров и OCR для распознавания текста
"""

import os
import cv2
import numpy as np
import pytesseract
import easyocr
import logging
from datetime import datetime
from pathlib import Path
import json
from typing import List, Dict, Tuple, Optional
import re
import pandas as pd

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VideoTextRecognizer:
    """Класс для распознавания текста из видео файлов"""
    
    def __init__(self, video_dir: str = "video", output_dir: str = "recognized_text", keep_screenshots: bool = False):
        """
        Инициализация распознавателя текста из видео
        
        Args:
            video_dir: Папка с видео файлами
            output_dir: Папка для сохранения результатов
            keep_screenshots: Сохранять ли скриншоты после обработки
        """
        self.video_dir = Path(video_dir)
        self.output_dir = Path(output_dir)
        self.keep_screenshots = keep_screenshots
        
        # Создаем папки если их нет
        self.output_dir.mkdir(exist_ok=True)
        
        # Инициализируем EasyOCR
        try:
            self.easyocr_reader = easyocr.Reader(['ru', 'en'], gpu=False)
            logger.info("EasyOCR инициализирован")
        except Exception as e:
            logger.error(f"Ошибка инициализации EasyOCR: {e}")
            self.easyocr_reader = None
        
        # Параметры для разных каналов
        self.channel_params = {
            'RBK': {
                'crop': (0, 0, 1920, 200),  # Область для обрезки (x, y, width, height)
                'frame_interval': 300,  # Интервал между кадрами (каждые 10 сек при 30 FPS)
                'min_text_length': 10,  # Минимальная длина текста
                'confidence_threshold': 0.5  # Порог уверенности для EasyOCR
            },
            'MIR24': {
                'crop': (0, 0, 1920, 200),
                'frame_interval': 300,
                'min_text_length': 10,
                'confidence_threshold': 0.5
            }
        }
        
        # Загружаем ключевые слова
        self.keywords = self.load_keywords()
        
        # Конфиг для Tesseract
        self.tesseract_config = '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя.,!?;:()[]{}\"\'- '
    
    def load_keywords(self) -> List[str]:
        """Загружает ключевые слова из файла"""
        try:
            with open('keywords.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                keywords = data.get('keywords', [])
                logger.info(f"Загружено {len(keywords)} ключевых слов: {keywords[:5]}{'...' if len(keywords) > 5 else ''}")
                return keywords
        except FileNotFoundError:
            logger.warning("Файл keywords.json не найден. Создайте файл с ключевыми словами для фильтрации.")
            return []
        except Exception as e:
            logger.error(f"Ошибка при загрузке ключевых слов: {e}")
            return []
    
    def preprocess_frame(self, frame: np.ndarray, crop_params: Tuple[int, int, int, int]) -> np.ndarray:
        """
        Предобработка кадра для улучшения распознавания
        
        Args:
            frame: Исходный кадр
            crop_params: Параметры обрезки (width, height, x, y)
            
        Returns:
            Обработанный кадр
        """
        try:
            width, height, x, y = crop_params
            h, w = frame.shape[:2]
            # Если crop выходит за границы — используем весь кадр
            if x + width > w or y + height > h or width <= 0 or height <= 0:
                logger.warning(f"[DIAG] Crop вне границ кадра {frame.shape}, используем весь кадр")
                cropped = frame
            else:
                cropped = frame[y:y+height, x:x+width]
            
            # Конвертируем в оттенки серого
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
            
            # Увеличиваем контраст
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            enhanced = clahe.apply(gray)
            
            # Убираем шум
            denoised = cv2.medianBlur(enhanced, 3)
            
            # Бинаризация
            _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            return binary
            
        except Exception as e:
            logger.error(f"Ошибка при предобработке кадра: {e}")
            return frame
    
    def recognize_text_tesseract(self, frame: np.ndarray) -> str:
        """Распознавание текста с помощью Tesseract"""
        try:
            text = pytesseract.image_to_string(frame, lang='rus+eng', config=self.tesseract_config)
            logger.info(f"[DIAG] Tesseract raw: {text}")
            return text.strip()
        except Exception as e:
            logger.error(f"Ошибка Tesseract: {e}")
            return ""
    
    def recognize_text_easyocr(self, frame: np.ndarray) -> List[Tuple[str, float]]:
        """Распознавание текста с помощью EasyOCR"""
        try:
            if self.easyocr_reader is None:
                return []
            
            results = self.easyocr_reader.readtext(frame)
            for bbox, text, confidence in results:
                logger.info(f"[DIAG] EasyOCR raw: {text} (conf={confidence})")
            return [(text, confidence) for (bbox, text, confidence) in results]
        except Exception as e:
            logger.error(f"Ошибка EasyOCR: {e}")
            return []
    
    def filter_text(self, text: str, min_length: int = 10) -> bool:
        """
        Фильтрация распознанного текста по ключевым словам из keywords.json
        
        Args:
            text: Распознанный текст
            min_length: Минимальная длина текста
            
        Returns:
            True если найдено хотя бы одно ключевое слово
        """
        if not text or len(text.strip()) < min_length:
            logger.debug(f"[FILTER] Текст слишком короткий: '{text}' (длина: {len(text.strip())})")
            return False
        
        # Убираем лишние символы
        cleaned = re.sub(r'[^\w\s.,!?;:()\[\]{}"\'-]', '', text)
        
        if len(cleaned.strip()) < min_length:
            logger.debug(f"[FILTER] Очищенный текст слишком короткий: '{cleaned}' (длина: {len(cleaned.strip())})")
            return False
        
        # Проверяем наличие ключевых слов
        if self.keywords:
            text_lower = cleaned.lower()
            found_keywords = []
            for keyword in self.keywords:
                if keyword.lower() in text_lower:
                    found_keywords.append(keyword)
            if found_keywords:
                logger.info(f"[KEYWORDS] Найдены ключевые слова в тексте: {found_keywords}")
                logger.info(f"[KEYWORDS] Текст: {text[:100]}...")
                return True
            else:
                logger.debug(f"[FILTER] Ключевые слова не найдены в тексте: '{text[:50]}...'")
                return False
        else:
            logger.warning("[FILTER] Ключевые слова не загружены! Все тексты будут отфильтрованы.")
            return False
    
    def deduplicate_texts(self, texts: List[Tuple[str, str, float]]) -> List[Tuple[str, str, float]]:
        """
        Удаление дубликатов и объединение похожих текстов
        
        Args:
            texts: Список кортежей (method, text, confidence)
            
        Returns:
            Список уникальных текстов
        """
        if not texts:
            return []
        
        # Группируем тексты по методу распознавания
        tesseract_texts = []
        easyocr_texts = []
        
        for method, text, confidence in texts:
            if method == 'tesseract':
                tesseract_texts.append((text, confidence))
            elif method == 'easyocr':
                easyocr_texts.append((text, confidence))
        
        unique_texts = []
        
        # Обрабатываем Tesseract тексты
        if tesseract_texts:
            # Берем текст с наивысшей уверенностью
            best_tesseract = max(tesseract_texts, key=lambda x: x[1])
            unique_texts.append(('tesseract', best_tesseract[0], best_tesseract[1]))
        
        # Обрабатываем EasyOCR тексты
        if easyocr_texts:
            # Удаляем дубликаты и похожие тексты
            unique_easyocr = []
            for text, confidence in easyocr_texts:
                # Проверяем, есть ли похожий текст уже в списке
                is_duplicate = False
                for existing_text, _ in unique_easyocr:
                    # Простая проверка на дубликаты (можно улучшить)
                    if text.strip().lower() == existing_text.strip().lower():
                        is_duplicate = True
                        break
                    # Проверка на частичное совпадение
                    if len(text) > 10 and len(existing_text) > 10:
                        similarity = self.calculate_similarity(text, existing_text)
                        if similarity > 0.8:  # 80% схожести
                            is_duplicate = True
                            break
                
                if not is_duplicate:
                    unique_easyocr.append((text, confidence))
            
            # Добавляем уникальные EasyOCR тексты
            for text, confidence in unique_easyocr:
                unique_texts.append(('easyocr', text, confidence))
        
        logger.info(f"Дубликаты удалены: {len(texts)} -> {len(unique_texts)} уникальных текстов")
        return unique_texts
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Вычисление схожести двух текстов
        
        Args:
            text1: Первый текст
            text2: Второй текст
            
        Returns:
            Коэффициент схожести от 0 до 1
        """
        from difflib import SequenceMatcher
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
    
    def cleanup_screenshots(self, channel_name: str, video_name: str):
        """
        Очистка папки со скриншотами после обработки
        
        Args:
            channel_name: Название канала
            video_name: Имя видео файла (без расширения)
        """
        screenshots_dir = self.output_dir / f"screenshots_{channel_name}_{video_name}"
        
        if screenshots_dir.exists():
            try:
                import shutil
                shutil.rmtree(screenshots_dir)
                logger.info(f"Очищена папка со скриншотами: {screenshots_dir}")
            except Exception as e:
                logger.error(f"Ошибка при очистке папки {screenshots_dir}: {e}")
    
    def process_video(self, video_path: Path, channel_name: str) -> List[Dict]:
        """
        Обработка видео файла: сначала создаем скриншоты каждые 10 секунд, затем распознаем текст
        
        Args:
            video_path: Путь к видео файлу
            channel_name: Название канала
            
        Returns:
            Список распознанных текстов с метаданными
        """
        logger.info(f"Обработка видео: {video_path}")
        
        if not video_path.exists():
            logger.error(f"Файл не найден: {video_path}")
            return []
        
        # Получаем параметры канала
        params = self.channel_params.get(channel_name, self.channel_params['RBK'])
        
        # Открываем видео
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видео: {video_path}")
            return []
        
        # Получаем информацию о видео
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        
        logger.info(f"FPS: {fps}, Всего кадров: {total_frames}, Длительность: {duration:.2f} сек")
        
        # Создаем папку для скриншотов
        screenshots_dir = self.output_dir / f"screenshots_{channel_name}_{video_path.stem}"
        screenshots_dir.mkdir(exist_ok=True)
        
        # Интервал для скриншотов (каждые 10 секунд)
        screenshot_interval_seconds = 10
        frame_interval = int(fps * screenshot_interval_seconds) if fps > 0 else 300  # 300 кадров при 30 FPS
        
        logger.info(f"Создание скриншотов каждые {screenshot_interval_seconds} секунд (каждые {frame_interval} кадров)")
        
        # Этап 1: Создание скриншотов
        screenshots_created = []
        frame_count = 0
        
        logger.info("Этап 1: Создание скриншотов...")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Создаем скриншот каждые N кадров
            if frame_count % frame_interval == 0:
                timestamp = frame_count / fps if fps > 0 else 0
                
                # Предобработка кадра
                processed_frame = self.preprocess_frame(frame, params['crop'])
                
                # Сохраняем скриншот
                screenshot_filename = f"screenshot_{channel_name}_{frame_count:06d}_{timestamp:.1f}s.jpg"
                screenshot_path = screenshots_dir / screenshot_filename
                
                success = cv2.imwrite(str(screenshot_path), processed_frame)
                
                if success:
                    screenshots_created.append({
                        'path': screenshot_path,
                        'timestamp': timestamp,
                        'frame_number': frame_count
                    })
                    logger.info(f"Создан скриншот: {screenshot_filename} (время: {timestamp:.1f}s)")
                else:
                    logger.error(f"Не удалось сохранить скриншот: {screenshot_filename}")
            
            frame_count += 1
        
        cap.release()
        logger.info(f"Создано {len(screenshots_created)} скриншотов")
        
        # Этап 2: Распознавание текста из скриншотов
        logger.info("Этап 2: Распознавание текста из скриншотов...")
        
        all_recognized_texts = []  # Собираем весь текст из всех скриншотов
        
        for i, screenshot_info in enumerate(screenshots_created):
            screenshot_path = screenshot_info['path']
            timestamp = screenshot_info['timestamp']
            frame_number = screenshot_info['frame_number']
            
            logger.info(f"Обработка скриншота {i+1}/{len(screenshots_created)}: {screenshot_path.name}")
            
            try:
                # Загружаем скриншот
                frame = cv2.imread(str(screenshot_path))
                
                if frame is None:
                    logger.error(f"Не удалось загрузить скриншот: {screenshot_path}")
                    continue
                
                # Распознавание текста
                tesseract_text = self.recognize_text_tesseract(frame)
                easyocr_results = self.recognize_text_easyocr(frame)
                
                # Собираем все тексты из этого скриншота
                screenshot_texts = []
                
                if tesseract_text and self.filter_text(tesseract_text, params['min_text_length']):
                    screenshot_texts.append(('tesseract', tesseract_text, 0.7))
                
                for text, confidence in easyocr_results:
                    if self.filter_text(text, params['min_text_length']) and confidence >= params['confidence_threshold']:
                        screenshot_texts.append(('easyocr', text, confidence))
                
                # Добавляем тексты из этого скриншота в общий список
                all_recognized_texts.extend(screenshot_texts)
                
                logger.info(f"Из скриншота {i+1} распознано {len(screenshot_texts)} текстов")
                
            except Exception as e:
                logger.error(f"Ошибка при обработке скриншота {screenshot_path}: {e}")
        
        # Удаляем дубликаты и объединяем похожие тексты
        unique_texts = self.deduplicate_texts(all_recognized_texts)
        
        # Создаем финальный результат
        recognized_texts = []
        
        for method, text, confidence in unique_texts:
            # Проверяем ключевые слова в тексте
            found_keywords = self.keywords
            
            result = {
                'channel': channel_name,
                'video_file': video_path.name,
                'screenshot_count': len(screenshots_created),
                'text': text,
                'recognition_method': method,
                'confidence': confidence,
                'found_keywords': found_keywords,
                'datetime': datetime.now().isoformat()
            }
            
            recognized_texts.append(result)
            
            if found_keywords:
                logger.info(f"Финальный текст [{method}] с ключевыми словами {found_keywords}: {text[:100]}...")
            else:
                logger.info(f"Финальный текст [{method}]: {text[:100]}...")
        
        logger.info(f"Обработка завершена. Из {len(screenshots_created)} скриншотов получено {len(unique_texts)} уникальных текстов")
        
        # Очистка скриншотов после обработки (если не нужно их сохранять)
        if not self.keep_screenshots:
            self.cleanup_screenshots(channel_name, video_path.stem)
        else:
            logger.info(f"Скриншоты сохранены в: {screenshots_dir}")
        
        return recognized_texts
    
    def save_results(self, results: List[Dict], channel_name: str) -> str:
        """
        Сохранение результатов в JSON файл
        
        Args:
            results: Список результатов распознавания
            channel_name: Название канала
            
        Returns:
            Путь к сохраненному файлу
        """
        if not results:
            logger.warning("Нет результатов для сохранения")
            return ""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{channel_name}_recognized_text_{timestamp}.json"
        output_path = self.output_dir / filename
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Результаты сохранены: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении результатов: {e}")
            return ""
    
    def process_channel_videos(self, channel_name: str) -> List[Dict]:
        """
        Обработка всех видео файлов для конкретного канала
        
        Args:
            channel_name: Название канала (RBK или MIR24)
            
        Returns:
            Список всех распознанных текстов
        """
        logger.info(f"Обработка видео для канала: {channel_name}")
        
        # Ищем видео файлы в папке канала
        channel_dir = self.video_dir / channel_name
        if not channel_dir.exists():
            logger.warning(f"Папка канала не найдена: {channel_dir}")
            return []
        
        video_files = list(channel_dir.glob("*.mp4"))
        
        if not video_files:
            logger.warning(f"Не найдены видео файлы для канала {channel_name} в {channel_dir}")
            return []
        
        logger.info(f"Найдено {len(video_files)} видео файлов для канала {channel_name}")
        
        all_results = []
        
        for video_file in video_files:
            try:
                logger.info(f"Обработка файла: {video_file.name}")
                results = self.process_video(video_file, channel_name)
                all_results.extend(results)
                
                # Сохраняем промежуточные результаты
                if results:
                    self.save_results(results, f"{channel_name}_{video_file.stem}")
                    
            except Exception as e:
                logger.error(f"Ошибка при обработке {video_file}: {e}")
        
        # Сохраняем общие результаты
        if all_results:
            self.save_results(all_results, channel_name)
        
        return all_results
    
    def process_all_channels(self) -> Dict[str, List[Dict]]:
        """
        Обработка видео для всех каналов
        
        Returns:
            Словарь с результатами по каналам
        """
        logger.info("Начало обработки всех каналов")
        
        results = {}
        
        for channel in ['RBK', 'MIR24']:
            try:
                channel_results = self.process_channel_videos(channel)
                results[channel] = channel_results
                
                logger.info(f"Канал {channel}: распознано {len(channel_results)} текстов")
                
            except Exception as e:
                logger.error(f"Ошибка при обработке канала {channel}: {e}")
                results[channel] = []
        
        return results

class TextAnalyzer:
    """Класс для анализа распознанного текста"""
    
    def __init__(self, input_dir: str = "recognized_text", output_dir: str = "analysis_results"):
        """
        Инициализация анализатора
        
        Args:
            input_dir: Директория с JSON файлами результатов
            output_dir: Директория для сохранения анализа
        """
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def load_results(self, file_pattern: str = "*.json") -> List[Dict]:
        """
        Загрузка результатов из JSON файлов
        
        Args:
            file_pattern: Паттерн для поиска файлов
            
        Returns:
            Список всех результатов
        """
        results = []
        
        for file_path in self.input_dir.glob(file_pattern):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        results.extend(data)
                    else:
                        results.append(data)
                        
                logger.info(f"Загружен файл: {file_path}")
                
            except Exception as e:
                logger.error(f"Ошибка при загрузке {file_path}: {e}")
        
        logger.info(f"Всего загружено {len(results)} результатов")
        return results
    
    def deduplicate_texts(self, results: List[Dict], similarity_threshold: float = 0.8) -> List[Dict]:
        """
        Удаление дубликатов и похожих текстов
        
        Args:
            results: Список результатов
            similarity_threshold: Порог схожести для удаления дубликатов
            
        Returns:
            Список уникальных результатов
        """
        if not results:
            return []
        
        # Группируем по каналам
        channel_groups = {}
        for result in results:
            channel = result.get('channel', 'Unknown')
            if channel not in channel_groups:
                channel_groups[channel] = []
            channel_groups[channel].append(result)
        
        unique_results = []
        
        for channel, channel_results in channel_groups.items():
            # Сортируем по времени
            channel_results.sort(key=lambda x: x.get('timestamp', 0))
            
            # Удаляем дубликаты
            seen_texts = set()
            channel_unique = []
            
            for result in channel_results:
                text = result.get('text', '').strip().lower()
                
                # Проверяем на точные дубликаты
                if text in seen_texts:
                    continue
                
                # Проверяем на похожие тексты
                is_similar = False
                for seen_text in seen_texts:
                    # Используем функцию из VideoTextRecognizer
                    similarity = self._calculate_similarity_simple(text, seen_text)
                    if similarity > similarity_threshold:
                        is_similar = True
                        break
                
                if not is_similar:
                    seen_texts.add(text)
                    channel_unique.append(result)
            
            unique_results.extend(channel_unique)
            logger.info(f"Канал {channel}: {len(channel_results)} -> {len(channel_unique)} уникальных")
        
        return unique_results
    
    def _calculate_similarity_simple(self, text1: str, text2: str) -> float:
        """
        Простое вычисление схожести между двумя текстами на основе общих слов
        
        Args:
            text1: Первый текст
            text2: Второй текст
            
        Returns:
            Коэффициент схожести (0-1)
        """
        if not text1 or not text2:
            return 0.0
        
        # Простая реализация на основе общих слов
        words1 = set(re.findall(r'\w+', text1.lower()))
        words2 = set(re.findall(r'\w+', text2.lower()))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union)
    
    def filter_by_keywords(self, results: List[Dict], keywords: List[str]) -> List[Dict]:
        """
        Фильтрация результатов по ключевым словам
        
        Args:
            results: Список результатов
            keywords: Список ключевых слов
            
        Returns:
            Отфильтрованные результаты
        """
        if not keywords:
            return results
        
        filtered = []
        keywords_lower = [kw.lower() for kw in keywords]
        
        for result in results:
            text = result.get('text', '').lower()
            if any(kw in text for kw in keywords_lower):
                filtered.append(result)
        
        logger.info(f"Фильтрация по ключевым словам: {len(results)} -> {len(filtered)}")
        return filtered
    
    def create_statistics(self, results: List[Dict]) -> Dict:
        """
        Создание статистики по результатам
        
        Args:
            results: Список результатов
            
        Returns:
            Словарь со статистикой
        """
        if not results:
            return {}
        
        # Статистика по каналам
        channel_stats = {}
        method_stats = {}
        keyword_stats = {}
        
        for result in results:
            channel = result.get('channel', 'Unknown')
            method = result.get('recognition_method', 'Unknown')
            keywords = result.get('found_keywords', [])
            
            # Статистика по каналам
            if channel not in channel_stats:
                channel_stats[channel] = 0
            channel_stats[channel] += 1
            
            # Статистика по методам
            if method not in method_stats:
                method_stats[method] = 0
            method_stats[method] += 1
            
            # Статистика по ключевым словам
            for keyword in keywords:
                if keyword not in keyword_stats:
                    keyword_stats[keyword] = 0
                keyword_stats[keyword] += 1
        
        # Общая статистика
        total_texts = len(results)
        unique_channels = len(channel_stats)
        unique_methods = len(method_stats)
        unique_keywords = len(keyword_stats)
        
        # Средняя длина текста
        avg_text_length = sum(len(result.get('text', '')) for result in results) / total_texts if total_texts > 0 else 0
        
        # Средняя уверенность
        confidences = [result.get('confidence', 0) for result in results if result.get('confidence')]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        statistics = {
            'total_texts': total_texts,
            'unique_channels': unique_channels,
            'unique_methods': unique_methods,
            'unique_keywords': unique_keywords,
            'avg_text_length': round(avg_text_length, 2),
            'avg_confidence': round(avg_confidence, 3),
            'channel_stats': channel_stats,
            'method_stats': method_stats,
            'keyword_stats': keyword_stats
        }
        
        return statistics
    
    def export_to_excel(self, results: List[Dict], filename: str = None) -> str:
        """
        Экспорт результатов в Excel
        
        Args:
            results: Список результатов
            filename: Имя файла (если None, генерируется автоматически)
            
        Returns:
            Путь к созданному файлу
        """
        if not results:
            logger.warning("Нет результатов для экспорта в Excel")
            return ""
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recognized_texts_{timestamp}.xlsx"
        
        output_path = self.output_dir / filename
        
        try:
            # Подготавливаем данные для Excel
            excel_data = []
            for result in results:
                excel_data.append({
                    'Channel': result.get('channel', ''),
                    'Video File': result.get('video_file', ''),
                    'Text': result.get('text', ''),
                    'Recognition Method': result.get('recognition_method', ''),
                    'Confidence': result.get('confidence', 0),
                    'Found Keywords': ', '.join(result.get('found_keywords', [])),
                    'DateTime': result.get('datetime', ''),
                    'Screenshot Count': result.get('screenshot_count', 0)
                })
            
            # Создаем DataFrame и сохраняем
            df = pd.DataFrame(excel_data)
            df.to_excel(output_path, index=False, engine='openpyxl')
            
            logger.info(f"Результаты экспортированы в Excel: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Ошибка при экспорте в Excel: {e}")
            return ""
    
    def export_to_csv(self, results: List[Dict], filename: str = None) -> str:
        """
        Экспорт результатов в CSV
        
        Args:
            results: Список результатов
            filename: Имя файла (если None, генерируется автоматически)
            
        Returns:
            Путь к созданному файлу
        """
        if not results:
            logger.warning("Нет результатов для экспорта в CSV")
            return ""
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recognized_texts_{timestamp}.csv"
        
        output_path = self.output_dir / filename
        
        try:
            # Подготавливаем данные для CSV
            csv_data = []
            for result in results:
                csv_data.append({
                    'Channel': result.get('channel', ''),
                    'Video File': result.get('video_file', ''),
                    'Text': result.get('text', ''),
                    'Recognition Method': result.get('recognition_method', ''),
                    'Confidence': result.get('confidence', 0),
                    'Found Keywords': ', '.join(result.get('found_keywords', [])),
                    'DateTime': result.get('datetime', ''),
                    'Screenshot Count': result.get('screenshot_count', 0)
                })
            
            # Создаем DataFrame и сохраняем
            df = pd.DataFrame(csv_data)
            df.to_csv(output_path, index=False, encoding='utf-8')
            
            logger.info(f"Результаты экспортированы в CSV: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Ошибка при экспорте в CSV: {e}")
            return ""
    
    def generate_report(self, results: List[Dict]) -> str:
        """
        Генерация отчета по результатам
        
        Args:
            results: Список результатов
            
        Returns:
            Путь к созданному отчету
        """
        if not results:
            logger.warning("Нет результатов для генерации отчета")
            return ""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_dir / f"analysis_report_{timestamp}.txt"
        
        try:
            # Создаем статистику
            stats = self.create_statistics(results)
            
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write("=== ОТЧЕТ ПО РАСПОЗНАВАНИЮ ТЕКСТА ===\n")
                f.write(f"Дата создания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Всего текстов: {stats.get('total_texts', 0)}\n")
                f.write(f"Каналов: {stats.get('unique_channels', 0)}\n")
                f.write(f"Методов распознавания: {stats.get('unique_methods', 0)}\n")
                f.write(f"Уникальных ключевых слов: {stats.get('unique_keywords', 0)}\n")
                f.write(f"Средняя длина текста: {stats.get('avg_text_length', 0)} символов\n")
                f.write(f"Средняя уверенность: {stats.get('avg_confidence', 0)}\n\n")
                
                # Статистика по каналам
                f.write("=== СТАТИСТИКА ПО КАНАЛАМ ===\n")
                for channel, count in stats.get('channel_stats', {}).items():
                    f.write(f"{channel}: {count} текстов\n")
                f.write("\n")
                
                # Статистика по методам
                f.write("=== СТАТИСТИКА ПО МЕТОДАМ ===\n")
                for method, count in stats.get('method_stats', {}).items():
                    f.write(f"{method}: {count} текстов\n")
                f.write("\n")
                
                # Статистика по ключевым словам
                f.write("=== СТАТИСТИКА ПО КЛЮЧЕВЫМ СЛОВАМ ===\n")
                for keyword, count in stats.get('keyword_stats', {}).items():
                    f.write(f"{keyword}: {count} упоминаний\n")
                f.write("\n")
                
                # Примеры текстов
                f.write("=== ПРИМЕРЫ РАСПОЗНАННЫХ ТЕКСТОВ ===\n")
                for i, result in enumerate(results[:10]):  # Первые 10 текстов
                    f.write(f"{i+1}. [{result.get('channel', 'Unknown')}] {result.get('text', '')[:100]}...\n")
            
            logger.info(f"Отчет создан: {report_path}")
            return str(report_path)
            
        except Exception as e:
            logger.error(f"Ошибка при создании отчета: {e}")
            return ""

def main():
    """Основная функция для тестирования"""
    recognizer = VideoTextRecognizer()
    
    # Обработка всех каналов
    results = recognizer.process_all_channels()
    
    # Вывод статистики
    print("\n=== Статистика распознавания ===")
    for channel, texts in results.items():
        print(f"{channel}: {len(texts)} текстов")
        
        if texts:
            print(f"  Примеры:")
            for i, text_info in enumerate(texts[:3]):
                print(f"    {i+1}. [{text_info['recognition_method']}] {text_info['text'][:50]}...")

    # Анализ результатов
    analyzer = TextAnalyzer()
    analyzed_results = analyzer.load_results()
    analyzed_results = analyzer.deduplicate_texts(analyzed_results)
    analyzed_results = analyzer.filter_by_keywords(analyzed_results, recognizer.keywords)
    statistics = analyzer.create_statistics(analyzed_results)
    analyzer.export_to_excel(analyzed_results)
    analyzer.export_to_csv(analyzed_results)
    analyzer.generate_report(analyzed_results)

if __name__ == "__main__":
    main() 