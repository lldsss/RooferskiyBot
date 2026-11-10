from html import escape
from math import ceil


def profile(name, info):
    return (f"📊 <b>{escape(name)}</b>\n\n"
            f"🏅 Уровень: <b>{info['level']}</b>\n"
            f"⭐ Очки: <b>{info['xp']}</b>\n\n"
            "Следующая цель — /level")


def cooldown(seconds):
    minutes, seconds = divmod(max(0, ceil(seconds)), 60)
    return f"⏳ <b>Время на отдых</b>\n\nСледующий руф через {minutes} мин {seconds} с."
