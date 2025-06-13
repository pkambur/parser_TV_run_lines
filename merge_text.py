import pytesseract
from PIL import Image
import os
from datetime import datetime
import re
import numpy as np
import cv2
import traceback

def extract_timestamp(filename):
    try:
        match = re.search(r'(\d{8}_\d{6})', filename)
        if match:
            timestamp_str = match.group(1)
            return datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
        return None
    except Exception:
        return None

def preprocess_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)
    gray = cv2.GaussianBlur(gray, (3,3), 0)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                   cv2.THRESH_BINARY, 11, 2)
    scale = 2
    thresh = cv2.resize(thresh, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return thresh

def extract_text(image):
    processed = preprocess_image(image)
    pil_image = Image.fromarray(processed)
    custom_config = '--oem 3 --psm 6'
    text = pytesseract.image_to_string(pil_image, lang='rus', config=custom_config)
    return text.strip()

def extract_text_and_boxes(image_path):
    image = cv2.imread(image_path)
    if image is None:
        print(f"Ошибка: не удалось загрузить {image_path}")
        return None, None, None
    processed = preprocess_image(image)
    pil_image = Image.fromarray(processed)
    custom_config = '--oem 3 --psm 6'
    data = pytesseract.image_to_data(pil_image, lang='rus', config=custom_config, output_type=pytesseract.Output.DICT)
    text = ""
    boxes = []
    scale = 2
    for i in range(len(data['text'])):
        if int(data['conf'][i]) > 70:
            text += data['text'][i] + " "
            boxes.append({
                'text': data['text'][i],
                'box': (
                    int(data['left'][i] / scale),
                    int(data['top'][i] / scale),
                    int(data['width'][i] / scale),
                    int(data['height'][i] / scale)
                )
            })
    return image, text.strip(), boxes

def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def find_overlapping_regions(boxes1, boxes2, threshold=0.5):
    matches = []
    boxes1 = sorted(boxes1, key=lambda x: x['box'][0])
    boxes2 = sorted(boxes2, key=lambda x: x['box'][0])
    y1_min = min(box['box'][1] for box in boxes1)
    y1_max = max(box['box'][1] + box['box'][3] for box in boxes1)
    y2_min = min(box['box'][1] for box in boxes2)
    y2_max = max(box['box'][1] + box['box'][3] for box in boxes2)
    y_overlap = min(y1_max, y2_max) - max(y1_min, y2_min)
    if y_overlap <= 0:
        return []
    for box1 in boxes1:
        best_match = None
        best_score = 0
        for box2 in boxes2:
            y1_start, y1_end = box1['box'][1], box1['box'][1] + box1['box'][3]
            y2_start, y2_end = box2['box'][1], box2['box'][1] + box2['box'][3]
            if y1_end < y2_start or y2_end < y1_start:
                continue
            y_overlap = min(y1_end, y2_end) - max(y1_start, y2_start)
            y_union = max(y1_end, y2_end) - min(y1_start, y2_start)
            y_ratio = y_overlap / y_union if y_union > 0 else 0
            text1 = box1['text'].lower()
            text2 = box2['text'].lower()
            if text1 in text2 or text2 in text1:
                text_score = 1.0
            else:
                max_len = max(len(text1), len(text2))
                if max_len > 0:
                    lev_dist = levenshtein_distance(text1, text2)
                    text_score = 1 - (lev_dist / max_len)
                else:
                    text_score = 0
            score = 0.7 * y_ratio + 0.3 * text_score
            if score > best_score and score > threshold:
                best_score = score
                best_match = box2
        if best_match:
            matches.append((box1, best_match, best_score))
    matches.sort(key=lambda x: x[2], reverse=True)
    filtered_matches = []
    used_boxes = set()
    for match in matches:
        box1, box2, score = match
        box1_id = f"{box1['box'][0]}_{box1['box'][1]}_{box1['box'][2]}_{box1['box'][3]}"
        box2_id = f"{box2['box'][0]}_{box2['box'][1]}_{box2['box'][2]}_{box2['box'][3]}"
        if box1_id not in used_boxes and box2_id not in used_boxes:
            filtered_matches.append(match)
            used_boxes.add(box1_id)
            used_boxes.add(box2_id)
    return filtered_matches

def stitch_images(img1, img2, overlap_boxes):
    if not overlap_boxes:
        return None
    box1, box2, score = overlap_boxes[0]
    x1 = box1['box'][0]
    x2 = box2['box'][0]
    offset = x2 - x1
    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]
    result_h = max(h1, h2)
    result_w = w1 + w2 - abs(offset) if offset >= 0 else w1 + w2
    result = np.zeros((result_h, result_w, 3), dtype=np.uint8)
    result[:h1, :w1] = img1
    if offset >= 0:
        copy_h = min(h2, result_h)
        copy_w = min(w2, result_w - offset)
        result[:copy_h, w1 - offset:w1 - offset + copy_w] = img2[:copy_h, :copy_w]
    else:
        copy_h = min(h2, result_h)
        copy_w = min(w2, result_w - w1)
        result[:copy_h, w1:w1 + copy_w] = img2[:copy_h, :copy_w]
    return result

