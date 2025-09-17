"""Константы оформления."""

EMOJI_PROFILE = "👤"
EMOJI_GIRL = "👧"
EMOJI_COIN = "🪙"
EMOJI_MORALE = "😊"
EMOJI_CLEAN = "🧽"
EMOJI_COMFORT = "🛏️"
EMOJI_HYGIENE = "🧼"
EMOJI_SECURITY = "🛡️"
EMOJI_ALLURE = "✨"
EMOJI_MARKET = "🛒"
EMOJI_OK = "✅"
EMOJI_X = "❌"
EMOJI_HEART = "❤️"
EMOJI_ENERGY = "⚡"
EMOJI_LUST = "🔥"
EMOJI_SPARK = "🌟"
EMOJI_STAT_VIT = "💪"
EMOJI_STAT_END = "🏃"
EMOJI_TRAIT = "🎯"
EMOJI_ROOMS = "🚪"
EMOJI_POPULARITY = "📣"
EMOJI_FACILITY = "🏢"
EMOJI_BODY = "🗿"
EMOJI_DIMENSION = "📏"

FACILITY_INFO = {
    "comfort": ("Комфорт", "Улучшает восстановление и настроение"),
    "hygiene": ("Гигиена", "Снижает падение чистоты и риск травм"),
    "security": ("Безопасность", "Уменьшает шанс травм"),
    "allure": ("Привлекательность", "Повышает награды за задания"),
}

EMBED_SPACER = "\u2003"

__all__ = [name for name in globals().keys() if name.startswith("EMOJI_")] + ["FACILITY_INFO", "EMBED_SPACER"]
