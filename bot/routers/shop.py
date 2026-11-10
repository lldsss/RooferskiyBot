from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
import bot.keyboards as kb
import database.requests as rq
from bot.common import setup_user_and_chat


router = Router()

@router.message(Command('buy'))
async def command_buy(message: Message) -> None:
    await setup_user_and_chat(message)
    await message.reply('🛍 Магазин усилений\n\nСрок действия указан в описании товара.\nОплата: Telegram Stars ⭐\n\nВыбери предмет:', reply_markup=await kb.shop())


@router.callback_query(F.data.startswith('buy_'))
async def buy_item(callback: CallbackQuery) -> None:
    await callback.answer()
    await rq.set_user(callback.from_user.id, callback.from_user.full_name)
    item = callback.data[4:]
    item_config = await rq.get_item(item)
    if not item_config or not item_config['available']:
        await callback.message.answer('Этот предмет больше не продаётся. Открой /buy.')
        return
    user_items = await rq.user_items(callback.from_user.id)
    if item in user_items or item_config['name'] in user_items:
        await callback.message.answer(f"У тебя уже есть {item_config['name']}.")
        return
    await callback.message.answer_invoice(
        title=item_config['name'],
        description=f"{item_config['description']}\nДействует {item_config['duration'] / 3600:g} ч. после покупки.",
        payload=item_config['key'],
        currency='XTR',
        prices=[LabeledPrice(label=item_config['name'], amount=item_config['price'])],
        reply_markup=kb.buy
    )


@router.pre_checkout_query()
async def pre_checkout_query(pcq: PreCheckoutQuery) -> None:
    item = await rq.get_item(pcq.invoice_payload)
    owned = await rq.user_items(pcq.from_user.id)
    valid = bool(item and item['available'] and item['key'] not in owned and item['name'] not in owned and pcq.currency == 'XTR' and pcq.total_amount == item['price'])
    await pcq.answer(ok=valid, error_message=None if valid else 'Товар или сумма изменились. Открой /buy заново.')


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment_info = message.successful_payment
    await rq.set_user(message.from_user.id, message.from_user.full_name)
    if not await rq.fulfill_payment(message.from_user.id, payment_info):
        return
    item = await rq.get_item(payment_info.invoice_payload)
    await message.answer(
        f"✅ Оплата прошла успешно!\nТовар: {item['name']}\nСумма: {payment_info.total_amount} ⭐️")


# Дополнительные обработчики
