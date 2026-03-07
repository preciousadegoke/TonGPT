// Main Application Logic for TonGPT
class TonGPTApp {
    constructor() {
        this.state = {
            currentView: 'scan',
            loading: false,
            memecoins: [],
            filteredMemecoins: [],
            currentFilter: 'all',
            lastUpdate: null,
            connectedWallet: null,
            subscriptionStatus: null
        };
        
        this.tg = window.Telegram?.WebApp;
        this.initialized = false;
    }

    async init() {
        try {
            console.log('Initializing TonGPT...');
            
            // Setup Telegram WebApp
            this.setupTelegramWebApp();
            
            // Check Consent first
            const hasConsent = await this.checkConsent();
            if (!hasConsent) {
                this.renderConsentScreen();
                return; // Stop initialization until consent is given
            }
            
            // Initialize TonConnect
            await initTonConnect();
            
            // Load initial data
            await this.loadInitialData();
            
            // Setup event listeners
            this.setupEventListeners();
            
            // Navigate to default view
            this.navigateTo('scan');
            
            // Setup auto-refresh
            this.setupAutoRefresh();
            
            this.initialized = true;
            console.log('TonGPT initialized successfully');
            
        } catch (error) {
            console.error('Failed to initialize TonGPT:', error);
            showNotification('Failed to initialize app', 'error');
        }
    }

    async checkConsent() {
        try {
            const response = await apiClient.request('/user/consent-status');
            return response.accepted === true;
        } catch (error) {
            console.error('Failed to check consent status:', error);
            // Default to requiring consent on error to be safe
            return false;
        }
    }

    renderConsentScreen() {
        const mainContent = document.getElementById('main-content');
        if (!mainContent) return;

        // Hide navigation while on consent screen
        const nav = document.querySelector('.bottom-nav');
        if (nav) nav.style.display = 'none';

        mainContent.innerHTML = `
            <div class="p-6 space-y-6 max-w-md mx-auto mt-10">
                <div class="text-center">
                    <div class="text-6xl mb-4">📜</div>
                    <h1 class="text-2xl font-bold gradient-text mb-2">Terms of Service</h1>
                    <p class="telegram-hint">Welcome to TonGPT! Before you begin, please review our terms.</p>
                </div>

                <div class="glass-morphism rounded-2xl p-4 text-sm space-y-3 h-64 overflow-y-auto">
                    <p>By using TonGPT, you agree to the following:</p>
                    <ul class="list-disc pl-5 space-y-2">
                        <li>TonGPT provides AI analysis and metrics for informational purposes only.</li>
                        <li><strong>Not Financial Advice:</strong> None of the insights or AI outputs constitute financial, investment, or trading advice.</li>
                        <li>You are solely responsible for any transactions you make using connected wallets.</li>
                        <li>Memecoins are highly volatile and carry significant risk of loss.</li>
                    </ul>
                    <p class="mt-4">Read our full <a href="#" class="telegram-accent underline">Terms of Service</a> and <a href="#" class="telegram-accent underline">Privacy Policy</a>.</p>
                </div>

                <div class="space-y-3 pt-4">
                    <button id="accept-consent-btn" class="w-full telegram-button rounded-xl py-3 font-medium text-lg flex items-center justify-center">
                        <i class="fas fa-check mr-2"></i> I Accept
                    </button>
                    <button id="decline-consent-btn" class="w-full bg-red-500 bg-opacity-20 text-red-400 rounded-xl py-3 font-medium text-sm flex items-center justify-center">
                        Decline & Exit
                    </button>
                </div>
            </div>
        `;

        document.getElementById('accept-consent-btn').addEventListener('click', async () => {
            const btn = document.getElementById('accept-consent-btn');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<div class="loading-spinner w-5 h-5 mr-2"></div> Accepting...';
            btn.disabled = true;

            try {
                await apiClient.request('/user/record-consent', {
                    method: 'POST',
                    body: JSON.stringify({ version: 'v1' })
                });
                
                // Consent recorded, resume initialization
                if (nav) nav.style.display = 'flex';
                
                // Re-run init to continue normal flow
                await this.init();
                
            } catch (error) {
                console.error('Failed to record consent:', error);
                showNotification('Failed to record consent. Please try again.', 'error');
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        });

        document.getElementById('decline-consent-btn').addEventListener('click', () => {
            if (this.tg) {
                this.tg.close();
            } else {
                window.close();
            }
        });
    }

    setupTelegramWebApp() {
        if (this.tg) {
            this.tg.expand();
            this.tg.ready();
            
            // Setup theme
            document.documentElement.style.setProperty('--tg-color-scheme', this.tg.colorScheme);
            
            // Setup haptic feedback
            if (this.tg.HapticFeedback) {
                document.addEventListener('click', (e) => {
                    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
                        this.tg.HapticFeedback.impactOccurred('light');
                    }
                });
            }
        }
    }

