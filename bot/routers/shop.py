import html
import logging
import time

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
import bot.keyboards as kb
import database.requests as rq
from bot.common import setup_user_and_chat, ensure_user, check_prerequisites, check_callback_prerequisites, notify_admins
from bot.limits import support_limiter


router = Router()


def format_left(expires: float) -> str:
    hours = max(0.0, expires - time.time()) / 3600
    return f'{hours:.1f} ч.' if hours < 48 else f'{hours / 24:.1f} дн.'


@router.message(Command('buy'))
async def command_buy(message: Message) -> None:
    await setup_user_and_chat(message)
    if not await check_prerequisites(message, allow_private=True):
        return
    await message.reply('🛍 Магазин усилений\n\nСрок действия указан в описании товара. '
                        'Уже купленное усиление можно продлить — срок сложится.\n'
                        'Оплата: Telegram Stars ⭐\nПроблемы с оплатой: /paysupport\n\nВыбери предмет:',
                        reply_markup=await kb.shop())


@router.callback_query(F.data.startswith('buy_'))
async def buy_item(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await check_callback_prerequisites(callback, allow_private=True):
        return
    await ensure_user(callback.from_user)
    item = callback.data[4:]
    item_config = await rq.get_item(item)
    if not item_config or not item_config['available']:
        await callback.message.answer('Этот предмет больше не продаётся. Открой /buy.')
        return
    owned = await rq.user_items(callback.from_user.id)
    hours = f"{item_config['duration'] / 3600:g} ч."
    if item_config['key'] in owned:
        description = (f"Продление: +{hours} к текущему сроку "
                       f"(сейчас осталось {format_left(owned[item_config['key']])}).\n{item_config['description']}")
    else:
        description = f"{item_config['description']}\nДействует {hours} после покупки."
    await callback.message.answer_invoice(
        title=item_config['name'][:32],
        description=description[:255],
        payload=item_config['key'],
        currency='XTR',
        prices=[LabeledPrice(label=item_config['name'], amount=item_config['price'])],
        reply_markup=kb.buy
    )


@router.pre_checkout_query()
async def pre_checkout_query(pcq: PreCheckoutQuery) -> None:
    item = await rq.get_item(pcq.invoice_payload)
    valid = bool(item and item['available'] and pcq.currency == 'XTR' and pcq.total_amount == item['price'])
    await pcq.answer(ok=valid, error_message=None if valid else 'Товар или сумма изменились. Открой /buy заново.')


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    user = message.from_user
    try:
        await rq.set_user(user.id, user.full_name)
        expires = await rq.fulfill_payment(user.id, payment)
    except Exception:
        # Деньги списаны, а выдать товар нельзя: возвращаем Stars, а не молча теряем оплату.
        logging.exception('Не удалось выдать оплаченный товар, charge_id=%s', payment.telegram_payment_charge_id)
        try:
            await message.bot.refund_star_payment(user_id=user.id,
                                                  telegram_payment_charge_id=payment.telegram_payment_charge_id)
            refunded = True
        except TelegramAPIError:
            logging.exception('Не удалось вернуть Stars, charge_id=%s', payment.telegram_payment_charge_id)
            refunded = False
        await message.answer('⚠️ Не получилось выдать товар. ' + (
            'Stars возвращены на твой счёт.' if refunded else
            'Мы уже знаем о проблеме и вернём Stars вручную. Если что — /paysupport'))
        await notify_admins(message.bot, (
            f'⚠️ Оплата не выдана, возврат: {"выполнен" if refunded else "НЕ выполнен"}\n'
            f'Пользователь: {user.id} ({user.full_name})\nТовар: {payment.invoice_payload}\n'
            f'Сумма: {payment.total_amount} {payment.currency}\n'
            f'charge_id: {payment.telegram_payment_charge_id}'
            + ('' if refunded else f'\nВернуть вручную: /refund {payment.telegram_payment_charge_id} {user.id}')))
        return
    if not expires:
        return  # повторная доставка уже обработанного платежа
    item = await rq.get_item(payment.invoice_payload)
    name = item['name'] if item else payment.invoice_payload
    await message.answer(f"✅ Оплата прошла успешно!\nТовар: {name}\nСумма: {payment.total_amount} ⭐️\n"
                         f"Действует ещё {format_left(expires)}")


@router.message(Command('paysupport'))
async def pay_support(message: Message, command: CommandObject) -> None:
    """Обязательная по правилам Telegram команда поддержки по платежам Stars."""
    user = message.from_user
    if not command.args:
        await message.reply('💬 Поддержка по оплатам\n\nОпиши проблему одним сообщением:\n'
                            '/paysupport оплатил рюкзак, но он не появился\n\n'
                            'Обращение получит администратор и ответит в личке. '
                            'Если товар не выдан, Stars вернём.')
        return
    wait = support_limiter.hit(user.id)
    if wait:
        await message.reply(f'Ты уже отправил несколько обращений. Попробуй через {int(wait // 60) + 1} мин.')
        return
    payments = await rq.user_payments(user.id)
    history = '\n'.join(
        f"• {p['item_key']} · {p['amount']} ⭐ · {time.strftime('%d.%m %H:%M', time.gmtime(p['created_at']))} UTC"
        f"{' · возвращён' if p['refunded'] else ''}\n  <code>{html.escape(p['charge_id'])}</code>"
        for p in payments) or 'нет платежей в базе'
    await notify_admins(message.bot, (
        f'🆘 <b>/paysupport</b> от {html.escape(user.full_name)} (<code>{user.id}</code>'
        f'{", @" + html.escape(user.username) if user.username else ""})\n\n'
        f'{html.escape(command.args[:1500])}\n\n<b>Последние платежи:</b>\n{history}\n\n'
        'Возврат: /refund CHARGE_ID'), parse_mode='HTML')
    await message.reply('✅ Обращение отправлено. Администратор ответит в личке — '
                        'проверь, что у тебя открыт чат с ботом.')
