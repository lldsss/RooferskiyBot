"""Приватная панель администратора и пошаговое создание предметов."""
import time
from html import escape
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import ADMIN_ID
from bot import keyboards as kb
from database import requests as rq
from database.admin import create_item, toggle_item, summary, create_promo, remove_channel

router = Router()
router.message.filter(F.from_user.id == ADMIN_ID, F.chat.type == 'private')
router.callback_query.filter(F.from_user.id == ADMIN_ID, F.message.chat.type == 'private')


def buttons(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=data) for label, data in row] for row in rows])


menu = buttons([[('📦 Предметы', 'admin_items'), ('➕ Создать предмет', 'admin_new')],
                [('🎊 События', 'admin_events'), ('📊 Сводка', 'admin_summary')],
                [('📣 Каналы', 'admin_channels'), ('🎟 Промокоды', 'admin_promos')]])


cancel = buttons([[('❌ Отмена / в меню', 'admin_cancel')]])


class Management(StatesGroup):
    value = State()
    confirm = State()


MANAGEMENT_FIELDS = {
    'channel': [('tg_id', 'Отправь числовой ID канала (начинается с -100):'),
                ('name', 'Название канала (до 255 символов):'),
                ('link', 'Ссылка на канал: https://t.me/имя или ссылка-приглашение.')],
    'promo': [('name', 'Промокод: 1–32 латинские буквы, цифры, _ или -.'),
              ('limit', 'Лимит активаций: от 1 до 1000000.'),
              ('xp', 'Награда в очках: от 0 до 1000000.')],
}


def parse_management(kind, field, value):
    import re
    value = value.strip()
    if field == 'tg_id':
        if not re.fullmatch(r'-100[0-9]{1,16}', value): raise ValueError
        return int(value)
    if field == 'name':
        if kind == 'promo':
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', value): raise ValueError
            return value.upper()
        if not 1 <= len(value) <= 255: raise ValueError
        return value
    if field == 'link':
        if not re.fullmatch(r'https://t\.me/[A-Za-z0-9_+/-]+', value) or len(value) > 500: raise ValueError
        return value
    number = int(value)
    if not (1 if field == 'limit' else 0) <= number <= 1000000: raise ValueError
    return number


class Wizard(StatesGroup):
    value = State()
    confirm = State()


FIELDS = [
    ('name', 'Название предмета (до 32 символов):'),
    ('description', 'Описание эффекта (до 200 символов):'),
    ('price', 'Цена в Stars: целое число от 1 до 10000.'),
    ('cd', 'На сколько минут сократить отдых? От 0 до 50.'),
    ('prim', 'На сколько процентных пунктов снизить риск? От 0 до 100.'),
    ('lvl', 'Бонус к подбору объектов: от 0 до 10 уровней.'),
    ('duration', 'Сколько часов действует купленное усиление? От 1 до 8760.'),
    ('sale_hours', 'Сколько часов продавать предмет? От 1 до 8760, либо 0 — бессрочно.'),
]


def parse_value(field, value):
    value = value.strip()
    if field in ('name', 'description'):
        if not 1 <= len(value) <= (32 if field == 'name' else 200):
            raise ValueError
        return value
    number = int(value)
    low, high = {'price': (1, 10000), 'cd': (0, 50), 'prim': (0, 100),
                 'lvl': (0, 10), 'duration': (1, 8760), 'sale_hours': (0, 8760)}[field]
    if not low <= number <= high:
        raise ValueError
    return number * -60 if field == 'cd' else number / -100 if field == 'prim' else number * 3600 if field == 'duration' else number


@router.message(Command('admin', 'cancel', 'start'))
async def admin_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer('⚙️ Панель администратора\n\nВыбери раздел — управление доступно через кнопки.', reply_markup=menu)


