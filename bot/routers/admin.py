import html
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
import bot.keyboards as kb
import database.requests as rq
from bot.config import ADMIN_ID, EVENT_CONFIG, validate_event_value
from bot.common import Form, send_to_all_chats


router = Router()
router.message.filter(F.from_user.id == ADMIN_ID, F.chat.type == 'private')
router.callback_query.filter(F.from_user.id == ADMIN_ID, F.message.chat.type == 'private')

@router.message(Command('event'))
async def command_event(message: Message) -> None:
    if message.from_user.id != ADMIN_ID: return
    await message.reply('Укажи параметры ивента', reply_markup=kb.event_settings)


@router.callback_query(F.data.in_(EVENT_CONFIG.keys()))
async def event_parameter_select(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.answer()
    param_config = EVENT_CONFIG[callback.data]
    await state.clear()
    await callback.message.reply(param_config['message'], reply_markup=kb.event_settings)
    await state.update_data(setting=callback.data, key=param_config['key'])
    await state.set_state(Form.add_event_settings)


@router.message(Form.add_event_settings)
async def event_parameter_set(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    setting = data.get('setting')
    key = data.get('key')
    param_config = EVENT_CONFIG[setting]
    if validate_event_value(key, message.text):
        value = param_config['type'](message.text.strip())
        await rq.set_event(setting=key, value=value)
        await state.clear()
        await message.reply('✅ Настройка события сохранена.', reply_markup=kb.event_settings)
    else:
        await message.reply('Некорректное значение. ' + param_config['message'], reply_markup=kb.event_settings)


@router.callback_query(F.data.in_(['event_start', 'event_stop']))
async def event_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID: return
    await callback.answer()
    await state.clear()
    event_data = await rq.get_event_settings(True)
    if callback.data == 'event_start':
        await rq.set_event('activated', True)
        text = (
            f"<b>🎊 Ивент «{html.escape(event_data['name'])}»</b>\n"
            f"{html.escape(event_data['description'])}"
        )
    else:
        await rq.set_event('activated', False)
        text = f"Ивент «{html.escape(event_data['name'])}» завершён"
    await send_to_all_chats(callback.message.bot, text)
    await callback.message.answer('✅ Состояние события обновлено.', reply_markup=kb.event_settings)


@router.callback_query(F.data == 'event_settings')
async def event_settings_show(callback: CallbackQuery) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступно только администратору", show_alert=True)
        return
    await callback.answer()
    data = await rq.get_event_settings(True)
    text = '\n'.join(f'{key}: {value}' for key, value in data.items())
    await callback.message.answer(text, reply_markup=kb.event_settings)


@router.callback_query(F.data == 'event_reset')
async def event_reset_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступно только администратору", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    event = await rq.get_event_settings(True)
    if event['activated']:
        await callback.message.answer('Нельзя сбросить настройки ивента, пока он идёт')
        return
    reset_settings = {'name': 'Ивент', 'description': '', 'cd_event': 0, 'prim_event': 0, 'lvl_event': 0,
                      'activated': False}
    await rq.set_event_settings(reset_settings)
    await callback.message.answer('Настройки ивента сброшены', reply_markup=kb.event_settings)


@router.message(Command('channel'))
async def command_channel(message: Message) -> None:
    if message.from_user.id != ADMIN_ID: return
    argument = message.text.partition(' ')[2].strip()
    parts = argument.split('&')
    if not argument:
        await rq.reset_channels()
    else:
        try:
            tg_id, name, link = int(parts[0]), parts[1].strip(), parts[2].strip()
            if not name or not link.startswith('https://'): raise ValueError
        except (ValueError, IndexError):
            await message.answer('Формат: /channel ID & Название & https://t.me/канал')
            return
        await rq.add_channel(tg_id=tg_id, name=name, link=link)
        await message.answer(f'✅ Канал {name} добавлен!')


# Система покупок
@router.message(Command('add_promo'))
async def promo_add(message: Message) -> None:
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 4:
        await message.answer('Использование: /add_promo имя лимит xp')
        return
    try:
        name, limit, xp = parts[1].upper(), int(parts[2]), int(parts[3])
        if limit < 1 or xp < 0: raise ValueError
    except ValueError:
        await message.answer('Лимит должен быть положительным целым числом, очки — неотрицательным.')
        return
    await rq.add_promo(name, limit, xp)
    await message.answer(f'Ты добавил код {name}')
