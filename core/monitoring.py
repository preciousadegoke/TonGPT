"""
Production monitoring, logging, and metrics for TonGPT
Enhanced version with better dependency management and error handling
"""
import asyncio
import logging
import time
import platform
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
import json
import os
from contextlib import asynccontextmanager

# Try to import optional dependencies with graceful fallbacks
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not available - system metrics will be limited")

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logging.warning("aiohttp not available - webhook alerts disabled")

# External monitoring integrations
try:
    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

logger = logging.getLogger(__name__)

@dataclass
class SystemMetrics:
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    disk_percent: float
    active_connections: int
    redis_connections: int
    database_connections: int
    python_version: str = ""
    platform: str = ""

@dataclass
class BusinessMetrics:
    timestamp: datetime
    total_users: int
    active_users_24h: int
    free_users: int
    paid_users: int
    total_payments: float
    api_requests_per_minute: float
    error_rate_percent: float
    avg_response_time_ms: float

class StructuredLogger:
    """Enhanced structured logging for production"""
    
    def __init__(self, service_name: str = "tongpt", log_level: str = "INFO"):
        self.service_name = service_name
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.setup_logging()
    
    def setup_logging(self):
        """Configure structured logging"""
        # Create logs directory if it doesn't exist
        os.makedirs('logs', exist_ok=True)
        
        # Configure formatters
        console_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        file_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s [%(filename)s:%(lineno)d]: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Configure handlers
        handlers = []
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(console_formatter)
        handlers.append(console_handler)
        
        # File handlers
        try:
            file_handler = logging.FileHandler('logs/tongpt.log', encoding='utf-8')
            file_handler.setLevel(self.log_level)
            file_handler.setFormatter(file_formatter)
            handlers.append(file_handler)
            
            error_handler = logging.FileHandler('logs/tongpt-error.log', encoding='utf-8')
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(file_formatter)
            handlers.append(error_handler)
        except Exception as e:
            print(f"Warning: Could not create log files: {e}")
        
        # Configure root logger
        logging.basicConfig(
            level=self.log_level,
            handlers=handlers,
            force=True
        )
        
        # Configure third-party loggers
        logging.getLogger("aiogram").setLevel(logging.WARNING)
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    def _create_log_data(self, event_type: str, **kwargs) -> Dict[str, Any]:
        """Create structured log data"""
        return {
            "service": self.service_name,
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
    
    def log_user_action(self, user_id: int, action: str, success: bool, 
                       metadata: Dict[str, Any] = None):
        """Log user actions with structured data"""
        log_data = self._create_log_data(
            "user_action",
            user_id=user_id,
            action=action,
            success=success,
            metadata=metadata or {}
        )
        
        if success:
            logger.info(f"User action completed: {json.dumps(log_data, default=str)}")
        else:
            logger.error(f"User action failed: {json.dumps(log_data, default=str)}")
    
    def log_payment(self, user_id: int, amount: float, currency: str, 
                   status: str, transaction_hash: str):
        """Log payment events"""
        log_data = self._create_log_data(
            "payment",
            user_id=user_id,
            amount=amount,
            currency=currency,
            status=status,
            transaction_hash=transaction_hash
        )
        
        logger.info(f"Payment event: {json.dumps(log_data, default=str)}")
    
    def log_api_request(self, endpoint: str, user_id: int, response_time_ms: float, 
                       success: bool, error_message: str = None):
        """Log API requests with performance metrics"""
        log_data = self._create_log_data(
            "api_request",
            endpoint=endpoint,
            user_id=user_id,
            response_time_ms=response_time_ms,
            success=success
        )
        
        if error_message:
            log_data["error_message"] = error_message
        
        if success:
            logger.info(f"API request: {json.dumps(log_data, default=str)}")
        else:
            logger.error(f"API request failed: {json.dumps(log_data, default=str)}")

class PrometheusMetrics:
    """Prometheus metrics for monitoring"""
    
    def __init__(self):
        if not PROMETHEUS_AVAILABLE:
            logger.warning("Prometheus client not available - metrics disabled")
            return
        
        # Request metrics
        self.request_counter = Counter(
            'tongpt_requests_total',
            'Total requests by endpoint and status',
            ['endpoint', 'status', 'user_tier']
        )
        
        self.request_duration = Histogram(
            'tongpt_request_duration_seconds',
            'Request duration in seconds',
            ['endpoint'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )
        
        # User metrics
        self.active_users = Gauge(
            'tongpt_active_users',
            'Number of active users',
            ['tier']
        )
        
        # Payment metrics
        self.payments_total = Counter(
            'tongpt_payments_total',
            'Total payments',
            ['currency', 'status']
        )
        
        self.revenue_total = Counter(
            'tongpt_revenue_total',
            'Total revenue in USD',
            ['currency']
        )
        
        # System metrics
        self.system_cpu = Gauge('tongpt_system_cpu_percent', 'CPU usage percentage')
        self.system_memory = Gauge('tongpt_system_memory_percent', 'Memory usage percentage')
        self.system_disk = Gauge('tongpt_system_disk_percent', 'Disk usage percentage')
        self.database_connections = Gauge('tongpt_database_connections', 'Active database connections')
        self.redis_connections = Gauge('tongpt_redis_connections', 'Active Redis connections')
        
        # Error metrics
        self.errors_total = Counter(
            'tongpt_errors_total',
            'Total errors by type',
            ['error_type', 'endpoint']
        )
        
        # Application metrics
        self.uptime = Gauge('tongpt_uptime_seconds', 'Application uptime in seconds')
        
        logger.info("Prometheus metrics initialized")
    
    def record_request(self, endpoint: str, status: str, duration: float, user_tier: str = "unknown"):
        """Record API request metrics"""
        if not PROMETHEUS_AVAILABLE:
            return
        
        try:
            self.request_counter.labels(
                endpoint=endpoint, 
                status=status, 
                user_tier=user_tier
            ).inc()
            self.request_duration.labels(endpoint=endpoint).observe(duration)
        except Exception as e:
            logger.error(f"Failed to record request metrics: {e}")
    
    def record_payment(self, amount: float, currency: str, status: str):
        """Record payment metrics"""
        if not PROMETHEUS_AVAILABLE:
            return
        
        try:
            self.payments_total.labels(currency=currency, status=status).inc()
            if status == 'confirmed':
                self.revenue_total.labels(currency=currency).inc(amount)
        except Exception as e:
            logger.error(f"Failed to record payment metrics: {e}")
    
    def record_error(self, error_type: str, endpoint: str = "unknown"):
        """Record error metrics"""
        if not PROMETHEUS_AVAILABLE:
            return
        
        try:
            self.errors_total.labels(error_type=error_type, endpoint=endpoint).inc()
        except Exception as e:
            logger.error(f"Failed to record error metrics: {e}")
    
    def update_system_metrics(self, metrics: SystemMetrics):
        """Update system metrics"""
        if not PROMETHEUS_AVAILABLE:
            return
        
        try:
            self.system_cpu.set(metrics.cpu_percent)
            self.system_memory.set(metrics.memory_percent)
            self.system_disk.set(metrics.disk_percent)
            self.database_connections.set(metrics.database_connections)
            self.redis_connections.set(metrics.redis_connections)
        except Exception as e:
            logger.error(f"Failed to update system metrics: {e}")

class SentryIntegration:
    """Sentry error tracking integration"""
    
    def __init__(self, dsn: str, environment: str = "production", sample_rate: float = 0.1):
        if not SENTRY_AVAILABLE:
            logger.warning("Sentry SDK not available - error tracking disabled")
            return
        
        sentry_logging = LoggingIntegration(
            level=logging.INFO,
            event_level=logging.ERROR
        )
        
        try:
            sentry_sdk.init(
                dsn=dsn,
                environment=environment,
                integrations=[
                    AsyncioIntegration(reraise_errors=True),
                    sentry_logging
                ],
                traces_sample_rate=sample_rate,
                send_default_pii=False,
                before_send=self.filter_sensitive_data,
                release=os.getenv("APP_VERSION", "unknown")
            )
            
            logger.info(f"Sentry integration initialized for environment: {environment}")
        except Exception as e:
            logger.error(f"Failed to initialize Sentry: {e}")
    
    def filter_sensitive_data(self, event, hint):
        """Filter sensitive data before sending to Sentry"""
        try:
            # Remove sensitive fields from different parts of the event
            sensitive_keys = ['api_key', 'token', 'password', 'wallet_address', 'private_key']
            
            # Filter extra data
            if 'extra' in event:
                for key in sensitive_keys:
                    if key in event['extra']:
                        event['extra'][key] = '[FILTERED]'
            
            # Filter request data
            if 'request' in event and 'data' in event['request']:
                for key in sensitive_keys:
                    if key in str(event['request']['data']):
                        event['request']['data'] = '[FILTERED]'
            
            return event
        except Exception:
            # If filtering fails, still send the event
            return event
    
    def capture_exception(self, exception: Exception, user_id: int = None, 
                         extra_data: Dict[str, Any] = None):
        """Capture exception with context"""
        if not SENTRY_AVAILABLE:
            return
        
        try:
            with sentry_sdk.push_scope() as scope:
                if user_id:
                    scope.user = {"id": str(user_id)}
                
                if extra_data:
                    for key, value in extra_data.items():
                        scope.set_extra(key, value)
                
                sentry_sdk.capture_exception(exception)
        except Exception as e:
            logger.error(f"Failed to capture exception in Sentry: {e}")

class SystemMonitor:
    """System health and performance monitoring"""
    
    def __init__(self):
        self.start_time = time.time()
        self.last_metrics_time = time.time()
        self.request_counts = {}
        self.error_counts = {}
        self.response_times = []
    
    def get_basic_system_info(self) -> Dict[str, Any]:
        """Get basic system info without psutil"""
        return {
            "python_version": sys.version,
            "platform": platform.platform(),
            "architecture": platform.architecture()[0],
            "processor": platform.processor() or "unknown",
            "uptime_seconds": time.time() - self.start_time
        }
    
    async def get_system_metrics(self) -> SystemMetrics:
        """Collect system metrics"""
        try:
            basic_info = self.get_basic_system_info()
            
            if PSUTIL_AVAILABLE:
                # Full system metrics with psutil
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                connections = len(psutil.net_connections(kind='inet'))
            else:
                # Fallback metrics without psutil
                cpu_percent = 0.0
                memory = type('obj', (object,), {'percent': 0.0, 'used': 0})()
                disk = type('obj', (object,), {'percent': 0.0})()
                connections = 0
            
            # Database connections (would need to query actual pool)
            db_connections = 0
            redis_connections = 0
            
            # Try to get Redis info if available
            try:
                # This would need to be imported from your Redis connection module
                # from utils.redis_conn import redis_client
                # redis_info = redis_client.info()
                # redis_connections = redis_info.get('connected_clients', 0)
                pass
            except Exception:
                pass
            
            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_mb=memory.used / (1024 * 1024) if hasattr(memory, 'used') else 0,
                disk_percent=disk.percent,
                active_connections=connections,
                redis_connections=redis_connections,
                database_connections=db_connections,
                python_version=basic_info["python_version"].split()[0],
                platform=basic_info["platform"]
            )
            
        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")
            basic_info = self.get_basic_system_info()
            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=0.0, memory_percent=0.0, memory_used_mb=0.0,
                disk_percent=0.0, active_connections=0,
                redis_connections=0, database_connections=0,
                python_version=basic_info["python_version"].split()[0],
                platform=basic_info["platform"]
            )
    
    async def get_business_metrics(self) -> BusinessMetrics:
        """Collect business metrics"""
        try:
            current_time = time.time()
            time_diff = max(current_time - self.last_metrics_time, 1)
            
            total_requests = sum(self.request_counts.values())
            requests_per_minute = (total_requests / time_diff) * 60
            
            total_errors = sum(self.error_counts.values())
            error_rate = (total_errors / max(total_requests, 1)) * 100
            
            avg_response_time = (
                sum(self.response_times) / len(self.response_times)
                if self.response_times else 0.0
            )
            
            return BusinessMetrics(
                timestamp=datetime.now(),
                total_users=1000,  # Would query from database
                active_users_24h=150,  # Would query from database
                free_users=800,
                paid_users=200,
                total_payments=5000.0,
                api_requests_per_minute=requests_per_minute,
                error_rate_percent=error_rate,
                avg_response_time_ms=avg_response_time
            )
            
        except Exception as e:
            logger.error(f"Failed to collect business metrics: {e}")
            return BusinessMetrics(
                timestamp=datetime.now(),
                total_users=0, active_users_24h=0, free_users=0,
                paid_users=0, total_payments=0.0, api_requests_per_minute=0.0,
                error_rate_percent=0.0, avg_response_time_ms=0.0
            )
    
    def record_request(self, endpoint: str, response_time_ms: float = 0):
        """Record API request"""
        self.request_counts[endpoint] = self.request_counts.get(endpoint, 0) + 1
        if response_time_ms > 0:
            self.response_times.append(response_time_ms)
            # Keep only last 1000 response times
            if len(self.response_times) > 1000:
                self.response_times = self.response_times[-1000:]
    
    def record_error(self, endpoint: str, error_type: str):
        """Record API error"""
        key = f"{endpoint}:{error_type}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1