    async loadInitialData() {
        try {
            // Load memecoins data
            const memecoins = await fetchMemecoins();
            this.state.memecoins = memecoins;
            this.state.filteredMemecoins = memecoins;
            this.state.lastUpdate = new Date();
            
        } catch (error) {
            console.error('Failed to load initial data:', error);
            // Continue with empty data - user can refresh later
        }
    }

    setupEventListeners() {
        // Global error handler
        window.addEventListener('error', (e) => {
            console.error('Global error:', e.error);
            if (CONFIG.APP.DEBUG) {
                showNotification(`Error: ${e.error.message}`, 'error');
            }
        });

        // Handle online/offline status
        window.addEventListener('online', () => {
            showNotification('Connection restored', 'success');
            this.refreshCurrentView();
        });

        window.addEventListener('offline', () => {
            showNotification('Connection lost', 'warning');
        });

        // Handle visibility change
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.initialized) {
                // App became visible, refresh data if it's stale
                const timeSinceUpdate = Date.now() - (this.state.lastUpdate?.getTime() || 0);
                if (timeSinceUpdate > CONFIG.APP.REFRESH_INTERVAL * 2) {
                    this.refreshCurrentView();
                }
            }
        });
    }

    setupAutoRefresh() {
        setInterval(() => {
            if (this.state.currentView === 'scan' && !document.hidden) {
                this.refreshMemecoins(false); // Silent refresh
            }
        }, CONFIG.APP.REFRESH_INTERVAL);
    }

    navigateTo(view) {
        if (this.state.currentView === view) return;
        
        this.state.currentView = view;
        
        // Update navigation UI
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.view === view);
        });
        
        // Render the view
        viewRenderer.render(view);
        
        // Update URL hash (for development)
        if (CONFIG.APP.DEBUG) {
            window.location.hash = view;
        }
    }

    async refreshCurrentView() {
        switch (this.state.currentView) {
            case 'scan':
                await this.refreshMemecoins();
                break;
            case 'trending':
                await viewRenderer.initTrendingView();
                break;
            case 'social':
                await viewRenderer.initSocialView();
                break;
        }
    }

    async refreshMemecoins(showNotif = true) {
        try {
            if (showNotif) {
                showNotification('Refreshing memecoin data...');
            }
            
            const memecoins = await fetchMemecoins();
            this.state.memecoins = memecoins;
            this.applyCurrentFilter();
            this.state.lastUpdate = new Date();
            
            if (showNotif) {
                showNotification('Data refreshed successfully!', 'success');
            }
            
        } catch (error) {
            console.error('Refresh failed:', error);
            if (showNotif) {
                showNotification('Failed to refresh data', 'error');
            }
        }
    }

    filterMemecoins(type) {
        this.state.currentFilter = type;
        this.applyCurrentFilter();
        
        // Update filter UI
        document.querySelectorAll('.filter-btn').forEach(btn => {
            const isActive = btn.dataset.filter === type;
            btn.className = `filter-btn px-3 py-1 rounded-lg text-xs ${
                isActive ? 'bg-blue-500 bg-opacity-20 text-blue-400' : 'glass-morphism'
            }`;
        });
        
        showNotification(`Filtering ${type === 'all' ? 'all' : type} memecoins...`);
    }

    applyCurrentFilter() {
        if (this.state.currentFilter === 'all') {
            this.state.filteredMemecoins = this.state.memecoins;
        } else {
            this.state.filteredMemecoins = this.state.memecoins.filter(
                coin => coin.type === this.state.currentFilter
            );
        }
        
        // Update the UI
        viewRenderer.updateMemecoinList();
    }

    async scanContract() {
        const contractInput = document.getElementById('contract-input');
        const resultDiv = document.getElementById('contract-result');
        
        if (!contractInput || !resultDiv) return;
        
        const contract = contractInput.value.trim();
        
        if (!contract) {
            showNotification('Please enter a contract address', 'error');
            return;
        }
        
        if (!Utils.isValidTonAddress(contract)) {
            showNotification('Invalid TON address format', 'error');
            return;
        }
        
        setLoading('contract-result', true, 'Scanning contract...');
        
        try {
            const result = await scanTokenContract(contract);
            
            if (result && result.success) {
                resultDiv.innerHTML = `
                    <div class="p-3 glass-morphism rounded-xl">
                        <div class="font-medium">${result.data.name} (${result.data.symbol})</div>
                        <div class="text-sm telegram-hint mt-1">
                            Price: ${result.data.price} | 
                            Holders: ${result.data.holders} | 
                            Volume: ${result.data.volume}
                        </div>
                        <div class="text-xs telegram-hint mt-2">
                            Contract: ${Utils.shortenAddress(contract, 10, 6)}
                        </div>
                        <button onclick="app.analyzeMemecoin('${result.data.symbol}')" 
                                class="mt-2 w-full telegram-button rounded-xl py-1 text-xs">
                            Analyze with AI
                        </button>
                    </div>
                `;
                showNotification('Token found successfully!', 'success');
            } else {
                resultDiv.innerHTML = '<div class="p-3 bg-red-500 bg-opacity-10 rounded-xl text-red-400 text-sm">Contract not found or invalid</div>';
            }
        } catch (error) {
            console.error('Contract scan error:', error);
            resultDiv.innerHTML = '<div class="p-3 bg-red-500 bg-opacity-10 rounded-xl text-red-400 text-sm">Failed to scan contract</div>';
            showNotification('Contract scan failed', 'error');
        }
    }

    analyzeMemecoin(symbol) {
        showNotification(`Analyzing ${symbol} with AI...`);
        this.navigateTo('ai');
        
        // Pre-fill the AI question
        setTimeout(() => {
            const aiQuestion = document.getElementById('ai-question');
            if (aiQuestion) {
                aiQuestion.value = `Analyze ${symbol} memecoin. What are its prospects?`;
            }
        }, 100);
    }

    async askAI(question) {
        const responseDiv = document.getElementById('ai-response');
        const answerDiv = document.getElementById('ai-answer');
        
        if (!responseDiv || !answerDiv) return;
        
        responseDiv.style.display = 'block';
        answerDiv.innerHTML = '<div class="flex items-center"><div class="loading-spinner mr-2"></div><span>AI is analyzing...</span></div>';
        
        try {
            const result = await askAIQuestion(question);
            
            answerDiv.innerHTML = `
                <div class="mb-3">
                    <strong>Question:</strong> ${question}
                </div>
                <div>
                    <strong>AI Analysis:</strong> ${result.analysis || result.answer || 'Analysis completed successfully.'}
                </div>
            `;
        } catch (error) {
            console.error('AI analysis error:', error);
            answerDiv.innerHTML = `
                <div class="text-red-400">
                    Failed to get AI analysis. Please try again later.
                </div>
            `;
            showNotification('AI analysis failed', 'error');
        }
    }

    async askCustomQuestion() {
        const questionInput = document.getElementById('ai-question');
        if (!questionInput) return;
        
        const question = questionInput.value.trim();
        if (!question) {
            showNotification('Please enter a question', 'error');
            return;
        }
        
        await this.askAI(question);
    }

    async subscribePlan(plan) {
        if (!isWalletConnected()) {
            showNotification('Please connect your wallet first', 'error');
            return;
        }

        const planConfig = CONFIG.PLANS[plan.toUpperCase()];
        if (!planConfig) {
            showNotification('Invalid plan selected', 'error');
            return;
        }

        try {
            showNotification(`Processing ${planConfig.name} plan payment (${planConfig.price} TON)...`);

            // Fetch current payment wallet address from backend
            const addressInfo = await apiClient.request('/subscription/payment-info?plan=' + planConfig.name);
            const recipientAddress = addressInfo.address;
            
            const result = await tonConnect.sendTransaction(
                planConfig.price, 
                `TonGPT ${planConfig.name} subscription`,
                recipientAddress
            );
            
            if (result) {
                // Verify subscription with backend
                const walletAddress = getConnectedAddress();
                const verification = await apiClient.verifySubscription(walletAddress, result.boc);
                
                if (verification.success) {
                    this.state.subscriptionStatus = {
                        plan: plan,
                        active: true,
                        expiresAt: verification.expiresAt
                    };
                    showNotification(`Successfully subscribed to ${planConfig.name} plan!`, 'success');
                } else {
                    throw new Error('Subscription verification failed');
                }
            }
        } catch (error) {
            console.error('Subscription error:', error);
            showNotification('Subscription failed. Please try again.', 'error');
        }
    }

    async shareReferral() {
        try {
            const response = await apiClient.request('/user/referral-token');
            const token = response.token;
            const referralLink = `https://t.me/TonGpt_bot?start=${token}`;
            
            if (navigator.share) {
                navigator.share({
                    title: 'Join TonGPT - TON Memecoin Analyzer',
                    text: 'Get AI-powered memecoin analysis on TON blockchain!',
                    url: referralLink
                });
            } else {
                Utils.copyToClipboard(referralLink).then(success => {
                    if (success) {
                        showNotification('Referral link copied to clipboard!', 'success');
                    } else {
                        showNotification('Failed to copy referral link', 'error');
                    }
                });
            }
        } catch (error) {
            console.error('Error sharing referral:', error);
            showNotification('Failed to generate referral link.', 'error');
        }
    }

    viewMemecoinDetails(contractOrSymbol) {
        // Navigate to scan view and show contract details
        this.navigateTo('scan');
        setTimeout(() => {
            const contractInput = document.getElementById('contract-input');
            if (contractInput && Utils.isValidTonAddress(contractOrSymbol)) {
                contractInput.value = contractOrSymbol;
                this.scanContract();
            }
        }, 100);
    }
}