def process_images(image_paths):
    sorted_paths = sorted(image_paths, key=lambda x: extract_timestamp(os.path.basename(x)) or datetime.max)
    images_data = []
    for path in sorted_paths:
        img, text, boxes = extract_text_and_boxes(path)
        if img is not None and boxes:
            images_data.append({
                'path': path,
                'image': img,
                'text': text,
                'boxes': boxes
            })
    if not images_data:
        raise ValueError("Не удалось обработать ни одно изображение")
    stitch_dir = os.path.join(os.path.dirname(images_data[0]['path']), 'stitched')
    os.makedirs(stitch_dir, exist_ok=True)
    current_stitch = images_data[0]['image']
    stitch_count = 0
    last_successful_stitch = current_stitch
    for i in range(1, len(images_data)):
        overlaps = find_overlapping_regions(
            images_data[i-1]['boxes'],
            images_data[i]['boxes']
        )
        if overlaps:
            new_stitch = stitch_images(current_stitch, images_data[i]['image'], overlaps)
            if new_stitch is not None:
                current_stitch = new_stitch
                last_successful_stitch = current_stitch
            else:
                if last_successful_stitch is not None:
                    stitch_path = os.path.join(stitch_dir, f'stitch_{stitch_count:03d}.jpg')
                    cv2.imwrite(stitch_path, last_successful_stitch)
                    text = extract_text(last_successful_stitch)
                    with open(os.path.join(stitch_dir, f'stitch_{stitch_count:03d}.txt'), 'w', encoding='utf-8') as f:
                        f.write(text)
                    stitch_count += 1
                current_stitch = images_data[i]['image']
                last_successful_stitch = current_stitch
        else:
            if last_successful_stitch is not None:
                stitch_path = os.path.join(stitch_dir, f'stitch_{stitch_count:03d}.jpg')
                cv2.imwrite(stitch_path, last_successful_stitch)
                text = extract_text(last_successful_stitch)
                with open(os.path.join(stitch_dir, f'stitch_{stitch_count:03d}.txt'), 'w', encoding='utf-8') as f:
                    f.write(text)
                stitch_count += 1
            current_stitch = images_data[i]['image']
            last_successful_stitch = current_stitch
    if last_successful_stitch is not None:
        stitch_path = os.path.join(stitch_dir, f'stitch_{stitch_count:03d}.jpg')
        cv2.imwrite(stitch_path, last_successful_stitch)
        text = extract_text(last_successful_stitch)
        with open(os.path.join(stitch_dir, f'stitch_{stitch_count:03d}.txt'), 'w', encoding='utf-8') as f:
            f.write(text)
    return stitch_dir

def get_image_paths(directory):
    """
    Возвращает список путей к изображениям в указанной директории и её поддиректориях.
    """
    supported_extensions = ['.png', '.jpg', '.jpeg']
    image_paths = []
    if not os.path.exists(directory):
        raise FileNotFoundError(f"Директория не найдена: {directory}")
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if any(filename.lower().endswith(ext) for ext in supported_extensions):
                image_paths.append(os.path.join(root, filename))
    if not image_paths:
        raise ValueError(f"В директории {directory} и её поддиректориях нет изображений с поддерживаемыми форматами.")
    return image_paths

def main():
    try:
        directory = r"D:\projects\Lines\tv_running_lines\screenshots\MIR24"
        image_paths = get_image_paths(directory)
        if not image_paths:
            print("Не найдено изображений для обработки")
            return
        print(f"Найдено {len(image_paths)} изображений")
        result_dir = process_images(image_paths)
        if result_dir:
            print(f"\nРезультат сохранен в директорию: {result_dir}")
        else:
            print("Не удалось создать склеенные изображения")
    except Exception as e:
        print(f"Ошибка: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