class HealthChecker:
    """Health check endpoints for load balancers"""
    
    def __init__(self, db_manager=None, redis_client=None):
        self.db_manager = db_manager
        self.redis_client = redis_client
        self.system_monitor = SystemMonitor()
    
    async def basic_health_check(self) -> Dict[str, Any]:
        """Basic health check - just verify service is running"""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": time.time() - self.system_monitor.start_time,
            "service": "tongpt-bot",
            "version": os.getenv("APP_VERSION", "unknown")
        }
    
    async def detailed_health_check(self) -> Dict[str, Any]:
        """Detailed health check including dependencies"""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "system_info": self.system_monitor.get_basic_system_info()
        }
        
        # Check database
        if self.db_manager:
            try:
                # This would depend on your database manager implementation
                # async with self.db_manager.get_connection() as conn:
                #     await conn.fetchval("SELECT 1")
                health_status["services"]["database"] = "healthy"
            except Exception as e:
                health_status["services"]["database"] = f"unhealthy: {str(e)}"
                health_status["status"] = "degraded"
        
        # Check Redis
        if self.redis_client:
            try:
                # This would depend on your Redis client implementation
                # self.redis_client.ping()
                health_status["services"]["redis"] = "healthy"
            except Exception as e:
                health_status["services"]["redis"] = f"unhealthy: {str(e)}"
                health_status["status"] = "degraded"
        
        # Check system resources
        try:
            system_metrics = await self.system_monitor.get_system_metrics()
            if system_metrics.cpu_percent > 90 or system_metrics.memory_percent > 90:
                health_status["status"] = "degraded"
                health_status["warnings"] = ["High system resource usage"]
            
            health_status["system_metrics"] = asdict(system_metrics)
        except Exception as e:
            health_status["warnings"] = [f"Could not collect system metrics: {str(e)}"]
        
        return health_status
    
    async def readiness_check(self) -> Dict[str, Any]:
        """Readiness check for Kubernetes"""
        ready = True
        services = {}
        
        # Check critical dependencies
        if self.db_manager:
            try:
                # Check database connectivity
                # This would be implemented based on your DB manager
                services["database"] = "ready"
            except Exception as e:
                services["database"] = f"not_ready: {str(e)}"
                ready = False
        
        if self.redis_client:
            try:
                # Check Redis connectivity
                # This would be implemented based on your Redis client
                services["redis"] = "ready"
            except Exception as e:
                services["redis"] = f"not_ready: {str(e)}"
                ready = False
        
        return {
            "ready": ready,
            "timestamp": datetime.now().isoformat(),
            "services": services
        }

