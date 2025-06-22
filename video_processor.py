import os
import json
import subprocess
import logging
from pathlib import Path
import sys
from datetime import timedelta, datetime
import requests
from typing import Optional, TYPE_CHECKING, Any
import argparse

if TYPE_CHECKING:
    from natasha import MorphVocab

# Заменяем pymorphy2 на natasha для совместимости с Python 3.12
try:
    from natasha import MorphVocab
except ImportError:
    # Fallback: простая замена без морфологического анализа
    MorphVocab = None

# Предполагается, что telegram_sender.py находится в том же каталоге
try:
    from telegram_sender import send_files
except ImportError:
    # Добавляем текущую директорию в sys.path, если запуск идет из другого места
    sys.path.append(str(Path(__file__).parent))
    from telegram_sender import send_files

# --- Настройка ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Константы ---
VIDEO_SOURCE_DIR = Path("TV_video")
VIDEO_PROCESSED_DIR = VIDEO_SOURCE_DIR / "processed"
KEYWORDS_FILE = Path("keywords.json")
TEMP_DIR = Path("temp_processing")
RECOGNIZED_TEXT_DIR = Path("recognized_text")

# --- Hugging Face API ---
# !!! ВАШ ТОКЕН ДОСТУПА HUGGING FACE !!!
# Получите его здесь: https://huggingface.co/settings/tokens
HF_API_TOKEN = "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" 
# Используем модель Whisper для транскрибации аудио
API_URL = "https://api-inference.huggingface.co/models/openai/whisper-large-v3"

# Создаем необходимые директории
VIDEO_PROCESSED_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)
RECOGNIZED_TEXT_DIR.mkdir(exist_ok=True)

# --- Основная логика ---

def transcribe_audio_with_segments(audio_path: Path) -> list:
    """
    Преобразует аудио в текст с временными метками для каждого сегмента,
    используя Hugging Face Inference API с моделью Whisper.
    """
    logger.info(f"Запуск транскрибации для {audio_path.name} через Hugging Face API...")

    if not HF_API_TOKEN or "hf_YOUR_TOKEN_HERE" in HF_API_TOKEN:
        logger.error("Токен Hugging Face API не указан. Укажите его в переменной HF_API_TOKEN.")
        return []

    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    
    with open(audio_path, "rb") as f:
        data = f.read()

    # Запрашиваем тайм-коды для каждого сегмента (чанка)
    params = {"return_timestamps": "chunk"}
    
    try:
        response = requests.post(API_URL, headers=headers, data=data, params=params, timeout=300)
        response.raise_for_status()  # Вызовет исключение для кодов 4xx/5xx
        
        result = response.json()
        logger.info("Транскрибация через API успешно завершена.")

        if 'chunks' not in result:
            logger.warning("Ответ API не содержит сегментов ('chunks').")
            return []

        # Преобразуем формат ответа API в наш внутренний формат
        # Формат ответа Whisper: {'chunks': [{'timestamp': [start, end], 'text': '...'}, ...]}
        segments = [
            {'start': chunk['timestamp'][0], 'end': chunk['timestamp'][1], 'text': chunk['text']}
            for chunk in result.get('chunks', []) if chunk.get('timestamp')
        ]
        
        return segments

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при обращении к Hugging Face API: {e}")
        if e.response is not None:
            logger.error(f"Тело ответа API: {e.response.text}")
        return []


