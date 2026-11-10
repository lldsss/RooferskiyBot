import os
from pathlib import Path

from dotenv import load_dotenv

# Читаем настройки из корня проекта независимо от рабочей директории.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1307205193"))
TEST_ID = int(os.getenv("TEST_ID", "8355668870"))
COOLDOWN = 3600  # 1 час в секундах

EVENT_CONFIG = {
    'event_name': {
        'message': 'Укажи название ивента',
        'key': 'name',
        'type': str,
        'validate': lambda x: x  # Любая непустая строка
    },
    'event_description': {
        'message': 'Укажи описание ивента',
        'key': 'description',
        'type': str,
        'validate': lambda x: x  # Любая непустая строка
    },
    'event_cd': {
        'message': 'Укажи КД ивента (в секундах)',
        'key': 'cd_event',
        'type': int,
        'validate': lambda x: x.lstrip('-').isascii() and x.lstrip('-').isdecimal() and x.count('-') <= 1  # Целое число
    },
    'event_prim': {
        'message': 'Укажи прим ивента (например: 0.1)',
        'key': 'prim_event',
        'type': float,
        'validate': lambda x: x.lstrip('-').replace('.', '', 1).isascii() and x.lstrip('-').replace('.', '', 1).isdecimal() and x.count('-') <= 1  # Число с плавающей точкой
    },
    'event_lvl': {
        'message': 'Укажи лвл ивента',
        'key': 'lvl_event',
        'type': int,
        'validate': lambda x: x.lstrip('-').isascii() and x.lstrip('-').isdecimal() and x.count('-') <= 1  # Целое число
    },
}

from bot.catalog import STANDARD_ITEMS, OBJECTS, LEVELS
