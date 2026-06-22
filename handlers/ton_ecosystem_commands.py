from aiogram import Dispatcher, types
from aiogram.filters import Command
import logging

logger = logging.getLogger(__name__)

async def defi_command(message: types.Message):
    """Show TON DeFi ecosystem overview"""
    reply = """🔄 <b>TON DeFi Ecosystem</b>

<b>🏦 Major DEXs:</b>
• <b>STON.fi</b> - Leading AMM DEX
• <b>DeDust</b> - Advanced trading features
• <b>Megaton</b> - Multi-chain DEX

<b>💰 Lending & Staking:</b>
• <b>Tonstakers</b> - Liquid staking (stTON)
• <b>Evaa Protocol</b> - Lending protocol
• <b>Aqua Protocol</b> - Yield farming

<b>🌉 Bridges:</b>
• <b>TON Bridge</b> - Official Ethereum bridge
• <b>Orbit Bridge</b> - Multi-chain bridge

<b>💎 Key Metrics:</b>
Use /scan to see current token prices and volumes.

<b>⚠️ Safety Tips:</b>
• Always verify contract addresses
• Check for audits before investing
• Start with small amounts
• Never invest more than you can afford to lose
"""
    await message.answer(reply, parse_mode="HTML", disable_web_page_preview=True)

async def wallets_command(message: types.Message):
    """Show TON wallet information"""
    reply = """💼 <b>TON Wallets Guide</b>

<b>📱 Mobile Wallets:</b>
• <b>Tonkeeper</b> - Most popular, user-friendly
• <b>Telegram Wallet</b> - Integrated in Telegram
• <b>TON Wallet</b> - Official wallet

<b>💻 Desktop/Web:</b>
• <b>Tonkeeper Extension</b> - Chrome/Firefox
• <b>MyTonWallet</b> - Web-based wallet
• <b>OpenMask</b> - Browser extension

<b>🔧 Developer Tools:</b>
• <b>TON Connect</b> - For dApp integration
• <b>TonLib</b> - Low-level library
• <b>TON SDK</b> - Development toolkit

<b>🔐 Security Best Practices:</b>
• Always backup your seed phrase (24 words)
• Never share your private keys
• Use official app stores only
• Enable PIN/biometric protection
• Verify wallet addresses before sending

<b>🎯 For Beginners:</b>
Start with Tonkeeper - it's the most beginner-friendly option!
"""
    await message.answer(reply, parse_mode="HTML", disable_web_page_preview=True)

async def nft_command(message: types.Message):
    """Show TON NFT ecosystem"""
    reply = """🎨 <b>TON NFT Ecosystem</b>

<b>🏪 Major Marketplaces:</b>
• <b>Getgems</b> - Leading NFT marketplace
• <b>Fragment</b> - Telegram usernames auction
• <b>Disintar</b> - NFT platform
• <b>TON Diamonds</b> - Premium collectibles

<b>🎮 Gaming & Metaverse:</b>
• <b>Fanzee</b> - Sports NFTs
• <b>TON Play</b> - Gaming ecosystem
• <b>Various P2E games</b> in development

<b>🏷️ TON DNS:</b>
• Get your .ton domain
• Use for wallet addresses
• Decentralized naming system

<b>💡 Popular Collections:</b>
• TON Punks
• Anonymous Telegram Numbers
• Fragment Usernames
• Various art collections

<b>📈 Trading Tips:</b>
• Research project backgrounds
• Check trading volumes
• Verify authenticity on official platforms
• Understand royalty structures
"""
    await message.answer(reply, parse_mode="HTML", disable_web_page_preview=True)

async def development_command(message: types.Message):
    """Show TON development resources"""
    reply = """👨‍💻 <b>TON Development Guide</b>

<b>🔧 Programming Languages:</b>
• <b>FunC</b> - Smart contract language
• <b>Fift</b> - Low-level operations
• <b>JavaScript/TypeScript</b> - Web development
• <b>Python</b> - Backend development

<b>🛠️ Development Tools:</b>
• <b>ton-cli</b> - Command line interface
• <b>Blueprint</b> - Smart contract framework
• <b>TON IDE</b> - Online development environment
• <b>VS Code Extensions</b> - FunC syntax support

<b>📚 Key Resources:</b>
• <b>docs.ton.org</b> - Official documentation
• <b>ton.org/dev</b> - Developer portal
• <b>GitHub</b> - TON repositories
• <b>TON Dev Chat</b> - Developer community

<b>🏗️ Building on TON:</b>
• Smart contracts (FunC)
• Telegram Mini Apps
• Web3 dApps with TON Connect
• NFT projects
• DeFi protocols

<b>💰 Grants & Support:</b>
• TON Foundation grants
• Hackathons and competitions
• Developer community support

<b>🚀 Getting Started:</b>
1. Learn FunC basics
2. Set up development environment
3. Deploy test contracts
4. Join developer communities
"""
    await message.answer(reply, parse_mode="HTML", disable_web_page_preview=True)

