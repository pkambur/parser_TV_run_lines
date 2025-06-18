import os
import cv2
import numpy as np
from datetime import datetime

def capture_screenshot_opencv(stream_url, output_dir, crop_params=None, fps_interval=1/14):
    """
    Создание скриншота из видеопотока с использованием OpenCV.
    
    Args:
        stream_url (str): URL видеопотока
        output_dir (str): Директория для сохранения скриншотов
        crop_params (str): Параметры обрезки в формате "crop=width:height:x:y"
        fps_interval (float): Интервал между скриншотами в секундах
    """
    try:
        # Создаем директорию если её нет
        os.makedirs(output_dir, exist_ok=True)
        
        # Открываем видеопоток
        cap = cv2.VideoCapture(stream_url)
        
        if not cap.isOpened():
            print(f"Не удалось открыть видеопоток: {stream_url}")
            return False
        
        # Читаем кадр
        ret, frame = cap.read()
        
        if not ret or frame is None:
            print("Не удалось прочитать кадр из потока")
            cap.release()
            return False
        
        # Применяем обрезку если указаны параметры
        if crop_params:
            try:
                # Парсим параметры crop (формат: crop=width:height:x:y)
                crop_str = crop_params.replace("crop=", "")
                width, height, x, y = map(int, crop_str.split(":"))
                
                # Проверяем границы
                h, w = frame.shape[:2]
                if x + width > w or y + height > h:
                    print(f"Параметры crop превышают размеры кадра. Используется полный кадр.")
                else:
                    frame = frame[y:y+height, x:x+width]
                    
            except Exception as e:
                print(f"Ошибка при применении crop: {e}")
        
        # Формируем имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(output_dir, f"screenshot_{timestamp}.jpg")
        
        # Сохраняем изображение
        success = cv2.imwrite(output_file, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        
        # Освобождаем ресурсы
        cap.release()
        
        if success:
            print(f"Скриншот сохранен: {output_file}")
            return True
        else:
            print("Не удалось сохранить скриншот")
            return False
            
    except Exception as e:
        print(f"Ошибка при создании скриншота: {e}")
        return False

if __name__ == "__main__":
    # Пример использования
    url_m3u8 = "https://e2-online-video.rbc.ru/online2/rbctvhd_1080p/index.m3u8?e=e2&t=Izzi0I"
    output_dir = "screenshots"
    crop_params = "crop=1474:50:353:958"
    
    # Создаем скриншот
    capture_screenshot_opencv(url_m3u8, output_dir, crop_params)