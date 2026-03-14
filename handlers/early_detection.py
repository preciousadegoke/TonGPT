# handlers/early_detection.py - FIXED for aiogram 3.x (C-4)
from aiogram import Router, types
from aiogram.filters import Command
from utils.scanner import scan_early_signals, get_combined_scan, analyze_token_details, get_system_status
import logging

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("early_scan"))
async def early_scan_command(message: types.Message):
    """
    Handler for /early_scan command - shows early memecoin detections
    """
    try:
        await message.reply("🔍 Scanning for early memecoin signals...")

        # Get early signals
        early_tokens = await scan_early_signals(hours_back=12, min_confidence=0.5)

        if not early_tokens:
            await message.reply("📊 No early signals detected in the last 12 hours.")
            return

        # Format response
        response = "🚀 **EARLY MEMECOIN SIGNALS**\n\n"

        for i, token in enumerate(early_tokens[:10], 1):
            confidence_val = token.get('confidence', '0%')
            if isinstance(confidence_val, str):
                confidence_num = float(confidence_val.rstrip('%'))
            else:
                confidence_num = float(confidence_val) * 100
            confidence_emoji = "🟢" if confidence_num > 70 else "🟡"
            risk_emoji = {"low": "✅", "medium": "⚠️", "high": "🚨"}.get(token.get('risk_level', ''), "❓")

            response += f"{i}. **{token.get('symbol', 'N/A')}** ({token.get('name', 'Unknown')})\n"
            response += f"   {confidence_emoji} Confidence: {confidence_val}\n"
            response += f"   {risk_emoji} Risk: {token.get('risk_level', 'unknown')}\n"
            response += f"   💰 Liquidity: {token.get('liquidity', 'N/A')}\n"
            response += f"   🏪 DEX: {token.get('dex', 'N/A')}\n\n"

        response += f"📈 Found {len(early_tokens)} early signals\n"
        response += "Use /analyze <symbol> for detailed analysis"

        await message.reply(response, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in early_scan_command: {e}")
        await message.reply("❌ Error scanning for early signals. Please try again.")


@router.message(Command("combined_scan"))
async def combined_scan_command(message: types.Message):
    """
    Handler for /combined_scan - shows both trending and early signals
    """
    try:
        await message.reply("📊 Getting trending tokens and early signals...")

        # Get combined data
        scan_data = await get_combined_scan(trending_limit=5, early_limit=8, min_confidence=0.4)

        if scan_data.get('summary', {}).get('error'):
            await message.reply(f"❌ Scan error: {scan_data['summary']['error']}")
            return

        response = "🔥 **COMBINED MEMECOIN SCAN**\n\n"

        # Trending section
        trending = scan_data.get('trending', [])
        if trending:
            response += "📈 **TRENDING NOW:**\n"
            for i, token in enumerate(trending[:5], 1):
                response += f"{i}. **{token.get('symbol', 'N/A')}** - {token.get('name', 'Unknown')}\n"
                response += f"   📊 Volume: {token.get('volume', 'N/A')}\n"
                response += f"   💧 LP: {token.get('lp', 'N/A')}\n\n"

        # Early signals section
        early = scan_data.get('early_signals', [])
        if early:
            response += "🚀 **EARLY SIGNALS:**\n"
            for i, token in enumerate(early[:5], 1):
                confidence_val = token.get('confidence', '0%')
                if isinstance(confidence_val, str):
                    confidence_num = float(confidence_val.rstrip('%'))
                else:
                    confidence_num = float(confidence_val) * 100
                confidence_emoji = "🟢" if confidence_num > 60 else "🟡"
                response += f"{i}. **{token.get('symbol', 'N/A')}** - {token.get('name', 'Unknown')}\n"
                response += f"   {confidence_emoji} {confidence_val} confidence\n"
                response += f"   💰 {token.get('liquidity', 'N/A')} liquidity\n\n"

        summary = scan_data.get('summary', {})
        response += f"📋 **SUMMARY:** {summary.get('trending_count', 0)} trending, "
        response += f"{summary.get('early_signals_count', 0)} early signals"

        await message.reply(response, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in combined_scan_command: {e}")
        await message.reply("❌ Error running combined scan. Please try again.")


@router.message(Command("analyze"))
async def analyze_command(message: types.Message):
    """
    Handler for /analyze <token> - detailed token analysis
    """
    try:
        if not message.text:
            await message.reply("Usage: /analyze <symbol or address>\nExample: /analyze DOGS or /analyze EQBx...")
            return

        command_text = message.text.replace("/analyze", "", 1).strip()
        args = command_text.split() if command_text else []

        if not args:
            await message.reply("Usage: /analyze <symbol or address>\nExample: /analyze DOGS or /analyze EQBx...")
            return

        token_input = args[0].upper()
        await message.reply(f"🔍 Analyzing {token_input}...")

        analysis = await analyze_token_details(token_input)

        if not analysis:
            await message.reply(f"❌ Token {token_input} not found in trending or early detection data.")
            return

        token_data = analysis.get('analysis', {})
        is_early = analysis.get('is_early_detection', False)

        response = f"🔬 **ANALYSIS: {token_data.get('symbol', 'Unknown')}**\n\n"
        response += f"📛 **Name:** {token_data.get('name', 'Unknown')}\n"

        if is_early:
            # Early detection analysis
            response += f"🚀 **Early Detection:** Yes\n"
            confidence_score = token_data.get('confidence_score', 0)
            response += f"🎯 **Confidence:** {confidence_score*100:.1f}%\n"
            response += f"⚠️ **Risk Level:** {token_data.get('risk_level', 'unknown')}\n"
            response += f"🏪 **DEX:** {token_data.get('dex', 'Unknown')}\n"
            response += f"💰 **Initial Liquidity:** ${token_data.get('initial_liquidity', 0):,.0f}\n"
            response += f"📅 **First Detected:** {token_data.get('first_detected', 'Unknown')}\n"
            response += f"🔍 **Detection Method:** {token_data.get('detection_method', 'Unknown')}\n"

            if token_data.get('is_memecoin'):
                response += f"🐕 **Memecoin Characteristics:** Detected\n"
        else:
            # Trending token analysis
            response += f"📈 **Status:** Trending\n"
            response += f"💵 **Price:** ${token_data.get('price', 0):.6f}\n"
            response += f"📊 **24h Volume:** ${token_data.get('volume_24h', 0):,.0f}\n"
            response += f"📈 **24h Change:** {token_data.get('price_change_24h', 0):+.1f}%\n"
            response += f"💎 **Market Cap:** ${token_data.get('market_cap', 0):,.0f}\n"

        response += f"\n🔗 **Address:** `{token_data.get('address', 'N/A')}`"

        await message.reply(response, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in analyze_command: {e}")
        await message.reply("❌ Error analyzing token. Please try again.")


@router.message(Command("system_status"))
async def system_status_command(message: types.Message):
    """
    Handler for /system_status - check system health
    """
    try:
        await message.reply("⚙️ Checking system status...")

        status = await get_system_status()

        response = "🔧 **SYSTEM STATUS**\n\n"

        # Overall status
        status_emoji = {"healthy": "🟢", "partial": "🟡", "error": "🔴"}.get(status.get('combined_status'), "❓")
        response += f"{status_emoji} **Overall Status:** {status.get('combined_status', 'unknown')}\n\n"

        # Trending system
        trending = status.get('trending_system', {})
        trending_emoji = "🟢" if trending.get('status') == 'working' else "🔴"
        response += f"{trending_emoji} **Trending System:** {trending.get('status', 'unknown')}\n"
        response += f"   📊 Active tokens: {trending.get('token_count', 0)}\n\n"

        # Early detection system
        early = status.get('early_detection_system', {})
        early_emoji = "🟢" if early.get('status') == 'working' else "🔴"
        response += f"{early_emoji} **Early Detection:** {early.get('status', 'unknown')}\n"
        response += f"   🗄️ Database: {'Connected' if early.get('database_connected') else 'Error'}\n"
        response += f"   🧠 Text Analysis: {'spaCy' if early.get('spacy_available') else 'Basic'}\n"

        if status.get('timestamp'):
            response += f"\n🕒 **Last Update:** {status['timestamp']}"

        if status.get('error'):
            response += f"\n❌ **Error:** {status['error']}"

        await message.reply(response, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in system_status_command: {e}")
        await message.reply("❌ Error checking system status.")


# Registration function for main.py
def register_early_detection_handlers(dp, ctx=None):
    """Register all early detection handlers with the dispatcher"""
    dp.include_router(router)