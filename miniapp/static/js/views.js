// View Rendering Functions for TonGPT
class ViewRenderer {
    constructor() {
        this.currentView = 'scan';
    }

    // Main render function
    render(view) {
        const mainContent = document.getElementById('main-content');
        this.currentView = view;
        
        switch (view) {
            case 'trending':
                mainContent.innerHTML = this.renderTrendingView();
                this.initTrendingView();
                break;
            case 'ai':
                mainContent.innerHTML = this.renderAIView();
                break;
            case 'social':
                mainContent.innerHTML = this.renderSocialView();
                this.initSocialView();
                break;
            case 'premium':
                mainContent.innerHTML = this.renderPremiumView();
                break;
            case 'scan':
            default:
                mainContent.innerHTML = this.renderScanView();
                this.initScanView();
        }
    }

    // Scan View - Pure Memecoins
    renderScanView() {
        const walletConnected = isWalletConnected();
        const memecoins = window.appState.memecoins || [];
        const loading = window.appState.loading;

        return `
            <div class="p-4 space-y-6">
                <!-- Header -->
                <div class="text-center">
                    <h1 class="text-2xl font-bold gradient-text mb-2">Pure TON Memecoins</h1>
                    <p class="telegram-hint">Live memecoin scanner - Major tokens excluded</p>
                </div>

                <!-- Wallet Info (if connected) -->
                <div id="wallet-info" class="glass-morphism rounded-2xl p-4" style="display: ${walletConnected ? 'block' : 'none'};">
                    <h2 class="font-semibold mb-3 flex items-center">
                        <i class="fas fa-wallet mr-2 text-green-400"></i>
                        Connected Wallet
                    </h2>
                    <div id="wallet-details" class="text-sm mb-3"></div>
                    <button onclick="disconnectWallet()" class="px-3 py-1 bg-red-500 bg-opacity-20 text-red-400 rounded-lg text-sm">
                        Disconnect
                    </button>
                </div>

                <!-- Filters -->
                <div class="glass-morphism rounded-2xl p-4">
                    <div class="flex items-center justify-between mb-3">
                        <h2 class="font-semibold">Memecoin Categories</h2>
                        <button onclick="refreshMemecoins()" class="text-sm telegram-accent">Refresh</button>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        <button onclick="filterMemecoins('all')" class="filter-btn px-3 py-1 rounded-lg text-xs bg-blue-500 bg-opacity-20 text-blue-400" data-filter="all">All</button>
                        <button onclick="filterMemecoins('dog')" class="filter-btn px-3 py-1 rounded-lg text-xs glass-morphism" data-filter="dog">🐕 Dogs</button>
                        <button onclick="filterMemecoins('cat')" class="filter-btn px-3 py-1 rounded-lg text-xs glass-morphism" data-filter="cat">🐱 Cats</button>
                        <button onclick="filterMemecoins('frog')" class="filter-btn px-3 py-1 rounded-lg text-xs glass-morphism" data-filter="frog">🐸 Frogs</button>
                        <button onclick="filterMemecoins('rocket')" class="filter-btn px-3 py-1 rounded-lg text-xs glass-morphism" data-filter="rocket">🚀 Moon</button>
                    </div>
                </div>

                <!-- Contract Scanner -->
                <div class="glass-morphism rounded-2xl p-4">
                    <h2 class="font-semibold mb-3 flex items-center">
                        <i class="fas fa-search mr-2 telegram-accent"></i>
                        Token Info Scanner
                    </h2>
                    <div class="flex gap-2">
                        <input id="contract-input" type="text" placeholder="Paste TON contract address..." 
                               class="flex-1 glass-morphism rounded-xl py-2 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                        <button onclick="scanContract()" class="telegram-button rounded-xl px-4 py-2 text-sm font-medium">
                            <i class="fas fa-search mr-1"></i>Scan
                        </button>
                    </div>
                    <div id="contract-result" class="mt-3"></div>
                </div>

                <!-- Memecoin List -->
                <div class="space-y-3" id="memecoin-list">
                    ${loading ? 
                        '<div class="text-center py-8"><div class="loading-spinner mx-auto"></div><p class="mt-2 telegram-hint">Loading memecoins...</p></div>' : 
                        memecoins.length > 0 ? 
                            memecoins.map(coin => this.renderMemecoinCard(coin)).join('') : 
                            '<div class="text-center py-8 telegram-hint">No memecoins found. Click refresh to reload data.</div>'
                    }
                </div>

                <!-- Stats -->
                <div class="glass-morphism rounded-2xl p-4 text-center">
                    <div class="grid grid-cols-3 gap-4">
                        <div>
                            <div class="text-2xl font-bold gradient-text">${memecoins.length}</div>
                            <div class="text-xs telegram-hint">Pure Memecoins</div>
                        </div>
                        <div>
                            <div class="text-2xl font-bold text-green-400">${memecoins.filter(c => c.change && c.change.includes('+')).length}</div>
                            <div class="text-xs telegram-hint">Pumping</div>
                        </div>
                        <div>
                            <div class="text-2xl font-bold text-red-400">${memecoins.filter(c => c.change && c.change.includes('-')).length}</div>
                            <div class="text-xs telegram-hint">Dumping</div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    // Initialize scan view specific functionality
    initScanView() {
        // Load memecoin data if not already loaded
        if (window.appState.memecoins.length === 0) {
            fetchMemecoins();
        }
        
        // Update wallet UI if connected
        if (tonConnect) {
            tonConnect.updateUI();
        }
    }

    // Trending View
    renderTrendingView() {
        return `
            <div class="p-4 space-y-6">
                <div class="text-center">
                    <h1 class="text-2xl font-bold gradient-text mb-2">Memecoin Trends</h1>
                    <p class="telegram-hint">Pure memecoin market analysis</p>
                </div>

                <!-- Loading State -->
                <div id="trending-loading" class="text-center py-8">
                    <div class="loading-spinner mx-auto"></div>
                    <p class="mt-2 telegram-hint">Loading trending data...</p>
                </div>

                <!-- Trending Content -->
                <div id="trending-content" style="display: none;">
                    <!-- Market Overview -->
                    <div class="glass-morphism rounded-2xl p-4">
                        <h2 class="font-semibold mb-3">Market Overview</h2>
                        <div id="market-trends" class="space-y-3">
                            <!-- Trends will be populated here -->
                        </div>
                    </div>

                    <!-- Top Performers -->
                    <div class="glass-morphism rounded-2xl p-4">
                        <h2 class="font-semibold mb-3">Top Performers (24h)</h2>
                        <div id="top-performers" class="space-y-2">
                            <!-- Top performers will be populated here -->
                        </div>
                    </div>

                    <!-- Market Insights -->
                    <div class="glass-morphism rounded-2xl p-4">
                        <h2 class="font-semibold mb-3 flex items-center">
                            <i class="fas fa-lightbulb mr-2 text-yellow-400"></i>
                            Market Insights
                        </h2>
                        <div id="market-insights" class="space-y-2 text-sm">
                            <!-- Insights will be populated here -->
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    async initTrendingView() {
        try {
            const data = await getTrendingData();
            this.populateTrendingData(data);
        } catch (error) {
            console.error('Failed to load trending data:', error);
            document.getElementById('trending-loading').innerHTML = 
                '<div class="text-center py-8 telegram-hint">Failed to load trending data. Please try again.</div>';
        }
    }

    populateTrendingData(data) {
        const loadingEl = document.getElementById('trending-loading');
        const contentEl = document.getElementById('trending-content');
        
        if (loadingEl) loadingEl.style.display = 'none';
        if (contentEl) contentEl.style.display = 'block';

        // Populate market trends
        const trendsEl = document.getElementById('market-trends');
        if (trendsEl && data.trends) {
            trendsEl.innerHTML = data.trends.map(trend => `
                <div class="flex justify-between items-center p-3 bg-${trend.color}-500 bg-opacity-10 rounded-xl">
                    <div>
                        <div class="font-medium text-${trend.color}-400">${trend.category}</div>
                        <div class="text-sm telegram-hint">${trend.description}</div>
                    </div>
                    <div class="text-${trend.color}-400 font-bold">${trend.change}</div>
                </div>
            `).join('');
        }

        // Populate top performers
        const performersEl = document.getElementById('top-performers');
        if (performersEl && data.performers) {
            performersEl.innerHTML = data.performers.map((coin, index) => `
                <div class="flex items-center justify-between p-3 glass-morphism rounded-xl">
                    <div class="flex items-center">
                        <span class="text-lg mr-2">${index + 1}</span>
                        <span class="text-xl mr-2">${getMemecoinEmoji(coin.type)}</span>
                        <div>
                            <div class="font-medium">${coin.name}</div>
                            <div class="text-sm telegram-hint">${coin.price}</div>
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="font-bold price-up">${coin.change}</div>
                        <div class="text-sm telegram-hint">$${coin.volume}</div>
                    </div>
                </div>
            `).join('');
        }

        // Populate insights
        const insightsEl = document.getElementById('market-insights');
        if (insightsEl && data.insights) {
            insightsEl.innerHTML = data.insights.map(insight => `
                <div class="flex items-start">
                    <i class="fas fa-circle text-${insight.color}-400 text-xs mt-2 mr-2"></i>
                    <span>${insight.text}</span>
                </div>
            `).join('');
        }
    }

    // AI View
    renderAIView() {
        return `
            <div class="p-4 space-y-6">
                <div class="text-center">
                    <h1 class="text-2xl font-bold gradient-text mb-2">AI Assistant</h1>
                    <p class="telegram-hint">Ask about TON memecoins and get AI analysis</p>
                </div>

                <!-- Quick Questions -->
                <div class="glass-morphism rounded-2xl p-4">
                    <h2 class="font-semibold mb-3">Quick Questions</h2>
                    <div class="grid grid-cols-1 gap-2">
                        <button onclick="askAI('What are the best TON memecoins right now?')" class="text-left p-3 glass-morphism rounded-xl text-sm hover:bg-white hover:bg-opacity-10">
                            💎 What are the best TON memecoins right now?
                        </button>
                        <button onclick="askAI('Which memecoin category is trending?')" class="text-left p-3 glass-morphism rounded-xl text-sm hover:bg-white hover:bg-opacity-10">
                            📈 Which memecoin category is trending?
                        </button>
                        <button onclick="askAI('How to identify a good memecoin?')" class="text-left p-3 glass-morphism rounded-xl text-sm hover:bg-white hover:bg-opacity-10">
                            🔍 How to identify a good memecoin?
                        </button>
                        <button onclick="askAI('What are the risks of memecoin trading?')" class="text-left p-3 glass-morphism rounded-xl text-sm hover:bg-white hover:bg-opacity-10">
                            ⚠️ What are the risks of memecoin trading?
                        </button>
                    </div>
                </div>

                <!-- Custom Question -->
                <div class="glass-morphism rounded-2xl p-4">
                    <h2 class="font-semibold mb-3">Ask Custom Question</h2>
                    <div class="space-y-3">
                        <textarea id="ai-question" placeholder="Ask me anything about TON memecoins..." 
                                class="w-full glass-morphism rounded-xl p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-400" 
                                rows="3"></textarea>
                        <button onclick="askCustomQuestion()" class="w-full telegram-button rounded-xl py-3 font-medium">
                            <i class="fas fa-magic mr-2"></i>Get AI Analysis
                        </button>
                    </div>
                </div>

                <!-- AI Response Area -->
                <div id="ai-response" class="glass-morphism rounded-2xl p-4" style="display: none;">
                    <h2 class="font-semibold mb-3 flex items-center">
                        <i class="fas fa-robot mr-2 telegram-accent"></i>
                        AI Analysis
                    </h2>
                    <div id="ai-answer" class="text-sm leading-relaxed"></div>
                </div>
            </div>
        `;
    }

    // Social View
    renderSocialView() {
        return `
            <div class="p-4 space-y-6">
                <div class="text-center">
                    <h1 class="text-2xl font-bold gradient-text mb-2">Social Intelligence</h1>
                    <p class="telegram-hint">X monitoring and influencer tracking</p>
                </div>

                <!-- Loading State -->
                <div id="social-loading" class="text-center py-8">
                    <div class="loading-spinner mx-auto"></div>
                    <p class="mt-2 telegram-hint">Loading social data...</p>
                </div>

                <!-- Social Content -->
                <div id="social-content" style="display: none;">
                    <!-- Influencer Posts -->
                    <div class="glass-morphism rounded-2xl p-4">
                        <h2 class="font-semibold mb-3 flex items-center">
                            <i class="fab fa-twitter mr-2 text-blue-400"></i>
                            Crypto Influencer Buzz
                        </h2>
                        <div id="influencer-posts" class="space-y-3">
                            <!-- Posts will be populated here -->
                        </div>
                    </div>

                    <!-- Sentiment Analysis -->
                    <div class="glass-morphism rounded-2xl p-4">
                        <h2 class="font-semibold mb-3">Market Sentiment</h2>
                        <div id="sentiment-analysis" class="grid grid-cols-3 gap-3 text-center">
                            <!-- Sentiment data will be populated here -->
                        </div>
                    </div>

                    <!-- Trending Topics -->
                    <div class="glass-morphism rounded-2xl p-4">
                        <h2 class="font-semibold mb-3">Trending Topics</h2>
                        <div id="trending-topics" class="flex flex-wrap gap-2">
                            <!-- Topics will be populated here -->
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    async initSocialView() {
        try {
            const data = await getSocialData();
            this.populateSocialData(data);
        } catch (error) {
            console.error('Failed to load social data:', error);
            document.getElementById('social-loading').innerHTML = 
                '<div class="text-center py-8 telegram-hint">Failed to load social data. Please try again.</div>';
        }
    }

    populateSocialData(data) {
        const loadingEl = document.getElementById('social-loading');
        const contentEl = document.getElementById('social-content');
        
        if (loadingEl) loadingEl.style.display = 'none';
        if (contentEl) contentEl.style.display = 'block';

        // Populate influencer posts
        const postsEl = document.getElementById('influencer-posts');
        if (postsEl && data.posts) {
            postsEl.innerHTML = data.posts.map(post => `
                <div class="p-3 glass-morphism rounded-xl">
                    <div class="flex items-center justify-between mb-2">
                        <div class="flex items-center">
                            <i class="fas fa-check-circle text-blue-400 mr-2"></i>
                            <span class="font-medium">${post.author}</span>
                            <span class="text-xs telegram-hint ml-2">${post.followers} followers</span>
                        </div>
                        <span class="text-xs telegram-hint">${post.time_ago}</span>
                    </div>
                    <p class="text-sm mb-2">${post.content}</p>
                    <div class="flex items-center justify-between text-xs">
                        <div class="flex items-center space-x-4">
                            <span>❤️ ${post.likes}</span>
                            <span>🔄 ${post.retweets}</span>
                        </div>
                        <span class="text-${post.sentiment === 'bullish' ? 'green' : post.sentiment === 'bearish' ? 'red' : 'yellow'}-400 font-medium">
                            ${post.sentiment}
                        </span>
                    </div>
                </div>
            `).join('');
        }

        // Populate sentiment analysis
        const sentimentEl = document.getElementById('sentiment-analysis');
        if (sentimentEl && data.sentiment) {
            sentimentEl.innerHTML = `
                <div class="p-3 bg-green-500 bg-opacity-20 rounded-xl">
                    <div class="text-2xl font-bold text-green-400">${data.sentiment.bullish}%</div>
                    <div class="text-xs telegram-hint">Bullish</div>
                </div>
                <div class="p-3 bg-yellow-500 bg-opacity-20 rounded-xl">
                    <div class="text-2xl font-bold text-yellow-400">${data.sentiment.neutral}%</div>
                    <div class="text-xs telegram-hint">Neutral</div>
                </div>
                <div class="p-3 bg-red-500 bg-opacity-20 rounded-xl">
                    <div class="text-2xl font-bold text-red-400">${data.sentiment.bearish}%</div>
                    <div class="text-xs telegram-hint">Bearish</div>
                </div>
            `;
        }

        // Populate trending topics
        const topicsEl = document.getElementById('trending-topics');
        if (topicsEl && data.trending_topics) {
            topicsEl.innerHTML = data.trending_topics.map(topic => 
                `<span class="px-3 py-1 bg-${topic.color}-500 bg-opacity-20 text-${topic.color}-400 rounded-full text-sm">${topic.tag}</span>`
            ).join('');
        }
    }

    // Premium View
    renderPremiumView() {
        const walletConnected = isWalletConnected();
        
        return `
            <div class="p-4 space-y-6">
                <div class="text-center">
                    <h1 class="text-2xl font-bold gradient-text mb-2">TonGPT Premium</h1>
                    <p class="telegram-hint">Unlock advanced memecoin analysis features</p>
                </div>

                <!-- Wallet Connection Warning -->
                ${!walletConnected ? `
                <div class="glass-morphism rounded-2xl p-4 border-2 border-yellow-500 border-opacity-30">
                    <div class="flex items-center mb-3">
                        <i class="fas fa-exclamation-triangle text-yellow-400 mr-2"></i>
                        <h3 class="font-bold">Wallet Required</h3>
                    </div>
                    <p class="text-sm telegram-hint mb-3">Connect your TON wallet to subscribe to premium plans</p>
                </div>
                ` : ''}

                <!-- Premium Plans -->
                <div class="space-y-4">
                    ${Object.entries(CONFIG.PLANS).map(([key, plan]) => `
                        <div class="glass-morphism rounded-2xl p-4 border-2 border-${key === 'PRO' ? 'purple' : key === 'ELITE' ? 'yellow' : 'blue'}-500 border-opacity-30">
                            <div class="flex items-center justify-between mb-3">
                                <div class="flex items-center">
                                    <h3 class="font-bold text-lg">${plan.name} Plan</h3>
                                    ${key === 'PRO' ? '<span class="ml-2 px-2 py-1 bg-purple-500 bg-opacity-30 text-purple-400 text-xs rounded-lg">Popular</span>' : ''}
                                    ${key === 'ELITE' ? '<span class="ml-2 px-2 py-1 bg-yellow-500 bg-opacity-30 text-yellow-400 text-xs rounded-lg">Best Value</span>' : ''}
                                </div>
                                <div class="text-right">
                                    <div class="text-2xl font-bold gradient-text">${plan.price} TON</div>
                                    <div class="text-xs telegram-hint">per month</div>
                                </div>
                            </div>
                            <div class="space-y-2 text-sm mb-4">
                                ${plan.features.map(feature => `
                                    <div class="flex items-center">
                                        <i class="fas fa-check text-green-400 mr-2"></i>
                                        <span>${feature}</span>
                                    </div>
                                `).join('')}
                            </div>
                            <button onclick="subscribePlan('${key.toLowerCase()}')" 
                                    class="w-full telegram-button rounded-xl py-2 text-sm ${!walletConnected ? 'opacity-50 cursor-not-allowed' : ''}"
                                    ${!walletConnected ? 'disabled' : ''}>
                                ${walletConnected ? 'Subscribe Now' : 'Connect Wallet First'}
                            </button>
                        </div>
                    `).join('')}
                </div>

                <!-- Referral Program -->
                <div class="glass-morphism rounded-2xl p-4">
                    <h2 class="font-semibold mb-3 flex items-center">
                        <i class="fas fa-gift mr-2 text-green-400"></i>
                        Earn Free Access
                    </h2>
                    <p class="text-sm telegram-hint mb-3">Invite friends and earn premium access without paying!</p>
                    <div class="flex items-center justify-between p-3 bg-green-500 bg-opacity-10 rounded-xl mb-3">
                        <span class="text-sm">Your referrals: 0</span>
                        <span class="text-sm text-green-400">Need 5 for Starter</span>
                    </div>
                    <button onclick="shareReferral()" class="w-full telegram-button rounded-xl py-2 text-sm">
                        <i class="fas fa-share mr-2"></i>Share Referral Link
                    </button>
                </div>
            </div>
        `;
    }

    // Memecoin Card Component
    renderMemecoinCard(coin) {
        const emoji = getMemecoinEmoji(coin.type || 'default');
        const verified = coin.verified ? '<i class="fas fa-check-circle text-blue-400 ml-1"></i>' : '';
        const changeColor = coin.change && coin.change.includes('+') ? 'price-up' : 'price-down';
        
        return `
            <div class="memecoin-card rounded-2xl p-4">
                <div class="flex justify-between items-start mb-3">
                    <div class="flex items-center">
                        <div class="text-2xl mr-3">${emoji}</div>
                        <div>
                            <div class="flex items-center">
                                <span class="font-bold">${coin.name || 'Unknown'}</span>
                                ${verified}
                            </div>
                            <span class="text-sm telegram-hint">${coin.symbol || 'N/A'}</span>
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="font-bold">${coin.price || '$0.00'}</div>
                        <div class="text-sm ${changeColor}">${coin.change || '0%'}</div>
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-4 text-sm">
                    <div>
                        <div class="telegram-hint">Volume 24h</div>
                        <div class="font-medium">${coin.volume || '0'}</div>
                    </div>
                    <div>
                        <div class="telegram-hint">Holders</div>
                        <div class="font-medium">${coin.holders || '0'}</div>
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-2 mt-3">
                    <button onclick="analyzeMemecoin('${coin.symbol || coin.name}')" class="telegram-button rounded-xl py-2 text-sm font-medium">
                        <i class="fas fa-chart-line mr-1"></i>Analyze
                    </button>
                    <button onclick="viewMemecoinDetails('${coin.contract || coin.symbol}')" class="glass-morphism rounded-xl py-2 text-sm font-medium">
                        <i class="fas fa-info-circle mr-1"></i>Details
                    </button>
                </div>
            </div>
        `;
    }

    // Update memecoin list in the current view
    updateMemecoinList() {
        const listElement = document.getElementById('memecoin-list');
        if (listElement && window.appState.memecoins) {
            const memecoins = window.appState.currentFilter && window.appState.currentFilter !== 'all' 
                ? window.appState.memecoins.filter(coin => coin.type === window.appState.currentFilter)
                : window.appState.memecoins;
                
            listElement.innerHTML = memecoins.length > 0 ? 
                memecoins.map(coin => this.renderMemecoinCard(coin)).join('') : 
                '<div class="text-center py-8 telegram-hint">No memecoins found matching your filter.</div>';
        }
    }
}

// Global view renderer instance
const viewRenderer = new ViewRenderer();