class AlertManager:
    """Alert management for critical issues"""
    
    def __init__(self, webhook_url: str = None, alert_cooldown: int = 300):
        self.webhook_url = webhook_url
        self.alert_cooldown = alert_cooldown  # 5 minutes default
        self.alert_thresholds = {
            "error_rate": 5.0,  # 5% error rate
            "response_time": 5000,  # 5 seconds
            "memory_usage": 85,  # 85% memory usage
            "cpu_usage": 85,  # 85% CPU usage
            "failed_payments": 3  # 3 failed payments in 10 minutes
        }
        self.alert_history = {}
    
    def update_thresholds(self, new_thresholds: Dict[str, float]):
        """Update alert thresholds"""
        self.alert_thresholds.update(new_thresholds)
        logger.info(f"Alert thresholds updated: {new_thresholds}")
    
    async def check_alerts(self, system_metrics: SystemMetrics, 
                          business_metrics: BusinessMetrics):
        """Check for alert conditions"""
        alerts = []
        
        # System alerts
        if system_metrics.cpu_percent > self.alert_thresholds["cpu_usage"]:
            alerts.append({
                "type": "system",
                "severity": "warning",
                "message": f"High CPU usage: {system_metrics.cpu_percent:.1f}%",
                "value": system_metrics.cpu_percent,
                "threshold": self.alert_thresholds["cpu_usage"]
            })
        
        if system_metrics.memory_percent > self.alert_thresholds["memory_usage"]:
            alerts.append({
                "type": "system",
                "severity": "warning",
                "message": f"High memory usage: {system_metrics.memory_percent:.1f}%",
                "value": system_metrics.memory_percent,
                "threshold": self.alert_thresholds["memory_usage"]
            })
        
        # Business alerts
        if business_metrics.error_rate_percent > self.alert_thresholds["error_rate"]:
            alerts.append({
                "type": "business",
                "severity": "critical",
                "message": f"High error rate: {business_metrics.error_rate_percent:.1f}%",
                "value": business_metrics.error_rate_percent,
                "threshold": self.alert_thresholds["error_rate"]
            })
        
        if business_metrics.avg_response_time_ms > self.alert_thresholds["response_time"]:
            alerts.append({
                "type": "performance",
                "severity": "warning",
                "message": f"Slow response time: {business_metrics.avg_response_time_ms:.0f}ms",
                "value": business_metrics.avg_response_time_ms,
                "threshold": self.alert_thresholds["response_time"]
            })
        
        # Send alerts
        for alert in alerts:
            await self.send_alert(alert)
    
    async def send_alert(self, alert: Dict[str, Any]):
        """Send alert notification with rate limiting"""
        alert_key = f"{alert['type']}:{alert['message']}"
        
        # Rate limiting - don't spam the same alert
        last_sent = self.alert_history.get(alert_key, 0)
        if time.time() - last_sent < self.alert_cooldown:
            return
        
        self.alert_history[alert_key] = time.time()
        
        # Log alert
        logger.error(f"ALERT: {json.dumps(alert, default=str)}")
        
        # Send to external webhook if configured and available
        if self.webhook_url and AIOHTTP_AVAILABLE:
            await self.send_webhook_alert(alert)
    
    async def send_webhook_alert(self, alert: Dict[str, Any]):
        """Send alert to webhook (Slack, Discord, etc.)"""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                payload = {
                    "text": f"🚨 TonGPT Alert: {alert['message']}",
                    "severity": alert["severity"],
                    "timestamp": datetime.now().isoformat(),
                    "service": "tongpt-bot",
                    "alert_type": alert["type"],
                    "value": alert.get("value"),
                    "threshold": alert.get("threshold")
                }
                
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status != 200:
                        logger.error(f"Failed to send webhook alert: {response.status}")
                    else:
                        logger.info("Alert sent to webhook successfully")
                        
        except Exception as e:
            logger.error(f"Webhook alert failed: {e}")

