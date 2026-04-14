"""
Inline keyboard button utilities for TonGPT (using aiogram 3.x).
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_buttons() -> InlineKeyboardMarkup:
    """
    Main action buttons for TonGPT homepage or default reply.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚀 Scan Memecoins", callback_data="scan"),
        InlineKeyboardButton(text="🐳 Whale Watch", callback_data="whale"),
    )
    builder.row(
        InlineKeyboardButton(text="🧠 Trending", callback_data="trending"),
        InlineKeyboardButton(text="🌾 STON Yield", callback_data="ston"),
    )
    builder.row(
        InlineKeyboardButton(text="👛 Wallet Tracker", callback_data="wallet"),
        InlineKeyboardButton(text="⚡ Alerts", callback_data="alerts"),
        InlineKeyboardButton(text="💳 Subscribe", callback_data="subscribe"),
    )
    return builder.as_markup()


def subscribe_buttons() -> InlineKeyboardMarkup:
    """
    Subscription plan buttons.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🥉 Starter (0.8 TON)", callback_data="sub_starter"),
        InlineKeyboardButton(text="🥈 Pro (3 TON)", callback_data="sub_pro"),
    )
    builder.row(
        InlineKeyboardButton(text="🥇 Pro+ (6 TON)", callback_data="sub_proplus"),
        InlineKeyboardButton(text="👑 Elite (10 TON)", callback_data="sub_elite"),
    )
    builder.row(
        InlineKeyboardButton(text="🔁 Pricing & Add-ons", callback_data="pricing"),
        InlineKeyboardButton(text="🎯 Lifetime (18 TON)", callback_data="sub_lifetime"),
    )
    return builder.as_markup()


def wallet_action_buttons(address: str) -> InlineKeyboardMarkup:
    """
    Buttons for wallet-specific actions.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Refresh", callback_data=f"refresh_wallet:{address}"),
        InlineKeyboardButton(text="🔔 Set Alert", callback_data=f"alert_wallet:{address}"),
        InlineKeyboardButton(text="❌ Unfollow", callback_data=f"unfollow_wallet:{address}"),
    )
    return builder.as_markup()


def referral_button(ref_link: str) -> InlineKeyboardMarkup:
    """
    Referral invite button with custom link.
    """
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🤝 Invite & Earn", url=ref_link))
    return builder.as_markup()


def back_to_menu_button() -> InlineKeyboardMarkup:
    """
    Single button to return to main menu.
    """
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu"))
    return builder.as_markup()
