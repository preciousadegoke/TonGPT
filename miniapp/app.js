/**
 * TonGPT MiniApp Logic
 * Modular class-based structure for better maintenance and code quality.
 */

// Global Config
const CONFIG = {
    API_BASE: '/api',
    ANIMATION_DURATION: 300,
    TOAST_DURATION: 3000
};

// Safe Telegram Init
const tg = window.Telegram?.WebApp || {
    expand: () => { },
    HapticFeedback: { impactOccurred: () => console.log('[Mock] Haptic') },
    initDataUnsafe: { user: { id: 123456789, first_name: 'Demo User' } },
    isExpanded: true
};

class TonGPTApp {
    constructor() {
        this.state = {
            currentView: 'scan',
            loading: false,
            memecoins: [],
            premium: null,
            wallet: null,
            lastUpdate: null
        };

        this.tonConnectUI = null;
        this.init();
    }

    async init() {
        this.expandApp();
        await this.initTonConnect();
        this.setupEventListeners();

        // Initial Fetch
        this.checkPremiumStatus();
        this.loadView(this.state.currentView);
    }

    expandApp() {
        try {
            tg.expand();
            tg.ready();
        } catch (e) {
            console.error('TG Init Error:', e);
        }
    }

    // --- Wallet & Auth ---
    async initTonConnect() {
        try {
            this.tonConnectUI = new TON_CONNECT_UI.TonConnectUI({
                manifestUrl: window.location.origin + '/miniapp/tonconnect-manifest.json',
                buttonRootId: 'ton-connect-button'
            });

            this.tonConnectUI.onStatusChange(wallet => this.handleWalletChange(wallet));

            // Check initial state
            if (this.tonConnectUI.account) {
                this.handleWalletChange(this.tonConnectUI.account);
            }
        } catch (e) {
            console.error('TonConnect Error:', e);
            this.showToast('Failed to initialize wallet', 'error');
        }
    }

    async handleWalletChange(wallet) {
        this.state.wallet = wallet;
        this.updateWalletUI();

        if (wallet) {
            this.triggerHaptic('light');

            // Send proof to backend
            try {
                if (wallet.connectItems?.tonProof && wallet.connectItems.tonProof.proof) {
                    const proof = wallet.connectItems.tonProof.proof;
                    const account = wallet.account;

                    const payload = {
                        TelegramId: tg.initDataUnsafe?.user?.id || 0,
                        Address: account.address,
                        PublicKey: account.publicKey,
                        Proof: JSON.stringify(proof),
                        StateInit: account.walletStateInit
                    };

                    await this.apiCall('/wallet/auth', 'POST', payload);
                    this.showToast('Wallet Verified & Linked!', 'success');
                } else {
                    // Fallback for simple connection without proof (dev mode / non-standard wallets)
                    const payload = {
                        TelegramId: tg.initDataUnsafe?.user?.id || 0,
                        Address: wallet.account.address,
                        PublicKey: wallet.account.publicKey || '',
                        Proof: "SKIP_VERIFICATION_DEV",
                        StateInit: wallet.account.walletStateInit
                    };
                    await this.apiCall('/wallet/auth', 'POST', payload);
                    this.showToast('Wallet Connected!', 'success');
                }
            } catch (e) {
                console.error('Wallet Auth Failed:', e);
                this.showToast('Wallet connected but verification failed', 'error');
            }
        }
    }

    async toggleWallet() {
        this.triggerHaptic('medium');
        if (this.state.wallet) {
            await this.tonConnectUI.disconnect();
            this.state.wallet = null;
            this.updateWalletUI();
            this.showToast('Wallet Disconnected', 'info');
        } else {
            await this.tonConnectUI.openModal();
        }
    }

    updateWalletUI() {
        const btn = document.getElementById('wallet-connect-btn');
        const status = document.getElementById('wallet-status');

        if (this.state.wallet) {
            const addr = this.state.wallet.account.address;
            status.textContent = `${addr.slice(0, 4)}...${addr.slice(-4)}`;
            btn.classList.add('bg-green-500', 'bg-opacity-20', 'text-green-400');
        } else {
            status.textContent = 'Connect Wallet';
            btn.classList.remove('bg-green-500', 'bg-opacity-20', 'text-green-400');
        }
    }

