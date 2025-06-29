#!/usr/bin/env python3
"""
Скрипт для проверки конфигурации Telegram Bot и других токенов
"""

import os
import sys
import json
from pathlib import Path

def check_config():
    """Проверяет конфигурацию Telegram Bot и других токенов"""
    print("🔍 Проверка конфигурации токенов...")
    
    # Проверяем переменные окружения
    telegram_token = os.getenv('TELEGRAM_TOKEN')
    telegram_chat_ids = os.getenv('TELEGRAM_CHAT_IDS')
    hf_api_token = os.getenv('HF_API_TOKEN')
    hf_token = os.getenv('HF_TOKEN')
    
    print(f"\n📋 Переменные окружения:")
    print(f"   TELEGRAM_TOKEN: {'✅ Установлен' if telegram_token else '❌ Не установлен'}")
    print(f"   TELEGRAM_CHAT_IDS: {'✅ Установлен' if telegram_chat_ids else '❌ Не установлен'}")
    print(f"   HF_API_TOKEN: {'✅ Установлен' if hf_api_token else '❌ Не установлен'}")
    print(f"   HF_TOKEN: {'✅ Установлен' if hf_token else '❌ Не установлен'}")
    
    # Проверяем файл конфигурации
    config_file = Path('config.json')
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            print(f"\n📄 Файл config.json:")
            print(f"   telegram_token: {'✅ Установлен' if config.get('telegram_token') else '❌ Не установлен'}")
            print(f"   chat_ids: {'✅ Установлен' if config.get('chat_ids') else '❌ Не установлен'}")
            print(f"   hf_api_token: {'✅ Установлен' if config.get('hf_api_token') else '❌ Не установлен'}")
            print(f"   hf_token: {'✅ Установлен' if config.get('hf_token') else '❌ Не установлен'}")
            
            if config.get('telegram_token') and config['telegram_token'] != 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
                print(f"   Telegram токен: {config['telegram_token'][:10]}...")
            else:
                print(f"   ⚠️  Telegram токен не настроен или использует значение по умолчанию")
                
            if config.get('hf_api_token') and config['hf_api_token'] != 'YOUR_HUGGING_FACE_API_TOKEN_HERE':
                print(f"   HF API токен: {config['hf_api_token'][:10]}...")
            else:
                print(f"   ⚠️  HF API токен не настроен или использует значение по умолчанию")
                
            if config.get('hf_token') and config['hf_token'] != 'YOUR_HUGGING_FACE_TOKEN_HERE':
                print(f"   HF токен: {config['hf_token'][:10]}...")
            else:
                print(f"   ⚠️  HF токен не настроен или использует значение по умолчанию")
                
        except Exception as e:
            print(f"   ❌ Ошибка чтения config.json: {e}")
    else:
        print(f"\n📄 Файл config.json: ❌ Не найден")
    
    # Определяем приоритетную конфигурацию
    print(f"\n🎯 Приоритетная конфигурация:")
    if telegram_token:
        print(f"   Telegram токен: {telegram_token[:10]}... (из переменной окружения)")
    elif config_file.exists() and config.get('telegram_token') and config['telegram_token'] != 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
        print(f"   Telegram токен: {config['telegram_token'][:10]}... (из config.json)")
    else:
        print(f"   ❌ Telegram токен не найден")
    
    if telegram_chat_ids:
        try:
            chat_ids = [int(chat_id.strip()) for chat_id in telegram_chat_ids.split(',')]
            print(f"   Chat IDs: {chat_ids} (из переменной окружения)")
        except:
            print(f"   ❌ Ошибка парсинга TELEGRAM_CHAT_IDS")
    elif config_file.exists() and config.get('chat_ids'):
        print(f"   Chat IDs: {config['chat_ids']} (из config.json)")
    else:
        print(f"   ❌ Chat IDs не найдены")
    
    if hf_api_token:
        print(f"   HF API токен: {hf_api_token[:10]}... (из переменной окружения)")
    elif config_file.exists() and config.get('hf_api_token') and config['hf_api_token'] != 'YOUR_HUGGING_FACE_API_TOKEN_HERE':
        print(f"   HF API токен: {config['hf_api_token'][:10]}... (из config.json)")
    else:
        print(f"   ⚠️  HF API токен не найден (опционально)")
    
    if hf_token:
        print(f"   HF токен: {hf_token[:10]}... (из переменной окружения)")
    elif config_file.exists() and config.get('hf_token') and config['hf_token'] != 'YOUR_HUGGING_FACE_TOKEN_HERE':
        print(f"   HF токен: {config['hf_token'][:10]}... (из config.json)")
    else:
        print(f"   ⚠️  HF токен не найден (опционально)")
    
    # Рекомендации
    print(f"\n💡 Рекомендации:")
    if not telegram_token and not (config_file.exists() and config.get('telegram_token') and config['telegram_token'] != 'YOUR_TELEGRAM_BOT_TOKEN_HERE'):
        print(f"   • Установите переменную окружения TELEGRAM_TOKEN")
        print(f"   • Или настройте telegram_token в config.json")
    
    if not telegram_chat_ids and not (config_file.exists() and config.get('chat_ids')):
        print(f"   • Установите переменную окружения TELEGRAM_CHAT_IDS")
        print(f"   • Или настройте chat_ids в config.json")
    
    if not hf_api_token and not (config_file.exists() and config.get('hf_api_token') and config['hf_api_token'] != 'YOUR_HUGGING_FACE_API_TOKEN_HERE'):
        print(f"   • Для улучшенного анализа ключевых слов установите HF_API_TOKEN")
        print(f"   • Или настройте hf_api_token в config.json")
    
    if not hf_token and not (config_file.exists() and config.get('hf_token') and config['hf_token'] != 'YOUR_HUGGING_FACE_TOKEN_HERE'):
        print(f"   • Для дополнительных функций установите HF_TOKEN")
        print(f"   • Или настройте hf_token в config.json")
    
    if config_file.exists():
        if config.get('telegram_token') == 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
            print(f"   • Замените 'YOUR_TELEGRAM_BOT_TOKEN_HERE' на реальный токен в config.json")
        if config.get('hf_api_token') == 'YOUR_HUGGING_FACE_API_TOKEN_HERE':
            print(f"   • Замените 'YOUR_HUGGING_FACE_API_TOKEN_HERE' на реальный токен в config.json")
        if config.get('hf_token') == 'YOUR_HUGGING_FACE_TOKEN_HERE':
            print(f"   • Замените 'YOUR_HUGGING_FACE_TOKEN_HERE' на реальный токен в config.json")
    
    print(f"\n📖 Подробная инструкция: см. TELEGRAM_SETUP.md")

if __name__ == "__main__":
    check_config() 