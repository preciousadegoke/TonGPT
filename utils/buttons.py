from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_buttons() -> InlineKeyboardMarkup:
    """
    Main action buttons for TonGPT homepage or default reply.
    """
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🚀 Scan Memecoins", callback_data="scan"),
        InlineKeyboardButton("🐳 Whale Watch", callback_data="whale"),
        InlineKeyboardButton("🧠 Trending", callback_data="trending"),
        InlineKeyboardButton("🌾 STON Yield", callback_data="ston"),
    )
    markup.add(
        InlineKeyboardButton("👛 Wallet Tracker", callback_data="wallet"),
        InlineKeyboardButton("⚡ Alerts", callback_data="alerts"),
        InlineKeyboardButton("💳 Subscribe", callback_data="subscribe"),
    )
    return markup


def subscribe_buttons() -> InlineKeyboardMarkup:
    """
    Subscription plan buttons.
    """
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🥉 Starter (0.8 TON)", callback_data="sub_starter"),
        InlineKeyboardButton("🥈 Pro (3 TON)", callback_data="sub_pro"),
        InlineKeyboardButton("🥇 Pro+ (6 TON)", callback_data="sub_proplus"),
        InlineKeyboardButton("👑 Elite (10 TON)", callback_data="sub_elite"),
    )
    markup.add(
        InlineKeyboardButton("🔁 Pricing & Add-ons", callback_data="pricing"),
        InlineKeyboardButton("🎯 Lifetime (18 TON)", callback_data="sub_lifetime")
    )
    return markup


def wallet_action_buttons(address: str) -> InlineKeyboardMarkup:
    """
    Buttons for wallet-specific actions.
    """
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_wallet:{address}"),
        InlineKeyboardButton("🔔 Set Alert", callback_data=f"alert_wallet:{address}"),
        InlineKeyboardButton("❌ Unfollow", callback_data=f"unfollow_wallet:{address}")
    )
    return markup


def referral_button(ref_link: str) -> InlineKeyboardMarkup:
    """
    Referral invite button with custom link.
    """
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🤝 Invite & Earn", url=ref_link))
    return markup


def back_to_menu_button() -> InlineKeyboardMarkup:
    """
    Single button to return to main menu.
    """
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu"))
    return markup

