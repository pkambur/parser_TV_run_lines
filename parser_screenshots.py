import os
import easyocr
import psycopg2
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

debug = True
directory = "screenshots"
DB_dbname = "postgres"
DB_user = "postgres"
DB_password = "Kambur_339"
DB_host = "127.0.0.1"
DB_port = "5432"

def get_all_files(directory, reader):
    """
    Обходит указанный каталог и возвращает список полных путей ко всем файлам.

    :param directory: Путь к каталогу для обхода
    :param reader: Экземпляр easyocr.Reader
    """
    tasks = []
    if debug:
        print(f"Обходим каталог: {directory}")
    with ThreadPoolExecutor() as executor:
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_cur = os.path.join(root, file)
                tv_channel = os.path.basename(root)  # Название папки телеканала
                if debug:
                    print(f"Текущий файл: {file_cur}, телеканал: {tv_channel}")
                tasks.append(executor.submit(screenshot_parse, file_cur, tv_channel, reader))


def screenshot_parse(file_cur, tv_channel, reader):
    """
    Распознаем текст на картинке и добавляем запись в базу данных

    :param file_cur: Путь к файлу скриншота
    :param tv_channel: Название телеканала (папка)
    :param reader: Экземпляр easyocr.Reader
    """
    if debug:
        print(f"Распознаем скриншот: {file_cur}")

    # Распознавание текста на изображении
    result = reader.readtext(file_cur)
    text = ' '.join([detection[1] for detection in result]).strip()

    if debug:
        print(f"Получили текст: {text}")

    # Регулярное выражение для проверки текста (только русские и английские буквы, цифры, пробелы и знаки пунктуации)
    valid_text_pattern = re.compile(r'^[a-zA-Zа-яА-Я0-9,.!?\-\s]+$')

    # Проверяем текст на валидность
    if valid_text_pattern.match(text):
        # Дополнительная проверка: текст не должен быть случайным набором символов (например, слишком короткий или бессмысленный)
        meaningful_text_pattern = re.compile(r'[a-zA-Zа-яА-Я]{2,}')  # Должны быть хотя бы 2 подряд идущие буквы
        if meaningful_text_pattern.search(text):
            if debug:
                print("Текст прошел проверку и будет добавлен в БД.")
            insert_into_db(text, tv_channel)
        else:
            if debug:
                print("Текст не содержит осмысленных слов и не будет добавлен в БД.")
    else:
        if debug:
            print("Текст содержит недопустимые символы и не будет добавлен в БД.")

    insert_into_db(text, tv_channel)

def insert_into_db(text, tv_channel):
    """
    Вставляет строку в таблицу public.running_strings

    :param text: Текст для вставки
    :param tv_channel: Название телеканала
    """
    try:
        conn = psycopg2.connect(dbname=DB_dbname, user=DB_user, password=DB_password, host=DB_host, port=DB_port)
        cur = conn.cursor()
        insert_query = """
        INSERT INTO public.running_strings (time_c, text, tv_channel)
        VALUES (%s, %s, %s);
        """
        cur.execute(insert_query, (datetime.now(), text, tv_channel))
        conn.commit()
        if debug:
            print(f"Успешно добавлена запись: {text}, телеканал: {tv_channel}")
    except (Exception, psycopg2.Error) as error:
        if debug:
            print("Ошибка при работе с PostgreSQL", error)
    finally:
        if conn:
            cur.close()
            conn.close()

# Создаем один экземпляр easyocr.Reader
reader = easyocr.Reader(['ru'], gpu=True)

# Запускаем обработку файлов
get_all_files(directory, reader)
