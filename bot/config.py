import os
from pathlib import Path

from dotenv import load_dotenv

# Читаем настройки из корня проекта независимо от рабочей директории.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1307205193"))
ADMIN_IDS = frozenset({ADMIN_ID, 1631402766})
TEST_ID = int(os.getenv("TEST_ID", "8355668870"))
COOLDOWN = 3600  # 1 час в секундах

from bot.catalog import OBJECTS as OBJECTS, STANDARD_ITEMS as STANDARD_ITEMS, LEVELS as LEVELS


def validate_event_value(setting, value):
    if not isinstance(value, str):
        return False
    value = value.strip()
    if setting in ('name', 'description'):
        return 1 <= len(value) <= (255 if setting == 'name' else 1000)
    try:
        number = float(value) if setting == 'prim_event' else int(value)
    except (ValueError, OverflowError):
        return False
    low, high = {'cd_event': (-86400, 86400), 'prim_event': (-1, 1),
                 'lvl_event': (-10, 10)}[setting]
    return low <= number <= high


EVENT_CONFIG = {
    'event_name': {'message': 'Название события (до 255 символов):', 'key': 'name', 'type': str},
    'event_description': {'message': 'Описание события (до 1000 символов):', 'key': 'description', 'type': str},
    'event_cd': {'message': 'Изменение КД в секундах: от -86400 до 86400.', 'key': 'cd_event', 'type': int},
    'event_prim': {'message': 'Изменение риска: от -1 до 1, например -0.1.', 'key': 'prim_event', 'type': float},
    'event_lvl': {'message': 'Изменение подбора объектов: от -10 до 10.', 'key': 'lvl_event', 'type': int},
}