// Global app instance
let app;

// Global functions for HTML onclick handlers
function navigateTo(view) {
    if (app) app.navigateTo(view);
}

function refreshData() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.querySelector('i').classList.add('fa-spin');
    }
    
    if (app) {
        app.refreshCurrentView().finally(() => {
            if (refreshBtn) {
                refreshBtn.querySelector('i').classList.remove('fa-spin');
            }
        });
    }
}

function refreshMemecoins() {
    if (app) app.refreshMemecoins();
}

function filterMemecoins(type) {
    if (app) app.filterMemecoins(type);
}

function scanContract() {
    if (app) app.scanContract();
}

function analyzeMemecoin(symbol) {
    if (app) app.analyzeMemecoin(symbol);
}

function askAI(question) {
    if (app) app.askAI(question);
}

function askCustomQuestion() {
    if (app) app.askCustomQuestion();
}

function subscribePlan(plan) {
    if (app) app.subscribePlan(plan);
}

function shareReferral() {
    if (app) app.shareReferral();
}

function viewMemecoinDetails(contractOrSymbol) {
    if (app) app.viewMemecoinDetails(contractOrSymbol);
}

function updateMemecoinList() {
    if (viewRenderer) viewRenderer.updateMemecoinList();
}

// Make app state globally accessible
window.appState = null;

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', async () => {
    try {
        app = new TonGPTApp();
        window.appState = app.state;
        await app.init();
    } catch (error) {
        console.error('Failed to start TonGPT:', error);
        showNotification('Failed to start application', 'error');
    }
});