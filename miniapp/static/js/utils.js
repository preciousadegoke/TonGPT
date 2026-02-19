// Utility Functions for TonGPT
class Utils {
    // Get memecoin emoji based on type
    static getMemecoinEmoji(type) {
        return CONFIG.EMOJIS[type] || CONFIG.EMOJIS.default;
    }

    // Format number with K/M suffix
    static formatNumber(num) {
        if (num >= 1000000) {
            return (num / 1000000).toFixed(1) + 'M';
        }
        if (num >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        }
        return num.toString();
    }

    // Format price with proper decimals
    static formatPrice(price) {
        if (typeof price === 'string' && price.startsWith('$')) {
            return price;
        }
        const numPrice = parseFloat(price);
        if (numPrice < 0.01) {
            return '$' + numPrice.toFixed(6);
        }
        return '$' + numPrice.toFixed(4);
    }

    // Format percentage change
    static formatPercentage(change) {
        if (typeof change === 'string') {
            return change;
        }
        const sign = change >= 0 ? '+' : '';
        return sign + change.toFixed(2) + '%';
    }

    // Validate TON address
    static isValidTonAddress(address) {
        // Basic TON address validation
        return /^[A-Za-z0-9_-]{48}$/.test(address) || 
               /^[0-9a-fA-F]{64}$/.test(address) ||
               /^EQ[A-Za-z0-9_-]{46}$/.test(address) ||
               /^UQ[A-Za-z0-9_-]{46}$/.test(address);
    }

    // Shorten address for display
    static shortenAddress(address, startLength = 6, endLength = 4) {
        if (!address) return 'Unknown';
        if (address.length <= startLength + endLength) return address;
        return `${address.slice(0, startLength)}...${address.slice(-endLength)}`;
    }

    // Time ago formatter
    static timeAgo(date) {
        const now = new Date();
        const diff = now - date;
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (seconds < 60) return `${seconds}s ago`;
        if (minutes < 60) return `${minutes}m ago`;
        if (hours < 24) return `${hours}h ago`;
        return `${days}d ago`;
    }

    // Debounce function
    static debounce(func, wait, immediate) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                timeout = null;
                if (!immediate) func(...args);
            };
            const callNow = immediate && !timeout;
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
            if (callNow) func(...args);
        };
    }

    // Throttle function
    static throttle(func, limit) {
        let lastFunc;
        let lastRan;
        return function(...args) {
            if (!lastRan) {
                func.apply(this, args);
                lastRan = Date.now();
            } else {
                clearTimeout(lastFunc);
                lastFunc = setTimeout(() => {
                    if ((Date.now() - lastRan) >= limit) {
                        func.apply(this, args);
                        lastRan = Date.now();
                    }
                }, limit - (Date.now() - lastRan));
            }
        };
    }

    // Generate random ID
    static generateId() {
        return Math.random().toString(36).substr(2, 9);
    }

    // Local storage with error handling
    static setLocalStorage(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (error) {
            console.error('LocalStorage error:', error);
            return false;
        }
    }

    static getLocalStorage(key, defaultValue = null) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : defaultValue;
        } catch (error) {
            console.error('LocalStorage error:', error);
            return defaultValue;
        }
    }

    // Copy to clipboard
    static async copyToClipboard(text) {
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(text);
                return true;
            } else {
                // Fallback for older browsers
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.style.position = 'absolute';
                textArea.style.left = '-999999px';
                document.body.prepend(textArea);
                textArea.select();
                try {
                    document.execCommand('copy');
                    return true;
                } finally {
                    textArea.remove();
                }
            }
        } catch (error) {
            console.error('Copy failed:', error);
            return false;
        }
    }

    // Animate element
    static animateElement(element, animation = 'fade-in') {
        element.classList.add(animation);
        setTimeout(() => {
            element.classList.remove(animation);
        }, 300);
    }

    // Scroll to element
    static scrollToElement(element, offset = 0) {
        const elementPosition = element.getBoundingClientRect().top;
        const offsetPosition = elementPosition + window.pageYOffset - offset;

        window.scrollTo({
            top: offsetPosition,
            behavior: 'smooth'
        });
    }

    // Check if element is in viewport
    static isInViewport(element) {
        const rect = element.getBoundingClientRect();
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
            rect.right <= (window.innerWidth || document.documentElement.clientWidth)
        );
    }

    // Color utilities
    static getChangeColor(change) {
        if (typeof change === 'string') {
            return change.includes('+') ? 'text-green-400' : change.includes('-') ? 'text-red-400' : '';
        }
        return change > 0 ? 'text-green-400' : change < 0 ? 'text-red-400' : '';
    }

    // Validate form data
    static validateForm(formData, rules) {
        const errors = {};
        
        for (const [field, rule] of Object.entries(rules)) {
            const value = formData[field];
            
            if (rule.required && (!value || value.trim() === '')) {
                errors[field] = `${field} is required`;
                continue;
            }
            
            if (value && rule.minLength && value.length < rule.minLength) {
                errors[field] = `${field} must be at least ${rule.minLength} characters`;
                continue;
            }
            
            if (value && rule.maxLength && value.length > rule.maxLength) {
                errors[field] = `${field} must be no more than ${rule.maxLength} characters`;
                continue;
            }
            
            if (value && rule.pattern && !rule.pattern.test(value)) {
                errors[field] = rule.message || `${field} format is invalid`;
                continue;
            }
        }
        
        return {
            isValid: Object.keys(errors).length === 0,
            errors
        };
    }
}

// Global utility functions for convenience
function getMemecoinEmoji(type) {
    return Utils.getMemecoinEmoji(type);
}

function formatNumber(num) {
    return Utils.formatNumber(num);
}

function formatPrice(price) {
    return Utils.formatPrice(price);
}

function shortenAddress(address, start = 6, end = 4) {
    return Utils.shortenAddress(address, start, end);
}

function timeAgo(date) {
    return Utils.timeAgo(date);
}

// Notification system
function showNotification(message, type = 'info', duration = CONFIG.APP.NOTIFICATION_DURATION) {
    const notification = document.createElement('div');
    const id = Utils.generateId();
    
    notification.id = `notification-${id}`;
    notification.className = `fixed top-4 right-4 z-50 p-3 rounded-lg text-white text-sm transition-all duration-300 transform translate-x-full max-w-sm ${
        type === 'error' ? 'bg-red-500' : 
        type === 'success' ? 'bg-green-500' : 
        type === 'warning' ? 'bg-yellow-500' : 
        'bg-blue-500'
    }`;
    
    notification.innerHTML = `
        <div class="flex items-center justify-between">
            <span>${message}</span>
            <button onclick="removeNotification('${id}')" class="ml-2 text-white opacity-70 hover:opacity-100">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    // Slide in
    setTimeout(() => {
        notification.classList.remove('translate-x-full');
    }, 100);
    
    // Auto remove
    setTimeout(() => {
        removeNotification(id);
    }, duration);
}

function removeNotification(id) {
    const notification = document.getElementById(`notification-${id}`);
    if (notification) {
        notification.classList.add('translate-x-full');
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }
}

// Loading state management
function setLoading(elementId, isLoading = true, loadingText = 'Loading...') {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    if (isLoading) {
        element.innerHTML = `
            <div class="flex items-center justify-center py-8">
                <div class="loading-spinner mr-2"></div>
                <span class="telegram-hint">${loadingText}</span>
            </div>
        `;
    }
}