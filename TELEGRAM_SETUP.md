# Настройка токенов и API

## Безопасная конфигурация

Для безопасной работы приложения необходимо настроить токены и API ключи одним из способов:

## Способ 1: Переменные окружения (рекомендуется)

### Windows (PowerShell):
```powershell
$env:TELEGRAM_TOKEN="YOUR_BOT_TOKEN_HERE"
$env:TELEGRAM_CHAT_IDS="984259692,117436228"
$env:HF_API_TOKEN="YOUR_HUGGING_FACE_API_TOKEN_HERE"
$env:HF_TOKEN="YOUR_HUGGING_FACE_TOKEN_HERE"
```

### Windows (Command Prompt):
```cmd
set TELEGRAM_TOKEN=YOUR_BOT_TOKEN_HERE
set TELEGRAM_CHAT_IDS=984259692,117436228
set HF_API_TOKEN=YOUR_HUGGING_FACE_API_TOKEN_HERE
set HF_TOKEN=YOUR_HUGGING_FACE_TOKEN_HERE
```

### Linux/Mac:
```bash
export TELEGRAM_TOKEN="YOUR_BOT_TOKEN_HERE"
export TELEGRAM_CHAT_IDS="984259692,117436228"
export HF_API_TOKEN="YOUR_HUGGING_FACE_API_TOKEN_HERE"
export HF_TOKEN="YOUR_HUGGING_FACE_TOKEN_HERE"
```

## Способ 2: Файл конфигурации

1. Отредактируйте файл `config.json`:
```json
{
    "telegram_token": "YOUR_BOT_TOKEN_HERE",
    "chat_ids": [984259692],
    "hf_api_token": "YOUR_HUGGING_FACE_API_TOKEN_HERE",
    "hf_token": "YOUR_HUGGING_FACE_TOKEN_HERE",
    "processed_dir": "screenshots_processed",
    "max_width": 1280,
    "max_height": 1280,
    "max_file_size": 10485760,
    "max_video_size": 52428800,
    "telegram_timeout": 600.0,
    "telegram_connect_timeout": 60.0
}
```

## Получение токенов

### Telegram Bot Token
1. Найдите @BotFather в Telegram
2. Отправьте команду `/newbot`
3. Следуйте инструкциям для создания бота
4. Скопируйте полученный токен

### Hugging Face API Token
1. Зарегистрируйтесь на [Hugging Face](https://huggingface.co/)
2. Перейдите в Settings → Access Tokens
3. Создайте новый токен с правами `read`
4. Скопируйте токен

### Hugging Face Token (дополнительный)
1. Тот же токен, что и для API, или создайте отдельный
2. Используется для дополнительных функций

## Получение ID чата

1. Добавьте бота в нужный чат
2. Отправьте сообщение в чат
3. Перейдите по ссылке: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Найдите `"chat":{"id":123456789}` - это и есть ID чата

## Приоритет конфигурации

1. Переменные окружения (высший приоритет)
2. Файл config.json
3. Значения по умолчанию

## Обязательные и опциональные токены

### Обязательные:
- **TELEGRAM_TOKEN** - для отправки сообщений в Telegram
- **TELEGRAM_CHAT_IDS** - ID чатов для отправки

### Опциональные:
- **HF_API_TOKEN** - для улучшенного анализа ключевых слов через Hugging Face API
- **HF_TOKEN** - для дополнительных функций Hugging Face

## Безопасность

- **НЕ** коммитьте токены в Git
- **НЕ** делитесь токенами публично
- Используйте переменные окружения в продакшене
- Регулярно обновляйте токены при необходимости

## Проверка настройки

После настройки запустите скрипт проверки:
```bash
python check_config.py
```

Должно появиться сообщение "Конфигурация успешно загружена" и все токены должны быть отмечены как установленные.

## Функциональность без токенов

Приложение будет работать даже без опциональных токенов:
- **Без HF_API_TOKEN**: используется локальная проверка ключевых слов
- **Без HF_TOKEN**: используются только базовые функции
- **Без TELEGRAM_TOKEN**: приложение не сможет отправлять сообщения в Telegram 