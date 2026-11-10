from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import database.requests as rq
import time

# Базовые клавиатуры
start_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='➕ Добавить в чат', url='https://t.me/rooferskiybot?startgroup=roof')]
])

level_up = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='⏫ Повысить уровень', callback_data='level')]
])

stats = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='📊 Моя статистика', callback_data='stats')]
])


# Клавиатура с каналами
async def channels():
    channels_data = await rq.get_channels()
    buttons = [[InlineKeyboardButton(text=channel['name'], url=channel['link'])] for channel in channels_data]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Клавиатуры для магазина и оплаты
async def shop():
    items = await rq.get_items()
    buttons = [[InlineKeyboardButton(text=f'{item.name.capitalize()} {item.price} ⭐️',
                                     callback_data=f'buy_{item.key}')] for item in items if item.enabled and (not item.available_until or time.time() < item.available_until)]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


buy = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Купить', pay=True)]
])

# Клавиатура управления ивентами
event_settings = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Название', callback_data='event_name')],
    [InlineKeyboardButton(text='Описание', callback_data='event_description')],
    [
        InlineKeyboardButton(text='КД', callback_data='event_cd'),
        InlineKeyboardButton(text='Прим', callback_data='event_prim'),
        InlineKeyboardButton(text='Лвл', callback_data='event_lvl')
    ],
    [InlineKeyboardButton(text='✅ Начать!', callback_data='event_start')],
    [InlineKeyboardButton(text='🛑 Закончить', callback_data='event_stop')],
    [InlineKeyboardButton(text='⚙️ Настройки', callback_data='event_settings')],
    [InlineKeyboardButton(text='🗑️ Сбросить', callback_data='event_reset')],
    [InlineKeyboardButton(text='⬅️ В меню', callback_data='admin_cancel')]
])
