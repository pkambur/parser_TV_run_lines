import os
import pandas as pd
import logging
from difflib import SequenceMatcher
from transformers import T5Tokenizer, T5ForConditionalGeneration

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("merge_text_log.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Загрузка модели T5 (можно заменить на другую, например, Grok, если есть API)
model_name = "t5-small"  # Используем небольшую модель для скорости
tokenizer = T5Tokenizer.from_pretrained(model_name)
model = T5ForConditionalGeneration.from_pretrained(model_name)


# Функция для алгоритмического объединения фрагментов
def merge_fragments(fragments):
    merged = fragments[0]
    for i in range(1, len(fragments)):
        current = fragments[i]
        matcher = SequenceMatcher(None, merged, current)
        match = matcher.find_longest_match(0, len(merged), 0, len(current))

        if match.size > 3:  # Если есть пересечение больше 3 символов
            overlap = merged[match.a:match.a + match.size]
            merged = merged[:match.a] + current
        else:
            merged += " " + current  # Если пересечения нет, просто соединяем
    return merged


# Функция для восстановления текста с помощью T5
def refine_text_with_t5(fragments):
    input_text = "merge fragments: " + " | ".join(fragments)
    inputs = tokenizer(input_text, return_tensors="pt", max_length=512, truncation=True)
    outputs = model.generate(inputs["input_ids"], max_length=512, num_beams=5, early_stopping=True)
    refined_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return refined_text


# Основная функция обработки
def process_channel_text(channel_name, df):
    # Фильтруем строки по каналу и сортируем по времени
    channel_df = df[df["Channel"] == channel_name].sort_values("Timestamp")
    fragments = channel_df["Text"].tolist()

    if not fragments:
        logger.warning(f"Нет данных для канала {channel_name}")
        return None

    # Алгоритмическое объединение
    merged_text = merge_fragments(fragments)
    logger.info(f"Алгоритмически объединённый текст для {channel_name}: {merged_text}")

    # Уточнение с помощью T5
    refined_text = refine_text_with_t5(fragments)
    logger.info(f"Уточнённый текст для {channel_name}: {refined_text}")

    return refined_text


# Загрузка данных и обработка
def main():
    # Чтение CSV с распознанным текстом
    csv_file = "recognized_text.csv"
    if not os.path.exists(csv_file):
        logger.error(f"Файл {csv_file} не найден")
        return

    df = pd.read_csv(csv_file)
    channels = df["Channel"].unique()

    # Словарь для хранения результатов
    results = {"Channel": [], "Merged_Text": []}

    # Обработка каждого канала
    for channel in channels:
        merged_text = process_channel_text(channel, df)
        if merged_text:
            results["Channel"].append(channel)
            results["Merged_Text"].append(merged_text)

    # Сохранение результатов
    result_df = pd.DataFrame(results)
    result_df.to_csv("merged_text.csv", index=False, encoding="utf-8-sig")
    logger.info("Объединённый текст сохранён в merged_text.csv")


if __name__ == "__main__":
    main()