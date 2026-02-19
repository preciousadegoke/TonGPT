// TonGPT Configuration
const CONFIG = {
    // API Configuration
    API: {
        BASE_URL: 'https://tongpt.loca.lt/api', // Your Python backend URL
        ENDPOINTS: {
            MEMECOINS: '/memecoins',
            SCAN_TOKEN: '/scan-token',
            TRENDING: '/trending',
            SOCIAL: '/social',
            AI_ANALYSIS: '/ai-analysis',
            SUBSCRIPTION: '/subscription'
        },
        TIMEOUT: 10000 // 10 seconds
    },

    // TonConnect Configuration
    TON_CONNECT: {
        MANIFEST_URL: 'https://your-domain.com/manifest.json', // Update with your actual manifest URL
        RECIPIENT_ADDRESS: 'UQCYwQOwGs9JJq_H-KJKD12nb8iG10V6plEMO0xI3ykxLFDD', // Your TON wallet address
        NETWORK: 'mainnet' // 'mainnet' or 'testnet'
    },

    // Subscription Plans
    PLANS: {
        STARTER: {
            name: 'Starter',
            price: 30, // TON
            features: [
                'Advanced AI memecoin analysis',
                'Real-time price alerts',
                'Social sentiment tracking'
            ]
        },
        PRO: {
            name: 'Pro',
            price: 130, // TON
            features: [
                'Everything in Starter',
                'X influencer alerts',
                'Whale transaction tracking',
                'Portfolio tracking'
            ]
        },
        ELITE: {
            name: 'Elite',
            price: 300, // TON
            features: [
                'Everything in Pro',
                'Custom AI trading signals',
                'Priority support',
                'Early access to new features'
            ]
        }
    },

    // App Configuration
    APP: {
        NAME: 'TonGPT',
        VERSION: '1.0.0',
        DEBUG: false, // Set to true for development
        REFRESH_INTERVAL: 30000, // 30 seconds
        NOTIFICATION_DURATION: 3000, // 3 seconds
        MAX_RETRIES: 3
    },

    // Memecoin Categories
    CATEGORIES: {
        ALL: 'all',
        DOG: 'dog',
        CAT: 'cat',
        FROG: 'frog',
        ROCKET: 'rocket',
        DIAMOND: 'diamond',
        HAMSTER: 'hamster'
    },

    // Category Emojis
    EMOJIS: {
        dog: '🐕',
        cat: '🐱',
        frog: '🐸',
        hamster: '🐹',
        rocket: '🚀',
        diamond: '💎',
        default: '🎯'
    },

    // Mock Data for Development (remove in production)
    MOCK_DATA: {
        MEMECOINS: [
            { 
                name: 'PepeTON', 
                symbol: 'PEPE', 
                price: '$0.0045', 
                change: '+23.4%', 
                volume: '234K', 
                holders: '1.2K', 
                type: 'frog', 
                verified: true 
            },
            { 
                name: 'DogeTON', 
                symbol: 'DOGT', 
                price: '$0.0012', 
                change: '+45.6%', 
                volume: '456K', 
                holders: '2.8K', 
                type: 'dog', 
                verified: false 
            },
            { 
                name: 'CatCoin', 
                symbol: 'CAT', 
                price: '$0.0089', 
                change: '-12.3%', 
                volume: '123K', 
                holders: '890', 
                type: 'cat', 
                verified: true 
            },
            { 
                name: 'RocketMoon', 
                symbol: 'MOON', 
                price: '$0.0156', 
                change: '+67.8%', 
                volume: '789K', 
                holders: '3.4K', 
                type: 'rocket', 
                verified: false 
            },
            { 
                name: 'DiamondTON', 
                symbol: 'DIAM', 
                price: '$0.0234', 
                change: '+34.5%', 
                volume: '567K', 
                holders: '1.9K', 
                type: 'diamond', 
                verified: true 
            }
        ]
    },

    // Error Messages
    ERRORS: {
        NETWORK: 'Network error. Please check your connection.',
        API: 'Unable to fetch data from server.',
        WALLET: 'Wallet connection failed.',
        TRANSACTION: 'Transaction failed. Please try again.',
        VALIDATION: 'Please check your input and try again.'
    },

    // Success Messages
    SUCCESS: {
        WALLET_CONNECTED: 'Wallet connected successfully!',
        WALLET_DISCONNECTED: 'Wallet disconnected',
        DATA_REFRESHED: 'Data refreshed successfully!',
        SUBSCRIPTION: 'Successfully subscribed!',
        TRANSACTION: 'Transaction completed successfully!'
    }
};

// Export for module usage (if needed)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CONFIG;
}