def get_normalized_keywords(morph: Any) -> set:
    """Загружает и нормализует ключевые слова из keywords.json."""
    if not KEYWORDS_FILE.exists():
        logger.error(f"Файл ключевых слов не найден: {KEYWORDS_FILE}")
        return set()
    
    with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
        keywords = json.load(f)
    
    if morph is None:
        # Fallback: используем ключевые слова как есть
        normalized_keywords = set(keywords)
        logger.info(f"Загружено {len(normalized_keywords)} ключевых слов (без морфологического анализа).")
        return normalized_keywords
    
    # Приводим все ключевые слова к нормальной форме с помощью natasha
    normalized_keywords = set()
    for kw in keywords:
        try:
            # Получаем нормальную форму слова
            normalized = morph.normalize(kw)
            if normalized:
                normalized_keywords.add(normalized)
            else:
                normalized_keywords.add(kw.lower())  # Fallback к нижнему регистру
        except Exception as e:
            logger.warning(f"Ошибка нормализации слова '{kw}': {e}")
            normalized_keywords.add(kw.lower())  # Fallback к нижнему регистру
    
    logger.info(f"Загружено и нормализовано {len(normalized_keywords)} ключевых слов.")
    return normalized_keywords


def find_segments_with_keywords(segments: list, keywords: set, morph: Any) -> list:
    """Находит сегменты, текст которых содержит ключевые слова."""
    found_segments = []
    for segment in segments:
        text = segment.get('text', '').lower()
        if not text:
            continue
            
        # Проверяем на совпадение ключевых слов
        found = False
        if morph is None:
            # Простая проверка без морфологического анализа
            for keyword in keywords:
                if keyword.lower() in text:
                    logger.info(f"Найдено ключевое слово '{keyword}' в сегменте: \"{text[:50]}...\"")
                    found_segments.append(segment)
                    found = True
                    break
        else:
            # Нормализуем каждое слово в тексте сегмента и проверяем на совпадение
            words_in_text = text.split()
            for word in words_in_text:
                try:
                    normalized_word = morph.normalize(word)
                    if normalized_word and normalized_word in keywords:
                        logger.info(f"Найдено ключевое слово '{normalized_word}' в сегменте: \"{text[:50]}...\"")
                        found_segments.append(segment)
                        found = True
                        break
                except Exception as e:
                    logger.warning(f"Ошибка нормализации слова '{word}': {e}")
                    # Fallback: проверяем исходное слово
                    if word in keywords:
                        logger.info(f"Найдено ключевое слово '{word}' в сегменте: \"{text[:50]}...\"")
                        found_segments.append(segment)
                        found = True
                        break
        
        if found:
            continue
            
    return found_segments


