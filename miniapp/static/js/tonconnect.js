// TonConnect Wallet Integration
class TonConnectManager {
    constructor() {
        this.tonConnectUI = null;
        this.wallet = null;
        this.isInitialized = false;
    }

    async init() {
        try {
            if (typeof TonConnectUI === 'undefined') {
                throw new Error('TonConnect UI not loaded');
            }

            this.tonConnectUI = new TonConnectUI({
                manifestUrl: CONFIG.TON_CONNECT.MANIFEST_URL,
                buttonRootId: 'ton-connect'
            });

            // Listen for wallet connection changes
            this.tonConnectUI.onStatusChange(wallet => {
                this.handleWalletChange(wallet);
            });

            // Check if wallet is already connected
            this.wallet = this.tonConnectUI.wallet;
            this.updateUI();
            
            this.isInitialized = true;
            console.log('TonConnect initialized successfully');
            
        } catch (error) {
            console.error('TonConnect initialization failed:', error);
            showNotification(CONFIG.ERRORS.WALLET, 'error');
        }
    }

    handleWalletChange(wallet) {
        this.wallet = wallet;
        this.updateUI();
        
        if (wallet && wallet.account) {
            showNotification(CONFIG.SUCCESS.WALLET_CONNECTED);
            // Update app state
            if (window.appState) {
                window.appState.connectedWallet = wallet;
            }
        } else {
            showNotification(CONFIG.SUCCESS.WALLET_DISCONNECTED);
            if (window.appState) {
                window.appState.connectedWallet = null;
            }
        }
    }

    updateUI() {
        const walletInfo = document.getElementById('wallet-info');
        const walletDetails = document.getElementById('wallet-details');
        
        if (this.wallet && this.wallet.account) {
            const address = this.wallet.account.address;
            const shortAddress = `${address.slice(0, 6)}...${address.slice(-4)}`;
            
            if (walletInfo && walletDetails) {
                walletInfo.style.display = 'block';
                walletDetails.innerHTML = `
                    <div class="space-y-2">
                        <div class="flex justify-between">
                            <span class="telegram-hint">Address:</span>
                            <span class="font-mono text-xs">${shortAddress}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="telegram-hint">Chain:</span>
                            <span>TON ${CONFIG.TON_CONNECT.NETWORK}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="telegram-hint">Status:</span>
                            <span class="text-green-400">Connected</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="telegram-hint">Wallet:</span>
                            <span>${this.wallet.device.appName}</span>
                        </div>
                    </div>
                `;
            }
        } else {
            if (walletInfo) {
                walletInfo.style.display = 'none';
            }
        }
    }

    async disconnect() {
        try {
            if (this.tonConnectUI) {
                await this.tonConnectUI.disconnect();
            }
        } catch (error) {
            console.error('Disconnect error:', error);
            showNotification(CONFIG.ERRORS.WALLET, 'error');
        }
    }

    async sendTransaction(amount, message = '') {
        if (!this.wallet || !this.wallet.account) {
            showNotification('Please connect your wallet first', 'error');
            return false;
        }

        try {
            const transaction = {
                validUntil: Math.floor(Date.now() / 1000) + 60,
                messages: [
                    {
                        address: CONFIG.TON_CONNECT.RECIPIENT_ADDRESS,
                        amount: (amount * 1000000000).toString(), // Convert to nanotons
                        payload: message
                    }
                ]
            };

            const result = await this.tonConnectUI.sendTransaction(transaction);
            console.log('Transaction result:', result);
            return result;
        } catch (error) {
            console.error('Transaction error:', error);
            if (error.message.includes('rejected')) {
                showNotification('Transaction was cancelled', 'error');
            } else {
                showNotification(CONFIG.ERRORS.TRANSACTION, 'error');
            }
            return false;
        }
    }

    isConnected() {
        return this.wallet && this.wallet.account;
    }

    getAddress() {
        return this.wallet?.account?.address || null;
    }

    getWalletName() {
        return this.wallet?.device?.appName || 'Unknown';
    }
}

// Global TonConnect instance
let tonConnect = null;

// Initialize TonConnect
async function initTonConnect() {
    tonConnect = new TonConnectManager();
    await tonConnect.init();
}

// Utility functions for global access
function disconnectWallet() {
    if (tonConnect) {
        tonConnect.disconnect();
    }
}

function isWalletConnected() {
    return tonConnect ? tonConnect.isConnected() : false;
}

function getConnectedAddress() {
    return tonConnect ? tonConnect.getAddress() : null;
}