async def mining_command(message: types.Message):
    """Show TON mining and staking info"""
    reply = """⛏️ <b>TON Mining & Staking</b>

<b>🏗️ TON Consensus:</b>
• <b>Proof-of-Stake</b> (not mineable like Bitcoin)
• <b>Validators</b> secure the network
• <b>Nominators</b> delegate stake to validators

<b>💰 Staking Requirements:</b>
• <b>Validator:</b> 300,000+ TON minimum
• <b>Nominator:</b> 10,000+ TON typically
• <b>Liquid Staking:</b> Any amount (stTON)

<b>📊 Staking Rewards:</b>
• <b>Current APY:</b> ~5-8% (varies)
• <b>Liquid staking:</b> ~4-6% APY
• <b>Lock period:</b> ~36 hours for unstaking

<b>🌊 Liquid Staking Options:</b>
• <b>Tonstakers (stTON)</b> - Most popular
• <b>Hipo Finance</b> - Alternative option
• <b>bemo (stTON)</b> - Another protocol

<b>⚡ Alternative "Mining":</b>
• <b>TON Storage</b> - Earn by providing storage
• <b>TON Proxy</b> - Earn by providing bandwidth
• <b>Running infrastructure</b> nodes

<b>🎯 For Beginners:</b>
Consider liquid staking (Tonstakers) - no minimum, instant liquidity!

<i>Remember: TON moved away from mining to be more eco-friendly!</i>
"""
    await message.answer(reply, parse_mode="HTML", disable_web_page_preview=True)

async def security_command(message: types.Message):
    """Show security best practices"""
    reply = """🔒 <b>TON Security Guide</b>

<b>🔐 Wallet Security:</b>
• <b>Seed Phrase:</b> Write down 24 words, store safely
• <b>Never share:</b> Private keys or seed phrases
• <b>Official sources:</b> Download wallets from official sites only
• <b>Hardware security:</b> Consider hardware wallets for large amounts

<b>🚨 Common Scams:</b>
• <b>Fake support:</b> Admins never DM first
• <b>Phishing sites:</b> Always verify URLs
• <b>Fake airdrops:</b> Too good to be true offers
• <b>Impersonation:</b> Fake telegram channels/bots

<b>🔍 Before Using DeFi:</b>
• <b>Verify contracts:</b> Check on ton.cx or tonscan.org
• <b>Audit reports:</b> Look for security audits
• <b>Community feedback:</b> Research project reputation
• <b>Start small:</b> Test with small amounts first

<b>✅ Safe Practices:</b>
• <b>Double-check addresses</b> before sending
• <b>Use official links</b> from verified sources
• <b>Enable notifications</b> for transactions
• <b>Keep software updated</b>

<b>🆘 If Something Goes Wrong:</b>
• <b>Don't panic</b> - transactions are irreversible
• <b>Document everything</b> - transaction hashes, screenshots
• <b>Report scams</b> to relevant platforms
• <b>Learn from experience</b> - review what happened

<b>🎯 Golden Rule:</b>
<i>If something seems too good to be true, it probably is!</i>
"""
    await message.answer(reply, parse_mode="HTML", disable_web_page_preview=True)

async def help_command(message: types.Message):
    """Enhanced help command with all features"""
    reply = """🤖 <b>TonGPT - Your TON Ecosystem Assistant</b>

<b>📊 Market Commands:</b>
/scan - View trending TON tokens and prices
/defi - TON DeFi ecosystem overview

<b>🎯 TON Ecosystem:</b>
/wallets - TON wallet guide and recommendations
/nft - NFT marketplaces and collections
/dev - Development resources and tools
/mining - Staking, validation, and earning TON
/security - Security best practices and scam prevention

<b>💬 Smart Chat:</b>
Just ask me anything about:
• TON blockchain and technology
• Telegram integration and Mini Apps
• DeFi protocols and trading
• NFTs and digital collectibles
• Crypto fundamentals and Web3
• Development and programming
• Market analysis and trends

<b>🔥 Examples:</b>
"How do I start developing on TON?"
"What's the difference between staking and liquid staking?"
"How do I safely use TON DeFi protocols?"
"Explain TON Connect integration"
"What are the best TON wallets?"

<b>⚡ Features:</b>
• Real-time market data integration
• Comprehensive TON ecosystem knowledge
• Security-focused recommendations
• Beginner to advanced guidance
• Conversation memory for context

<i>Ask me anything about TON, crypto, or blockchain - I'm here to help! 🚀</i>
"""
    await message.answer(reply, parse_mode="HTML", disable_web_page_preview=True)

def register_ecosystem_commands(dp: Dispatcher, config=None, gpt_handler=None):
    """Register all TON ecosystem command handlers"""
    
    @dp.message(Command(commands=["defi"]))
    async def cmd_defi(message: types.Message):
        await defi_command(message)
    
    @dp.message(Command(commands=["wallets"]))
    async def cmd_wallets(message: types.Message):
        await wallets_command(message)
    
    @dp.message(Command(commands=["nft", "nfts"]))
    async def cmd_nft(message: types.Message):
        await nft_command(message)
    
    @dp.message(Command(commands=["dev", "development", "build"]))
    async def cmd_development(message: types.Message):
        await development_command(message)
    
    @dp.message(Command(commands=["mining", "staking", "stake"]))
    async def cmd_mining(message: types.Message):
        await mining_command(message)
    
    @dp.message(Command(commands=["security", "safety", "scam"]))
    async def cmd_security(message: types.Message):
        await security_command(message)
    
    @dp.message(Command(commands=["help", "start"]))
    async def cmd_help(message: types.Message):
        await help_command(message)
    
    logger.info("✅ TON ecosystem commands registered successfully")