def extract_audio(video_path: Path, temp_audio_path: Path) -> bool:
    """Извлекает аудиодорожку из видео с помощью ffmpeg."""
    logger.info(f"Извлечение аудио из {video_path.name}...")
    command = [
        'ffmpeg', '-y',
        '-i', str(video_path),
        '-q:a', '0',      # Максимальное качество
        '-map', 'a',       # Выбирать только аудио
        str(temp_audio_path)
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
        logger.info("Аудио успешно извлечено.")
        return True
    except FileNotFoundError:
        logger.error("ffmpeg не найден. Убедитесь, что он установлен и доступен в системном PATH.")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при извлечении аудио: {e.stderr}")
        return False


def cut_video_segment(original_video: Path, segment: dict, output_path: Path) -> bool:
    """Вырезает фрагмент видео по временным меткам с помощью ffmpeg."""
    start_time = segment['start']
    end_time = segment['end']
    duration = end_time - start_time
    
    logger.info(f"Вырезка сюжета из {original_video.name} с {start_time:.2f} по {end_time:.2f}...")
    command = [
        'ffmpeg', '-y',
        '-ss', str(start_time),   # Время начала
        '-i', str(original_video),
        '-t', str(duration),       # Длительность
        '-c', 'copy',              # Копирование потоков без перекодирования (быстро)
        str(output_path)
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
        logger.info(f"Сюжет успешно вырезан и сохранен в {output_path.name}")
        return True
    except FileNotFoundError:
        logger.error("ffmpeg не найден.")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при вырезке видео: {e.stderr}")
        return False


def save_results_as_txt(results: list, channel_name: str, video_file: str = None) -> str:
    """
    Сохраняет результаты распознавания в txt-файл в папке recognized_text.
    Один файл на видео, с таймкодами и текстом.
    """
    if not results:
        logger.warning("Нет результатов для сохранения в txt")
        return ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{channel_name}_recognized_text_{timestamp}"
    if video_file:
        base_name = f"{channel_name}_{Path(video_file).stem}_recognized_text_{timestamp}"
    output_path = RECOGNIZED_TEXT_DIR / f"{base_name}.txt"
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, res in enumerate(results, 1):
                start = res.get('start') or res.get('start_time')
                end = res.get('end') or res.get('end_time')
                text = res.get('text', '')
                f.write(f"Сюжет {i}\n")
                if start is not None and end is not None:
                    f.write(f"Время: {start:.2f} - {end:.2f} сек\n")
                f.write(f"Текст: {text}\n\n")
        logger.info(f"Результаты сохранены в txt: {output_path}")
        return str(output_path)
    except Exception as e:
        logger.error(f"Ошибка при сохранении результатов в txt: {e}")
        return ""


def process_all_videos():
    """Основной цикл обработки всех видео."""
    logger.info("Запуск процесса обработки видеосюжетов...")
    morph = MorphVocab()
    keywords = get_normalized_keywords(morph)
    
    if not keywords:
        logger.warning("Нет ключевых слов для поиска. Процесс завершен.")
        return

    for channel_dir in VIDEO_SOURCE_DIR.iterdir():
        if not channel_dir.is_dir() or channel_dir.name == "processed":
            continue

        channel_name = channel_dir.name
        logger.info(f"Обработка канала: {channel_name}")

        for video_file in channel_dir.glob("*.mp4"):
            logger.info(f"--- Начинаю обработку файла: {video_file.name} ---")
            
            # 1. Извлечь аудио
            temp_audio = TEMP_DIR / f"{video_file.stem}.mp3"
            if not extract_audio(video_file, temp_audio):
                continue

            # 2. Транскрибировать аудио
            segments = transcribe_audio_with_segments(temp_audio)
            
            # 3. Найти сегменты с ключевыми словами
            found_segments = find_segments_with_keywords(segments, keywords, morph)

            # 4. Вырезать, отправить и очистить
            if found_segments:
                logger.info(f"Найдено {len(found_segments)} сюжетов с ключевыми словами в {video_file.name}")
                for i, segment in enumerate(found_segments):
                    cut_video_path = TEMP_DIR / f"{video_file.stem}_сюжет_{i+1}.mp4"
                    if cut_video_segment(video_file, segment, cut_video_path):
                        # Формируем сообщение для Telegram
                        start_td = timedelta(seconds=int(segment['start']))
                        end_td = timedelta(seconds=int(segment['end']))
                        caption = (
                            f"📺 Телеканал: {channel_name}\n"
                            f"🕒 Время сюжета: {start_td} - {end_td}\n\n"
                            f"📜 Распознанный текст:\n{segment['text']}"
                        )
                        
                        logger.info("Отправка сюжета в Telegram...")
                        if send_files([str(cut_video_path)], caption=caption):
                            logger.info("Сюжет успешно отправлен.")
                        else:
                            logger.error("Не удалось отправить сюжет.")
                        
                        # Удаляем временный вырезанный фрагмент
                        cut_video_path.unlink()
                # Сохраняем текстовые результаты
                save_results_as_txt(found_segments, channel_name, video_file.name)
            else:
                logger.info(f"В файле {video_file.name} сюжетов с ключевыми словами не найдено.")

            # Удаляем временный аудиофайл
            temp_audio.unlink()
            
            # Перемещаем обработанное видео
            processed_channel_dir = VIDEO_PROCESSED_DIR / channel_name
            processed_channel_dir.mkdir(exist_ok=True)
            video_file.rename(processed_channel_dir / video_file.name)
            logger.info(f"--- Файл {video_file.name} обработан и перемещен. ---\n")

    logger.info("Все видеосюжеты обработаны.")


def process_single_video(video_path_str, channel_name):
    """Обработка одного видеофайла для указанного канала."""
    logger.info(f"Обработка одного видео: {video_path_str} для канала {channel_name}")
    video_path = Path(video_path_str)
    if not video_path.exists():
        logger.error(f"Файл не найден: {video_path}")
        return
    try:
        morph = MorphVocab() if 'MorphVocab' in globals() and MorphVocab else None
        keywords = get_normalized_keywords(morph)
        temp_audio = TEMP_DIR / f"{video_path.stem}.mp3"
        if not extract_audio(video_path, temp_audio):
            return
        segments = transcribe_audio_with_segments(temp_audio)
        found_segments = find_segments_with_keywords(segments, keywords, morph)
        if found_segments:
            logger.info(f"Найдено {len(found_segments)} сюжетов с ключевыми словами в {video_path.name}")
            for i, segment in enumerate(found_segments):
                cut_video_path = TEMP_DIR / f"{video_path.stem}_сюжет_{i+1}.mp4"
                if cut_video_segment(video_path, segment, cut_video_path):
                    start_td = timedelta(seconds=int(segment['start']))
                    end_td = timedelta(seconds=int(segment['end']))
                    caption = (
                        f"📺 Телеканал: {channel_name}\n"
                        f"🕒 Время сюжета: {start_td} - {end_td}\n\n"
                        f"📜 Распознанный текст:\n{segment['text']}"
                    )
                    logger.info("Отправка сюжета в Telegram...")
                    if send_files([str(cut_video_path)], caption=caption):
                        logger.info("Сюжет успешно отправлен.")
                    else:
                        logger.error("Не удалось отправить сюжет.")
                    cut_video_path.unlink()
            # Сохраняем текстовые результаты
            save_results_as_txt(found_segments, channel_name, video_path.name)
        else:
            logger.info(f"В файле {video_path.name} сюжетов с ключевыми словами не найдено.")
        temp_audio.unlink()
        # Перемещаем обработанное видео
        processed_channel_dir = VIDEO_PROCESSED_DIR / channel_name
        processed_channel_dir.mkdir(exist_ok=True)
        video_path.rename(processed_channel_dir / video_path.name)
        logger.info(f"--- Файл {video_path.name} обработан и перемещен. ---\n")
    except Exception as e:
        logger.critical(f"Ошибка при обработке одного видео: {e}", exc_info=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Video processor for TV news segments.")
    parser.add_argument('--single', nargs=2, metavar=('VIDEO_PATH', 'CHANNEL_NAME'), help='Обработать только один видеофайл для указанного канала')
    parser.add_argument('--check-keywords-only', action='store_true', help='Только проверить наличие ключевых слов, не отправлять и не сохранять')
    args = parser.parse_args()

    if args.single:
        video_path_str, channel_name = args.single
        if args.check_keywords_only:
            # Только проверка на ключевые слова, ничего не сохраняем и не отправляем
            video_path = Path(video_path_str)
            if not video_path.exists():
                sys.exit(1)
            try:
                morph = MorphVocab() if 'MorphVocab' in globals() and MorphVocab else None
                keywords = get_normalized_keywords(morph)
                temp_audio = TEMP_DIR / f"{video_path.stem}.mp3"
                if not extract_audio(video_path, temp_audio):
                    sys.exit(1)
                segments = transcribe_audio_with_segments(temp_audio)
                found_segments = find_segments_with_keywords(segments, keywords, morph)
                temp_audio.unlink(missing_ok=True)
                if found_segments:
                    print("FOUND_KEYWORDS")
                    sys.exit(0)
                else:
                    sys.exit(2)
            except Exception as e:
                logger.critical(f"Ошибка при быстрой проверке ключевых слов: {e}", exc_info=True)
                sys.exit(1)
        else:
            process_single_video(video_path_str, channel_name)
    else:
        try:
            process_all_videos()
        except Exception as e:
            logger.critical(f"Произошла критическая ошибка в процессе обработки видео: {e}", exc_info=True) 