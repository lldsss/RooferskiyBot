from bot.messages import cooldown as format_cooldown_message
from bot.messages import profile
import html
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
import bot.keyboards as kb
import database.requests as rq
from bot.services import roof
from bot.common import setup_user_and_chat, check_prerequisites, process_roof_result, check_callback_prerequisites


router = Router()

@router.message(CommandStart())
async def command_start(message: Message) -> None:
    await setup_user_and_chat(message)
    if not await check_prerequisites(message): return
    await message.reply('🏙 Руферский бот\n\n/roof — отправиться на объект\n/me — моя статистика\n/top — рейтинг игроков\n/level — условия повышения\n/buy — магазин усилений на 24 часа\n/promo КОД — активировать промокод')


@router.message(Command('roof'))
async def command_roof(message: Message) -> None:
    await setup_user_and_chat(message)
    if not await check_prerequisites(message): return

    user_id = message.from_user.id

    remaining, obj = await roof(user_id)
    if remaining > 0:
        await message.reply(format_cooldown_message(remaining), parse_mode='HTML')
    elif obj is None:
        await message.reply('🏙 Пока нет доступных объектов. Попробуй позже.')
    else:
        await process_roof_result(message, obj)


@router.message(Command('me'))
async def command_me(message: Message) -> None:
    await setup_user_and_chat(message)
    if not await check_prerequisites(message): return
    user_info = await rq.get_user_info(message.from_user.id)
    await message.reply(
        profile(message.from_user.first_name, user_info),
        parse_mode='HTML')


@router.message(Command('top'))
async def command_top(message: Message) -> None:
    """Показывает топ-10 игроков с медальками"""
    await setup_user_and_chat(message)
    if not await check_prerequisites(message):
        return

    top_users = await rq.top()
    if not top_users:
        await message.reply('Топ пуст 🫥')
        return

    # Медальки для первых 3 мест
    medals = ['🥇', '🥈', '🥉']
    message_text = '<b>🏆 Топ-10 руферов:</b>\n\n'

    for i, user in enumerate(top_users):
        medal = medals[i] if i < len(medals) else f'{i + 1}.'  # Медальки для топ-3, цифры для остальных
        message_text += f'{medal} {html.escape(user["name"])} — {user["level"]} ур. | {user["xp"]} очков\n'

    await message.reply(message_text, parse_mode='HTML')


@router.message(Command('level'))
async def command_level(message: Message) -> None:
    await setup_user_and_chat(message)
    user_info = await rq.get_user_info(message.from_user.id)
    current_level = user_info['level']
    if current_level >= 10:
        await message.reply('<b>Твой уровень: 10\nЭто максимально возможный уровень</b>', parse_mode='HTML')
        return
    if await rq.able_to_update(message.from_user.id):
        await message.reply(
            f'<b>Твой уровень: {current_level}\n🆙 Ты можешь его повысить!</b>\n\n<i>При повышении уровня обнуляются очки и объекты, но шанс приняться и КД становятся меньше, и ещё будут объекты получше</i>',
            parse_mode='HTML', reply_markup=kb.level_up)
    else:
        level_info = await rq.about_level_updating(message.from_user.id)
        states = ['❌', '✅']
        await message.reply(
            f'<b>Твой уровень: {current_level}\n🚫 Ты пока не можешь его повысить</b>\n\n{states[level_info["object_status"]]} Руфанул {html.escape(level_info["object_req"])}\n{states[level_info["xp_status"]]} Есть {level_info["xp_req"]} очков',
            parse_mode='HTML')


@router.callback_query(F.data == 'level')
async def level_up(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await check_callback_prerequisites(callback):
        return
    if not await rq.update_level(callback.from_user.id):
        await callback.message.reply("🔒 Условия повышения ещё не выполнены. Проверь /level.")
        return
    user_info = await rq.get_user_info(callback.from_user.id)
    await callback.message.reply(
        f"<b>Твой уровень повышен!</b>\nТеперь твой уровень: {user_info['level']}",
        parse_mode="HTML",
    )



@router.callback_query(F.data == 'stats')
async def cb_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await check_callback_prerequisites(callback):
        return
    await rq.set_user(callback.from_user.id, callback.from_user.full_name)
    if callback.message.chat.type in ('group', 'supergroup'):
        await rq.set_chat(callback.message.chat.id, callback.message.chat.title or callback.from_user.full_name)
    user_info = await rq.get_user_info(callback.from_user.id)
    await callback.message.reply(
        profile(callback.from_user.first_name, user_info),
        parse_mode='HTML')


# Промокоды
@router.message(Command('promo'))
async def promo_use(message: Message) -> None:
    await setup_user_and_chat(message)
    if not await check_prerequisites(message): return
    promo_code = message.text.split()[1].upper() if len(message.text.split()) > 1 else 'empty'
    result = await rq.use_promo(message.from_user.id, promo_code)
    await message.reply(result, parse_mode='HTML')