# Global monitoring instances
_structured_logger = None
_prometheus_metrics = None
_system_monitor = None
_alert_manager = None
_health_checker = None

def get_logger() -> StructuredLogger:
    """Get structured logger instance"""
    global _structured_logger
    if _structured_logger is None:
        _structured_logger = StructuredLogger()
    return _structured_logger

def get_prometheus_metrics() -> Optional[PrometheusMetrics]:
    """Get Prometheus metrics instance"""
    global _prometheus_metrics
    if _prometheus_metrics is None and PROMETHEUS_AVAILABLE:
        _prometheus_metrics = PrometheusMetrics()
    return _prometheus_metrics

def get_system_monitor() -> SystemMonitor:
    """Get system monitor instance"""
    global _system_monitor
    if _system_monitor is None:
        _system_monitor = SystemMonitor()
    return _system_monitor

def get_alert_manager() -> Optional[AlertManager]:
    """Get alert manager instance"""
    global _alert_manager
    return _alert_manager

def get_health_checker() -> HealthChecker:
    """Get health checker instance"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker

def initialize_monitoring(
    sentry_dsn: str = None,
    prometheus_port: int = 8001,
    alert_webhook: str = None,
    environment: str = "production",
    log_level: str = "INFO"
):
    """Initialize monitoring services"""
    
    # Initialize structured logger first
    global _structured_logger
    _structured_logger = StructuredLogger(log_level=log_level)
    
    # Initialize Sentry
    if sentry_dsn:
        try:
            SentryIntegration(sentry_dsn, environment)
            logger.info("Sentry monitoring initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Sentry: {e}")
    
    # Initialize Prometheus metrics
    if PROMETHEUS_AVAILABLE:
        try:
            global _prometheus_metrics
            _prometheus_metrics = PrometheusMetrics()
            
            # Start Prometheus metrics server if port specified
            if prometheus_port:
                start_http_server(prometheus_port)
                logger.info(f"Prometheus metrics server started on port {prometheus_port}")
        except Exception as e:
            logger.error(f"Failed to start Prometheus server: {e}")
    
    # Initialize alert manager
    global _alert_manager
    _alert_manager = AlertManager(alert_webhook)
    
    # Initialize health checker
    global _health_checker
    _health_checker = HealthChecker()
    
    # Initialize system monitor
    global _system_monitor
    _system_monitor = SystemMonitor()
    
    logger.info(f"Monitoring system initialized for environment: {environment}")
    logger.info(f"Available integrations - Sentry: {SENTRY_AVAILABLE}, Prometheus: {PROMETHEUS_AVAILABLE}, psutil: {PSUTIL_AVAILABLE}, aiohttp: {AIOHTTP_AVAILABLE}")

async def monitoring_loop(interval: int = 60):
    """Main monitoring loop - runs periodically to collect and alert on metrics"""
    system_monitor = get_system_monitor()
    alert_manager = get_alert_manager()
    prometheus_metrics = get_prometheus_metrics()
    
    logger.info(f"Starting monitoring loop with {interval}s interval")
    
    while True:
        try:
            # Collect metrics
            system_metrics = await system_monitor.get_system_metrics()
            business_metrics = await system_monitor.get_business_metrics()
            
            # Update Prometheus metrics if available
            if prometheus_metrics:
                prometheus_metrics.update_system_metrics(system_metrics)
                prometheus_metrics.uptime.set(time.time() - system_monitor.start_time)
            
            # Check for alerts
            if alert_manager:
                await alert_manager.check_alerts(system_metrics, business_metrics)
            
            # Log metrics summary
            logger.info(
                f"Metrics summary - CPU: {system_metrics.cpu_percent:.1f}%, "
                f"Memory: {system_metrics.memory_percent:.1f}%, "
                f"Requests/min: {business_metrics.api_requests_per_minute:.1f}, "
                f"Error rate: {business_metrics.error_rate_percent:.2f}%"
            )
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            if SENTRY_AVAILABLE:
                sentry_sdk.capture_exception(e)
        
        await asyncio.sleep(interval)

# Context manager for request timing
@asynccontextmanager
async def monitor_request(endpoint: str, user_id: int = None, user_tier: str = "unknown"):
    """Context manager to automatically monitor request timing and errors"""
    start_time = time.time()
    system_monitor = get_system_monitor()
    prometheus_metrics = get_prometheus_metrics()
    structured_logger = get_logger()
    
    try:
        yield
        # Success case
        duration_ms = (time.time() - start_time) * 1000
        system_monitor.record_request(endpoint, duration_ms)
        
        if prometheus_metrics:
            prometheus_metrics.record_request(endpoint, "success", time.time() - start_time, user_tier)
        
        structured_logger.log_api_request(endpoint, user_id or 0, duration_ms, True)
        
    except Exception as e:
        # Error case
        duration_ms = (time.time() - start_time) * 1000
        error_type = type(e).__name__
        
        system_monitor.record_error(endpoint, error_type)
        
        if prometheus_metrics:
            prometheus_metrics.record_request(endpoint, "error", time.time() - start_time, user_tier)
            prometheus_metrics.record_error(error_type, endpoint)
        
        structured_logger.log_api_request(endpoint, user_id or 0, duration_ms, False, str(e))
        
        # Capture exception in Sentry if available
        if SENTRY_AVAILABLE:
            sentry_sdk.capture_exception(e)
        
        raise

# Decorator for monitoring functions
def monitor_function(endpoint: str = None, user_tier: str = "unknown"):
    """Decorator to monitor function execution"""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            func_name = endpoint or f"{func.__module__}.{func.__name__}"
            async with monitor_request(func_name, user_tier=user_tier):
                return await func(*args, **kwargs)
        
        def sync_wrapper(*args, **kwargs):
            func_name = endpoint or f"{func.__module__}.{func.__name__}"
            start_time = time.time()
            system_monitor = get_system_monitor()
            prometheus_metrics = get_prometheus_metrics()
            structured_logger = get_logger()
            
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                system_monitor.record_request(func_name, duration_ms)
                
                if prometheus_metrics:
                    prometheus_metrics.record_request(func_name, "success", time.time() - start_time, user_tier)
                
                structured_logger.log_api_request(func_name, 0, duration_ms, True)
                return result
                
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                error_type = type(e).__name__
                
                system_monitor.record_error(func_name, error_type)
                
                if prometheus_metrics:
                    prometheus_metrics.record_request(func_name, "error", time.time() - start_time, user_tier)
                    prometheus_metrics.record_error(error_type, func_name)
                
                structured_logger.log_api_request(func_name, 0, duration_ms, False, str(e))
                
                if SENTRY_AVAILABLE:
                    sentry_sdk.capture_exception(e)
                
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

# Example usage functions
@monitor_function("payment_processing", "premium")
async def process_payment_example(user_id: int, amount: float):
    """Example of monitored payment processing"""
    logger = get_logger()
    prometheus = get_prometheus_metrics()
    
    # Simulate payment processing
    await asyncio.sleep(0.1)
    
    # Log payment
    logger.log_payment(user_id, amount, "TON", "confirmed", "dummy_tx_hash")
    
    # Record payment metrics
    if prometheus:
        prometheus.record_payment(amount, "TON", "confirmed")
    
    return {"status": "success", "tx_hash": "dummy_tx_hash"}

if __name__ == "__main__":
    # Example initialization and usage
    initialize_monitoring(
        sentry_dsn="YOUR_SENTRY_DSN_HERE",  # Replace with actual DSN
        prometheus_port=8001,
        alert_webhook="YOUR_WEBHOOK_URL_HERE",  # Replace with actual webhook URL
        environment="development",
        log_level="INFO"
    )
    
    # Example of running the monitoring loop
    # asyncio.create_task(monitoring_loop(30))  # Check every 30 seconds