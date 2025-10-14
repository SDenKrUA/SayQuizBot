import logging
import aiofiles
import aiofiles.os
import asyncio
from logging import Handler, Formatter
from typing import Optional
import os

class AsyncFileHandler(Handler):
    """Асинхронний обробник для запису логів у файл"""
    
    def __init__(self, filename: str, encoding: str = 'utf-8', mode: str = 'a'):
        super().__init__()
        self.filename = filename
        self.encoding = encoding
        self.mode = mode
        self._file = None
        self._lock = asyncio.Lock()
        
    async def _ensure_file_open(self):
        """Відкриває файл асинхронно"""
        if self._file is None:
            self._file = await aiofiles.open(self.filename, self.mode, encoding=self.encoding)
            
    async def emit(self, record):
        """Асинхронний запис логу"""
        try:
            async with self._lock:
                await self._ensure_file_open()
                message = self.format(record)
                await self._file.write(message + '\n')
                await self._file.flush()
        except Exception as e:
            print(f"Logging error: {e}")
            
    async def close(self):
        """Асинхронне закриття файлу"""
        if self._file:
            await self._file.close()
            self._file = None

class AsyncStreamHandler(Handler):
    """Асинхронний обробник для виводу в консоль"""
    
    def __init__(self):
        super().__init__()
        
    async def emit(self, record):
        """Асинхронний вивід в консоль"""
        try:
            message = self.format(record)
            print(message)
        except Exception as e:
            print(f"Console logging error: {e}")

class AsyncLogger:
    """Асинхронний логгер"""
    
    def __init__(self, name: str, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.handlers = []
        
    def add_handler(self, handler):
        """Додає обробник"""
        self.handlers.append(handler)
        self.logger.addHandler(handler)
        
    async def debug(self, message: str):
        """Асинхронний debug запис"""
        await self._log_async(logging.DEBUG, message)
        
    async def info(self, message: str):
        """Асинхронний info запис"""
        await self._log_async(logging.INFO, message)
        
    async def warning(self, message: str):
        """Асинхронний warning запис"""
        await self._log_async(logging.WARNING, message)
        
    async def error(self, message: str):
        """Асинхронний error запис"""
        await self._log_async(logging.ERROR, message)
        
    async def critical(self, message: str):
        """Асинхронний critical запис"""
        await self._log_async(logging.CRITICAL, message)
        
    async def _log_async(self, level: int, message: str):
        """Асинхронний запис логу"""
        # Використовуємо executor для синхронного виклику logging
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.logger.log, level, message)
        
    async def close(self):
        """Асинхронне закриття всіх обробників"""
        for handler in self.handlers:
            if hasattr(handler, 'close') and callable(handler.close):
                await handler.close()

async def setup_async_logger() -> AsyncLogger:
    """
    Асинхронна ініціалізація логгера
    """
    # Створюємо папку для логів асинхронно
    await aiofiles.os.makedirs("logs", exist_ok=True)
    
    # Форматер
    formatter = Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Створюємо асинхронний логгер
    async_logger = AsyncLogger("test_bot")
    
    # Додаємо асинхронний файловий обробник
    file_handler = AsyncFileHandler("logs/bot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    async_logger.add_handler(file_handler)
    
    # Додаємо асинхронний консольний обробник
    console_handler = AsyncStreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    async_logger.add_handler(console_handler)
    
    return async_logger

# Синхронна версія для зворотної сумісності
def setup_logger():
    """
    Синхронна ініціалізація логгера (для зворотної сумісності)
    """
    os.makedirs("logs", exist_ok=True)
    
    logger = logging.getLogger("test_bot")
    logger.setLevel(logging.INFO)
    
    # Очищаємо старі обробники
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Додаємо файловий обробник
    file_handler = logging.FileHandler("logs/bot.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    logger.addHandler(file_handler)
    
    # Додаємо консольний обробник
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    logger.addHandler(console_handler)
    
    return logger

# Глобальний асинхронний логгер
_async_logger = None

async def get_async_logger() -> AsyncLogger:
    """Отримуємо глобальний асинхронний логгер"""
    global _async_logger
    if _async_logger is None:
        _async_logger = await setup_async_logger()
    return _async_logger

async def close_async_logger():
    """Закриваємо асинхронний логгер"""
    global _async_logger
    if _async_logger:
        await _async_logger.close()
        _async_logger = None