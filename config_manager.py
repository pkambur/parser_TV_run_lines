import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    Централизованный менеджер конфигурации для загрузки и кэширования
    файлов channels.json и keywords.json
    """
    
    def __init__(self):
        """
        Инициализация менеджера конфигурации.
        """
        self._channels_cache: Optional[Dict[str, Any]] = None
        self._keywords_cache: Optional[Dict[str, Any]] = None
        self._channels_last_modified: Optional[datetime] = None
        self._keywords_last_modified: Optional[datetime] = None
        self._cache_duration = timedelta(seconds=30)  # Кэш на 30 секунд
        
        # Пути к файлам конфигурации
        self.channels_file = Path('channels.json')
        self.keywords_file = Path('keywords.json')
    
    def _get_file_modification_time(self, file_path: Path) -> Optional[datetime]:
        """
        Получает время последней модификации файла.
        """
        try:
            if file_path.exists():
                return datetime.fromtimestamp(file_path.stat().st_mtime)
        except Exception as e:
            logger.error(f"Ошибка при получении времени модификации файла {file_path}: {e}")
        return None
    
    def _is_cache_valid(self, file_path: Path, last_modified: Optional[datetime]) -> bool:
        """
        Проверяет, действителен ли кэш для файла.
        """
        if last_modified is None:
            return False
        
        current_mod_time = self._get_file_modification_time(file_path)
        if current_mod_time is None:
            return False
        
        return (datetime.now() - last_modified) < self._cache_duration
    
    def load_channels(self, force_reload: bool = False) -> Dict[str, Any]:
        """
        Загружает конфигурацию каналов из channels.json с кэшированием.
        
        Args:
            force_reload: Принудительная перезагрузка файла
            
        Returns:
            Словарь с конфигурацией каналов
        """
        # Проверяем кэш, если не требуется принудительная перезагрузка
        if not force_reload and self._channels_cache is not None:
            if self._is_cache_valid(self.channels_file, self._channels_last_modified):
                logger.debug("Используется кэшированная конфигурация каналов")
                return self._channels_cache
        
        # Проверка существования файла
        if not self.channels_file.exists():
            error_msg = "Файл channels.json не найден"
            logger.error(error_msg)
            self._channels_cache = {}
            self._channels_last_modified = None
            return {}
        
        try:
            # Загружаем файл
            with self.channels_file.open('r', encoding='utf-8') as f:
                channels = json.load(f)
            
            # Обновляем кэш
            self._channels_cache = channels
            self._channels_last_modified = self._get_file_modification_time(self.channels_file)
            
            logger.info(f"Конфигурация каналов загружена: {len(channels)} каналов")
            return channels
            
        except FileNotFoundError:
            error_msg = "Файл channels.json не найден"
            logger.error(error_msg)
            self._channels_cache = {}
            self._channels_last_modified = None
            return {}
        except json.JSONDecodeError as e:
            error_msg = f"Ошибка в формате файла channels.json: {e}"
            logger.error(error_msg)
            self._channels_cache = {}
            self._channels_last_modified = None
            return {}
        except Exception as e:
            error_msg = f"Ошибка при загрузке channels.json: {e}"
            logger.error(error_msg)
            self._channels_cache = {}
            self._channels_last_modified = None
            return {}
    
    def load_keywords(self, force_reload: bool = False) -> Dict[str, Any]:
        """
        Загружает ключевые слова из keywords.json с кэшированием.
        
        Args:
            force_reload: Принудительная перезагрузка файла
            
        Returns:
            Словарь с ключевыми словами
        """
        # Проверяем кэш, если не требуется принудительная перезагрузка
        if not force_reload and self._keywords_cache is not None:
            if self._is_cache_valid(self.keywords_file, self._keywords_last_modified):
                logger.debug("Используется кэшированный список ключевых слов")
                return self._keywords_cache
        
        # Проверка существования файла
        if not self.keywords_file.exists():
            error_msg = "Файл keywords.json не найден"
            logger.error(error_msg)
            self._keywords_cache = {"keywords": []}
            self._keywords_last_modified = None
            return {"keywords": []}
        
        try:
            # Загружаем файл
            with self.keywords_file.open('r', encoding='utf-8') as f:
                keywords = json.load(f)
            
            # Обновляем кэш
            self._keywords_cache = keywords
            self._keywords_last_modified = self._get_file_modification_time(self.keywords_file)
            
            logger.info(f"Ключевые слова загружены: {len(keywords.get('keywords', []))} слов")
            return keywords
            
        except FileNotFoundError:
            error_msg = "Файл keywords.json не найден"
            logger.error(error_msg)
            self._keywords_cache = {"keywords": []}
            self._keywords_last_modified = None
            return {"keywords": []}
        except json.JSONDecodeError as e:
            error_msg = f"Ошибка в формате файла keywords.json: {e}"
            logger.error(error_msg)
            self._keywords_cache = {"keywords": []}
            self._keywords_last_modified = None
            return {"keywords": []}
        except Exception as e:
            error_msg = f"Ошибка при загрузке keywords.json: {e}"
            logger.error(error_msg)
            self._keywords_cache = {"keywords": []}
            self._keywords_last_modified = None
            return {"keywords": []}
    
    def get_channel_info(self, channel_name: str) -> Optional[Dict[str, Any]]:
        """
        Получает информацию о конкретном канале.
        
        Args:
            channel_name: Название канала
            
        Returns:
            Словарь с информацией о канале или None
        """
        channels = self.load_channels()
        return channels.get(channel_name)
    
    def get_channel_names(self) -> list:
        """
        Получает список всех названий каналов.
        
        Returns:
            Список названий каналов
        """
        channels = self.load_channels()
        return list(channels.keys())
    
    def get_keywords_list(self) -> list:
        """
        Получает список ключевых слов.
        
        Returns:
            Список ключевых слов
        """
        keywords_data = self.load_keywords()
        return keywords_data.get('keywords', [])
    
    def save_channels(self, channels: Dict[str, Any]) -> bool:
        """
        Сохраняет конфигурацию каналов в файл.
        
        Args:
            channels: Словарь с конфигурацией каналов
            
        Returns:
            True если сохранение прошло успешно, False иначе
        """
        try:
            # Создаем резервную копию
            if self.channels_file.exists():
                backup_path = self.channels_file.with_suffix('.json.bak')
                import shutil
                shutil.copy2(str(self.channels_file), str(backup_path))
                logger.info(f"Создана резервная копия: {backup_path}")
            
            # Сохраняем новый файл
            with self.channels_file.open('w', encoding='utf-8') as f:
                json.dump(channels, f, ensure_ascii=False, indent=2)
            
            # Обновляем кэш
            self._channels_cache = channels
            self._channels_last_modified = self._get_file_modification_time(self.channels_file)
            
            logger.info("Конфигурация каналов успешно сохранена")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении channels.json: {e}")
            return False
    
    def save_keywords(self, keywords: Dict[str, Any]) -> bool:
        """
        Сохраняет ключевые слова в файл.
        
        Args:
            keywords: Словарь с ключевыми словами
            
        Returns:
            True если сохранение прошло успешно, False иначе
        """
        try:
            # Создаем резервную копию
            if self.keywords_file.exists():
                backup_path = self.keywords_file.with_suffix('.json.bak')
                import shutil
                shutil.copy2(str(self.keywords_file), str(backup_path))
                logger.info(f"Создана резервная копия: {backup_path}")
            
            # Сохраняем новый файл
            with self.keywords_file.open('w', encoding='utf-8') as f:
                json.dump(keywords, f, ensure_ascii=False, indent=2)
            
            # Обновляем кэш
            self._keywords_cache = keywords
            self._keywords_last_modified = self._get_file_modification_time(self.keywords_file)
            
            logger.info("Ключевые слова успешно сохранены")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении keywords.json: {e}")
            return False
    
    def clear_cache(self):
        """
        Очищает кэш конфигурации.
        """
        self._channels_cache = None
        self._keywords_cache = None
        self._channels_last_modified = None
        self._keywords_last_modified = None
        logger.info("Кэш конфигурации очищен")
    
    def reload_all(self):
        """
        Принудительно перезагружает все конфигурации.
        """
        self.load_channels(force_reload=True)
        self.load_keywords(force_reload=True)
        logger.info("Все конфигурационные файлы перезагружены")

# Глобальный экземпляр менеджера конфигурации
config_manager = ConfigManager()

# Функции-обертки для обратной совместимости
def load_channels() -> Dict[str, Any]:
    """
    Глобальная функция для загрузки каналов через config_manager.
    """
    return config_manager.load_channels()

def load_keywords() -> list:
    """
    Глобальная функция для загрузки ключевых слов через config_manager.
    """
    return config_manager.get_keywords_list() 