@router.callback_query(F.data.startswith('admin_'))
async def panel_action(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    action = callback.data
    if action == 'admin_manage_save':
        if await state.get_state() != Management.confirm.state:
            await callback.message.answer('Этот шаг уже завершён. Открой меню.', reply_markup=menu)
            return
        data = await state.get_data()
        if data['kind'] == 'channel':
            await rq.add_channel(**data['values'])
            result = '✅ Канал сохранён.'
        else:
            result = '✅ Промокод создан.' if await create_promo(data['values']) else 'Промокод с таким именем уже существует.'
        await state.clear()
        await callback.message.answer(result, reply_markup=menu)
        return
    if action == 'admin_save':
        if await state.get_state() != Wizard.confirm.state:
            return
        data = await state.get_data()
        if not await create_item(data['item']):
            await callback.message.answer('Предмет с таким названием уже есть. Начни заново через меню.', reply_markup=menu)
        else:
            await callback.message.answer('✅ Предмет добавлен в магазин.', reply_markup=menu)
        await state.clear()
        return
    await state.clear()
    if action in ('admin_channel_new', 'admin_promo_new'):
        kind = 'channel' if action == 'admin_channel_new' else 'promo'
        await state.set_state(Management.value)
        await state.update_data(kind=kind, step=0, values={})
        await callback.message.answer(MANAGEMENT_FIELDS[kind][0][1], reply_markup=cancel)
    elif action == 'admin_channels_reset':
        await callback.message.answer('Восстановить стандартный канал? Текущий список обязательных подписок будет заменён.', reply_markup=buttons([[('✅ Восстановить', 'admin_channels_reset_confirm')], [('Назад', 'admin_channels')]]))
    elif action == 'admin_channels_reset_confirm':
        await rq.reset_channels()
        await callback.message.answer('✅ Стандартный канал восстановлен.', reply_markup=menu)
    elif action.startswith('admin_channel_delete_'):
        channel_id = int(action.removeprefix('admin_channel_delete_'))
        await remove_channel(channel_id)
        await callback.message.answer('✅ Канал удалён из обязательных подписок.', reply_markup=menu)
    elif action == 'admin_cancel':
        await callback.message.answer('⚙️ Панель администратора', reply_markup=menu)
    elif action == 'admin_new':
        await state.set_state(Wizard.value)
        await state.update_data(step=0, item={})
        await callback.message.answer('📦 Новый предмет\n\n' + FIELDS[0][1], reply_markup=cancel)
    elif action == 'admin_events':
        await callback.message.answer('🎊 Управление событием', reply_markup=kb.event_settings)
    elif action == 'admin_summary':
        await callback.message.answer('📊 Сводка\n\n' + '\n'.join(f'{k}: {v}' for k, v in (await summary()).items()), reply_markup=menu)
    elif action == 'admin_channels':
        channels = await rq.get_channels()
        for channel in channels:
            await callback.message.answer(f"📣 {escape(channel['name'])}\nID: {channel['tg_id']}\n{escape(channel['link'])}", parse_mode='HTML', reply_markup=buttons([[('Удалить из подписок', f"admin_channel_delete_{channel['tg_id']}")]]))
        await callback.message.answer('📣 Управление обязательными подписками' if channels else '📣 Список каналов пуст.', reply_markup=buttons([[('➕ Добавить / обновить', 'admin_channel_new')], [('Восстановить стандартный канал', 'admin_channels_reset')], [('⬅️ В меню', 'admin_cancel')]]))
    elif action == 'admin_promos':
        await callback.message.answer('🎟 Промокоды\n\nСоздай код с ограничением активаций и наградой в очках.', reply_markup=buttons([[('➕ Создать промокод', 'admin_promo_new')], [('⬅️ В меню', 'admin_cancel')]]))
    elif action == 'admin_items' or action.startswith('admin_toggle_'):
        if action.startswith('admin_toggle_'):
            await toggle_item(action.removeprefix('admin_toggle_'))
        for item in await rq.get_items():
            status = '🟢 В продаже' if item.enabled and (not item.available_until or item.available_until > time.time()) else '⚪ Снят с продажи'
            remaining = f'{max(0, (item.available_until - time.time()) / 3600):.1f} ч.' if item.available_until else 'бессрочно'
            await callback.message.answer(f'<b>{escape(item.name)}</b> · {item.price} ⭐\n{escape(item.description)}\n\n{status}\nСрок продажи: {remaining}\nДействие покупки: {item.duration / 3600:g} ч.', parse_mode='HTML', reply_markup=buttons([[('Скрыть' if item.enabled else 'Включить', f'admin_toggle_{item.key}')]]))
        await callback.message.answer('Управление магазином', reply_markup=menu)


@router.message(Wizard.value)
async def item_value(message: Message, state: FSMContext):
    data = await state.get_data()
    step, item = data['step'], data['item']
    field, prompt = FIELDS[step]
    try:
        item[field] = parse_value(field, message.text or '')
    except (ValueError, TypeError):
        await message.answer('Некорректное значение. ' + prompt, reply_markup=cancel)
        return
    step += 1
    await state.update_data(item=item, step=step)
    if step < len(FIELDS):
        await message.answer(FIELDS[step][1], reply_markup=cancel)
    else:
        await state.set_state(Wizard.confirm)
        sale = f"{item['sale_hours']} ч." if item['sale_hours'] else 'бессрочно'
        await message.answer(f"📦 <b>{escape(item['name'])}</b>\n{escape(item['description'])}\n\nЦена: {item['price']} ⭐\nОтдых: {item['cd'] // 60} мин\nРиск: {item['prim'] * 100:g} п.п.\nПодбор объектов: +{item['lvl']}\nДействие: {item['duration'] // 3600} ч.\nПродажа: {sale}", parse_mode='HTML', reply_markup=buttons([[('✅ Добавить в магазин', 'admin_save'), ('❌ Отмена', 'admin_cancel')]]))


@router.message(Management.value)
async def management_value(message: Message, state: FSMContext):
    data = await state.get_data()
    kind, step, values = data['kind'], data['step'], data['values']
    field, prompt = MANAGEMENT_FIELDS[kind][step]
    try:
        values[field] = parse_management(kind, field, message.text or '')
    except (ValueError, TypeError):
        await message.answer('Некорректное значение. ' + prompt, reply_markup=cancel)
        return
    step += 1
    await state.update_data(values=values, step=step)
    if step < len(MANAGEMENT_FIELDS[kind]):
        await message.answer(MANAGEMENT_FIELDS[kind][step][1], reply_markup=cancel)
        return
    await state.set_state(Management.confirm)
    if kind == 'channel':
        text = f"📣 <b>{escape(values['name'])}</b>\nID: {values['tg_id']}\n{escape(values['link'])}\n\nКанал с таким ID будет добавлен или обновлён."
    else:
        text = f"🎟 <b>{escape(values['name'])}</b>\nЛимит: {values['limit']}\nНаграда: {values['xp']} очков"
    await message.answer(text, parse_mode='HTML', reply_markup=buttons([[('✅ Сохранить', 'admin_manage_save'), ('❌ Отмена', 'admin_cancel')]]))
