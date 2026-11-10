from aiogram import Router
from bot.routers import game, admin, shop, panel

router = Router()
router.include_routers(panel.router, game.router, admin.router, shop.router)
