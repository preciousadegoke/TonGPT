// API Client for TonGPT Backend
class APIClient {
    constructor(baseUrl = CONFIG.API.BASE_URL) {
        this.baseUrl = baseUrl;
        this.timeout = CONFIG.API.TIMEOUT;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const config = {
            timeout: this.timeout,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        };

        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), this.timeout);

            const response = await fetch(url, {
                ...config,
                signal: controller.signal
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            
            if (error.name === 'AbortError') {
                throw new Error('Request timeout');
            }
            
            throw error;
        }
    }

    // Memecoin Data
    async getMemecoins() {
        try {
            const data = await this.request(CONFIG.API.ENDPOINTS.MEMECOINS);
            return data.memecoins || [];
        } catch (error) {
            console.error('Failed to fetch memecoins:', error);
            throw new Error(CONFIG.ERRORS.API);
        }
    }

    // Token Contract Scanning
    async scanToken(contractAddress) {
        try {
            const data = await this.request(CONFIG.API.ENDPOINTS.SCAN_TOKEN, {
                method: 'POST',
                body: JSON.stringify({ contract: contractAddress })
            });
            return data;
        } catch (error) {
            console.error('Failed to scan token:', error);
            throw new Error('Failed to scan token contract');
        }
    }

    // Trending Data
    async getTrending() {
        try {
            const data = await this.request(CONFIG.API.ENDPOINTS.TRENDING);
            return {
                trends: data.trends || [],
                insights: data.insights || [],
                performers: data.performers || []
            };
        } catch (error) {
            console.error('Failed to fetch trending data:', error);
            throw new Error('Failed to load trending data');
        }
    }

    // Social Data
    async getSocialData() {
        try {
            const data = await this.request(CONFIG.API.ENDPOINTS.SOCIAL);
            return {
                posts: data.posts || [],
                sentiment: data.sentiment || { bullish: 0, neutral: 0, bearish: 0 },
                influencers: data.influencers || [],
                trending_topics: data.trending_topics || []
            };
        } catch (error) {
            console.error('Failed to fetch social data:', error);
            throw new Error('Failed to load social data');
        }
    }

    // AI Analysis
    async getAIAnalysis(question) {
        try {
            const data = await this.request(CONFIG.API.ENDPOINTS.AI_ANALYSIS, {
                method: 'POST',
                body: JSON.stringify({ question })
            });
            return data;
        } catch (error) {
            console.error('Failed to get AI analysis:', error);
            throw new Error('AI analysis failed');
        }
    }

    // Subscription Management
    async verifySubscription(walletAddress, transactionHash) {
        try {
            const data = await this.request(CONFIG.API.ENDPOINTS.SUBSCRIPTION, {
                method: 'POST',
                body: JSON.stringify({ 
                    wallet_address: walletAddress,
                    transaction_hash: transactionHash 
                })
            });
            return data;
        } catch (error) {
            console.error('Failed to verify subscription:', error);
            throw new Error('Subscription verification failed');
        }
    }

    // Health Check
    async healthCheck() {
        try {
            await this.request('/health');
            return true;
        } catch (error) {
            return false;
        }
    }
}

// Global API client instance
const apiClient = new APIClient();

// Convenience functions for global use
async function fetchMemecoins() {
    try {
        window.appState.loading = true;
        const memecoins = await apiClient.getMemecoins();
        window.appState.memecoins = memecoins;
        window.appState.lastUpdate = new Date();
        
        // Update UI if we're on scan view
        if (window.appState.currentView === 'scan') {
            updateMemecoinList();
        }
        
        return memecoins;
    } catch (error) {
        showNotification(error.message, 'error');
        return [];
    } finally {
        window.appState.loading = false;
    }
}

async function scanTokenContract(contractAddress) {
    try {
        return await apiClient.scanToken(contractAddress);
    } catch (error) {
        throw error;
    }
}

async function getTrendingData() {
    try {
        return await apiClient.getTrending();
    } catch (error) {
        showNotification(error.message, 'error');
        return { trends: [], insights: [], performers: [] };
    }
}

async function getSocialData() {
    try {
        return await apiClient.getSocialData();
    } catch (error) {
        showNotification(error.message, 'error');
        return { 
            posts: [], 
            sentiment: { bullish: 0, neutral: 0, bearish: 0 }, 
            influencers: [], 
            trending_topics: [] 
        };
    }
}

async function askAIQuestion(question) {
    try {
        return await apiClient.getAIAnalysis(question);
    } catch (error) {
        throw error;
    }
}