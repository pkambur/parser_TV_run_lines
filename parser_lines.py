import os
import time
import json
import logging
import threading
from datetime import datetime
import subprocess
from utils import setup_logging
import cv2
import numpy as np

# Инициализация логирования
logger = setup_logging()

# Глобальные переменные для управления мониторингом
monitoring_threads = []
force_capture = False
stop_monitoring = False

def load_channels():
    """Загрузка конфигурации каналов из JSON файла."""
    try:
        with open('channels.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации каналов: {e}")
        return {}

def parse_interval(interval_str):
    """Парсит строку интервала (например, '1/7') и возвращает количество секунд."""
    try:
        if not interval_str or '/' not in interval_str:
            logger.warning(f"Некорректный формат интервала: {interval_str}. Используется 10 секунд.")
            return 10
        numerator, denominator = interval_str.split('/')
        interval = int(denominator) / int(numerator)
        if interval <= 0:
            raise ValueError("Интервал должен быть положительным")
        return interval
    except (ValueError, TypeError) as e:
        logger.error(f"Ошибка парсинга интервала {interval_str}: {e}. Используется 10 секунд.")
        return 10

def capture_screenshot(channel_name, stream_url, output_dir, crop_params=None):
    """Создание скриншота из видеопотока с использованием OpenCV."""
    try:
        # Формируем имя файла с текущей датой и временем
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(output_dir, f"{channel_name}_{timestamp}.jpg")
        
        # Открываем видеопоток
        cap = cv2.VideoCapture(stream_url)
        
        if not cap.isOpened():
            logger.error(f"Не удалось открыть видеопоток для {channel_name}: {stream_url}")
            return False
        
        # Читаем кадр
        ret, frame = cap.read()
        
        if not ret or frame is None:
            logger.error(f"Не удалось прочитать кадр из потока для {channel_name}")
            cap.release()
            return False
        
        # Применяем обрезку если указаны параметры
        if crop_params:
            try:
                # Парсим параметры crop (формат: crop=width:height:x:y)
                crop_str = crop_params.replace("crop=", "")
                width, height, x, y = map(int, crop_str.split(":"))
                h, w = frame.shape[:2]
                if x + width > w or y + height > h:
                    logger.warning(f"Параметры crop для {channel_name} превышают размеры кадра. Используется полный кадр.")
                else:
                    frame = frame[y:y+height, x:x+width]
            except Exception as e:
                logger.error(f"Ошибка при применении crop для {channel_name}: {e}. Используется полный кадр.")
        else:
            logger.info(f"Для канала {channel_name} не указан crop. Используется полный кадр.")
        
        # Сохраняем изображение
        success = cv2.imwrite(output_file, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        
        # Освобождаем ресурсы
        cap.release()
        
        if success:
            logger.info(f"Скриншот создан: {output_file}")
            return True
        else:
            logger.error(f"Не удалось сохранить скриншот для {channel_name}")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при создании скриншота для {channel_name}: {e}")
        return False

def monitor_channel(channel_name, channel_info):
    """Мониторинг отдельного канала."""
    global force_capture, stop_monitoring
    try:
        # Получаем URL потока из конфигурации
        stream_url = channel_info.get('url')
        if not stream_url:
            logger.error(f"Не указан URL потока для канала {channel_name}")
            return

        # Создаем директорию для скриншотов если её нет
        output_dir = os.path.join('screenshots', channel_name)
        os.makedirs(output_dir, exist_ok=True)
        
        # Получаем параметры обрезки и интервал
        crop_params = channel_info.get('crop')
        interval = parse_interval(channel_info.get('interval', '1/10'))
        
        logger.info(f"Запущен мониторинг канала {channel_name} (URL: {stream_url}, интервал: {interval} сек)")
        
        last_capture_time = None
        
        while not stop_monitoring:
            try:
                current_time = time.time()
                
                # Проверяем флаг принудительного захвата или прошло достаточно времени
                if force_capture or (last_capture_time is None or current_time - last_capture_time >= interval):
                    # Создаем скриншот
                    result = capture_screenshot(channel_name, stream_url, output_dir, crop_params)
                    if result:
                        logger.info(f"Скриншот успешно создан для {channel_name}")
                        last_capture_time = current_time
                    else:
                        logger.error(f"Не удалось создать скриншот для {channel_name}")
                    
                    # Сбрасываем флаг принудительного захвата
                    if force_capture:
                        force_capture = False
                
                # Проверяем флаг остановки каждую секунду
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга канала {channel_name}: {e}")
                if stop_monitoring:
                    break
                time.sleep(5)  # Пауза перед повторной попыткой
                
    except Exception as e:
        logger.error(f"Критическая ошибка при мониторинге канала {channel_name}: {e}")
    finally:
        logger.info(f"Мониторинг канала {channel_name} завершен")

def start_force_capture():
    """Запускает принудительный захват скриншотов для всех каналов."""
    global force_capture
    force_capture = True
    logger.info("Запущен принудительный захват скриншотов")

def stop_force_capture():
    """Останавливает принудительный захват скриншотов."""
    global force_capture
    force_capture = False
    logger.info("Остановлен принудительный захват скриншотов")

def stop_subprocesses():
    """Останавливает все потоки мониторинга."""
    global stop_monitoring
    stop_monitoring = True
    logger.info("Остановка всех потоков мониторинга")
    
    # Ждем завершения всех потоков
    for thread in monitoring_threads:
        if thread.is_alive():
            try:
                thread.join(timeout=5.0)
            except Exception as e:
                logger.error(f"Ошибка при остановке потока {thread.name}: {e}")
    
    # Очищаем список потоков
    monitoring_threads.clear()
    
    # Сбрасываем флаг остановки
    stop_monitoring = False
    logger.info("Все потоки мониторинга остановлены")

def main():
    """Основная функция мониторинга."""
    try:
        # Загружаем конфигурацию каналов
        channels = load_channels()
        if not channels:
            logger.error("Не удалось загрузить конфигурацию каналов")
            return

        # Список каналов для скриншотов
        screenshot_channels = [
            'R24_blue_line', 'R24_white_line', 'M24', '360', 
            'Izvestiya', 'R1', 'Zvezda'
        ]

        # Запускаем мониторинг только для каналов скриншотов
        for channel_name, channel_info in channels.items():
            if channel_name not in screenshot_channels:
                logger.info(f"Пропуск канала {channel_name} (не в списке каналов для скриншотов)")
                continue

            # Проверяем наличие URL
            if not channel_info.get('url'):
                logger.error(f"Пропуск канала {channel_name}: не указан URL потока")
                continue
                
            # Создаем и запускаем поток для канала
            thread = threading.Thread(
                target=monitor_channel,
                args=(channel_name, channel_info),
                name=f"monitor_{channel_name}"
            )
            thread.daemon = True
            thread.start()
            monitoring_threads.append(thread)
            logger.info(f"Запущен мониторинг канала {channel_name}")

        # Ждем завершения всех потоков
        for thread in monitoring_threads:
            thread.join()

    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения работы")
        stop_subprocesses()
    except Exception as e:
        logger.error(f"Ошибка в основном процессе: {e}")
        stop_subprocesses()

# Экспортируем необходимые функции
__all__ = ['main', 'stop_subprocesses', 'start_force_capture', 'stop_force_capture']

if __name__ == "__main__":
    main()