    // --- API Service ---
    async apiCall(endpoint, method = 'GET', body = null) {
        try {
            const options = {
                method,
                headers: { 'Content-Type': 'application/json' }
            };
            if (body) options.body = JSON.stringify(body);

            const res = await fetch(`${CONFIG.API_BASE}${endpoint}`, options);
            if (!res.ok) throw new Error(`API Error: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error(`API Fail [${endpoint}]:`, e);
            // Fallback for demo
            if (endpoint.includes('memecoins')) return this.getMockMemecoins();
            throw e;
        }
    }

    getMockMemecoins() {
        return [
            { name: 'DOGEZ', symbol: 'DOGEZ', type: 'dog', price: 0.0045, change: '+12.5%', volume: '1.2M', holders: '5K' },
            { name: 'CATZ', symbol: 'CATZ', type: 'cat', price: 0.0032, change: '-3.2%', volume: '850K', holders: '3K' }
        ];
    }

    // --- Core Logic ---
    async checkPremiumStatus() {
        const userId = tg.initDataUnsafe?.user?.id;
        try {
            const data = await this.apiCall(`/user/status?telegram_id=${userId}`);
            this.state.premium = data;
        } catch (e) {
            this.state.premium = { is_premium: false, plan: 'Free' };
        }
    }

    async loadView(view) {
        this.state.currentView = view;
        this.updateNavHighlight();

        const main = document.getElementById('main-content');
        main.innerHTML = this.renderSkeleton(view); // Show Skeleton

        try {
            let content = '';
            switch (view) {
                case 'scan':
                    const coins = await this.apiCall('/memecoins');
                    this.state.memecoins = Array.isArray(coins) ? coins : coins.memecoins || [];
                    content = this.renderScanView();
                    break;
                case 'trending':
                    const trends = await this.apiCall('/trending');
                    content = this.renderTrendingView(trends);
                    break;
                case 'premium':
                    content = this.renderPremiumView();
                    break;
                default:
                    content = `<div class="p-8 text-center telegram-hint">Feature coming soon...</div>`;
            }

            // Artificial delay for smooth skeleton transition
            await new Promise(r => setTimeout(r, 400));

            main.innerHTML = content;
            this.setupViewInteractions();

        } catch (e) {
            main.innerHTML = this.renderErrorState(e.message);
            this.showToast('Failed to load data', 'error');
        }
    }

    // --- Rendering ---
    renderSkeleton(view) {
        return `
            <div class="p-4 space-y-4 fade-in">
                <div class="skeleton h-12 w-3/4 mx-auto mb-6"></div>
                <div class="skeleton h-32 w-full rounded-2xl"></div>
                <div class="skeleton h-24 w-full rounded-2xl"></div>
                <div class="skeleton h-24 w-full rounded-2xl"></div>
            </div>
        `;
    }

    renderScanView() {
        return `
            <div class="p-4 space-y-4 scene-3d fade-in">
                <div class="text-center mb-6 tilt-target">
                    <h1 class="text-3xl font-bold gradient-text tilt-inner">Market Scanner</h1>
                    <p class="telegram-hint text-sm">Real-time TON Ecosystem Data</p>
                </div>

                <!-- Memecoin List -->
                <div class="space-y-4">
                    ${this.state.memecoins.map((coin, i) => this.renderCoinCard(coin, i)).join('')}
                </div>
            </div>
        `;
    }

    renderCoinCard(coin, index) {
        const isUp = coin.change.includes('+');
        const colorClass = isUp ? 'text-green-400' : 'text-red-400';
        const icon = isUp ? '📈' : '📉';

        return `
            <div class="glass-morphism rounded-2xl p-4 card-3d stagger-${index % 3 + 1} flex items-center justify-between">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-full bg-white bg-opacity-5 flex items-center justify-center text-xl">
                        ${this.getTypeEmoji(coin.type)}
                    </div>
                    <div>
                        <div class="font-bold text-lg">${coin.symbol} <span class="text-xs telegram-hint">${coin.name}</span></div>
                        <div class="text-xs telegram-hint">Vol: ${coin.volume}</div>
                    </div>
                </div>
                <div class="text-right">
                    <div class="font-bold font-mono">${coin.price}</div>
                    <div class="text-sm ${colorClass} font-medium flex items-center justify-end gap-1">
                        ${icon} ${coin.change}
                    </div>
                </div>
            </div>
        `;
    }

    renderPremiumView() {
        const isPremium = this.state.premium?.is_premium;
        return `
            <div class="p-4 space-y-6 fade-in">
                <div class="glass-morphism rounded-2xl p-6 text-center card-3d border-t-2 ${isPremium ? 'border-green-500' : 'border-blue-500'}">
                    <div class="text-6xl mb-4 floating">${isPremium ? '👑' : '💎'}</div>
                    <h2 class="text-2xl font-bold mb-2">${isPremium ? 'Whale Hunter' : 'Free Plan'}</h2>
                    <p class="telegram-hint text-sm mb-6">${isPremium ? 'Your subscription is active.' : 'Upgrade to unlock real-time alerts.'}</p>
                    
                    ${!isPremium ? `
                        <button onclick="app.upgrade()" class="w-full telegram-button py-3 rounded-xl font-bold text-lg shadow-lg pulse-glow">
                            Upgrade Now (10 TON)
                        </button>
                    ` : `
                        <div class="p-3 bg-green-500 bg-opacity-10 rounded-xl text-green-400 font-bold">
                            Active until ${new Date(this.state.premium.expiry).toLocaleDateString()}
                        </div>
                    `}
                </div>
            </div>
        `;
    }

    // Placeholder for Trending View
    renderTrendingView(trends) {
        // Simple mock render if API fails or returns simple array
        return `
             <div class="p-4 space-y-4 fade-in">
                 <div class="text-center mb-6">
                    <h1 class="text-2xl font-bold gradient-text">Trending Pools</h1>
                 </div>
                 ${trends.map((pool, i) => `
                    <div class="glass-morphism rounded-xl p-4 card-3d stagger-${i % 3 + 1}">
                        <div class="flex justify-between items-center">
                            <span class="font-bold">${pool.pair || 'TON/USDT'}</span>
                            <span class="text-green-400 font-mono">${pool.apr || '12%'} APR</span>
                        </div>
                        <div class="mt-2 text-xs telegram-hint flex justify-between">
                            <span>TVL: ${pool.tvl || '$1M'}</span>
                            <span>Vol: ${pool.volume || '$500K'}</span>
                        </div>
                    </div>
                 `).join('')}
             </div>
        `;
    }

    renderErrorState(msg) {
        return `
            <div class="flex flex-col items-center justify-center h-64 text-center p-6 fade-in">
                <i class="fas fa-exclamation-triangle text-4xl text-red-400 mb-4"></i>
                <p class="text-lg font-medium mb-2">Oops!</p>
                <p class="telegram-hint text-sm">${msg}</p>
                <button onclick="app.init()" class="mt-6 px-6 py-2 glass-morphism rounded-full hover:bg-white hover:bg-opacity-10">Try Again</button>
            </div>
        `;
    }

    // --- Helpers ---
    getTypeEmoji(type) {
        const map = { dog: '🐶', cat: '🐱', frog: '🐸', rocket: '🚀' };
        return map[type] || '💎';
    }

    updateNavHighlight() {
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.view === this.state.currentView);
            el.setAttribute('aria-selected', el.dataset.view === this.state.currentView);
        });
    }

    setupEventListeners() {
        // Navigation
        document.querySelectorAll('.nav-item').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.triggerHaptic('light');
                const view = e.currentTarget.dataset.view;
                this.loadView(view);
            });
        });

        // Wallet Btn
        document.getElementById('wallet-connect-btn').addEventListener('click', () => this.toggleWallet());
    }

    triggerHaptic(style) {
        tg.HapticFeedback.impactOccurred(style);
    }

    showToast(msg, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        let icon = 'ℹ️';
        if (type === 'success') icon = '✅';
        if (type === 'error') icon = '❌';

        toast.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="text-lg">${icon}</span>
                <span class="text-sm font-medium">${msg}</span>
            </div>
            <button onclick="this.parentElement.remove()" class="text-white opacity-50 hover:opacity-100 ml-3">&times;</button>
        `;

        container.appendChild(toast);
        this.triggerHaptic('light');

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(20px)';
            setTimeout(() => toast.remove(), 300);
        }, CONFIG.TOAST_DURATION);
    }
}

// Initialize App
const app = new TonGPTApp();

// Expose strictly necessary methods to global scope for HTML OnClick attributes if needed
// though strictly we should use addEventListener. For now, we keep compatibility.
window.app = app;
