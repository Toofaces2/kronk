import time
import hashlib
import threading
from collections import defaultdict, OrderedDict
from functools import wraps
from urllib.parse import urlparse
import jurialmunkey.reqapi
from tmdbhelper.lib.addon.plugin import get_setting
from tmdbhelper.lib.addon.logger import kodi_log
from tmdbhelper.lib.files.bcache import BasicCache


def null_function(*args, **kwargs):
    return


class ConnectionPool:
    """HTTP connection pool for reusing connections"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.max_connections = int(get_setting('max_connections_per_host', '8'))
        self.pools = defaultdict(list)
        self.pool_lock = threading.Lock()
        self.active_connections = defaultdict(int)
        self._initialized = True
    
    def get_session(self, host):
        """Get or create a session for the given host"""
        with self.pool_lock:
            if self.pools[host]:
                session = self.pools[host].pop()
                # Verify session is still valid
                if hasattr(session, '_closed') and not session._closed:
                    return session
            
            # Create new session if under limit
            if self.active_connections[host] < self.max_connections:
                try:
                    import requests
                    session = requests.Session()
                    
                    # Configure session for optimal performance
                    adapter = requests.adapters.HTTPAdapter(
                        pool_connections=self.max_connections,
                        pool_maxsize=self.max_connections,
                        max_retries=1
                    )
                    session.mount('http://', adapter)
                    session.mount('https://', adapter)
                    
                    session.headers.update({
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive',
                    })
                    
                    self.active_connections[host] += 1
                    return session
                except Exception as e:
                    kodi_log(f"Failed to create session for {host}: {e}", level=2)
            
            return None
    
    def return_session(self, host, session):
        """Return session to pool for reuse"""
        try:
            with self.pool_lock:
                if (len(self.pools[host]) < self.max_connections and 
                    hasattr(session, '_closed') and not session._closed):
                    self.pools[host].append(session)
                else:
                    session.close()
        except Exception as e:
            kodi_log(f"Error returning session for {host}: {e}", level=1)


class RequestMemoryCache:
    """Memory-based request cache with LRU eviction"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.max_size = int(get_setting('memory_cache_size', '500'))
        self.default_ttl = int(get_setting('memory_cache_ttl', '300'))
        
        self.cache = OrderedDict()
        self.timestamps = {}
        self.cache_lock = threading.RLock()
        self._initialized = True
    
    def _generate_key(self, url, method, params=None, headers=None):
        """Generate cache key from request parameters"""
        key_parts = [method.upper(), url]
        
        if params:
            # Sort params for consistent key generation
            if isinstance(params, dict):
                params_str = '&'.join(f"{k}={v}" for k, v in sorted(params.items()))
            else:
                params_str = str(params)
            key_parts.append(f"params:{params_str}")
        
        key_data = "|".join(key_parts)
        return hashlib.md5(key_data.encode('utf-8')).hexdigest()[:16]
    
    def get(self, url, method='GET', params=None, headers=None, ttl=None):
        """Get cached response if valid and not expired"""
        if not get_setting('use_memory_cache', True):
            return None
            
        key = self._generate_key(url, method, params, headers)
        
        with self.cache_lock:
            if key not in self.cache:
                return None
            
            # Check TTL
            max_age = ttl or self.default_ttl
            if time.time() - self.timestamps[key] > max_age:
                # Expired, remove from cache
                self._remove_key(key)
                return None
            
            # Move to end for LRU (most recently accessed)
            self.cache.move_to_end(key)
            return self.cache[key]
    
    def set(self, url, method, response_data, params=None, headers=None):
        """Cache response data"""
        if not get_setting('use_memory_cache', True):
            return
        
        key = self._generate_key(url, method, params, headers)
        
        with self.cache_lock:
            # Remove oldest items if cache is full
            while len(self.cache) >= self.max_size:
                oldest_key = next(iter(self.cache))
                self._remove_key(oldest_key)
            
            self.cache[key] = response_data
            self.timestamps[key] = time.time()
    
    def _remove_key(self, key):
        """Remove key from cache and timestamps"""
        self.cache.pop(key, None)
        self.timestamps.pop(key, None)
    
    def clear(self):
        """Clear all cached data"""
        with self.cache_lock:
            self.cache.clear()
            self.timestamps.clear()


class RateLimiter:
    """Rate limiter to prevent API abuse and respect API limits"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.requests_per_second = float(get_setting('requests_per_second', '5'))
        self.burst_limit = int(get_setting('burst_limit', '15'))
        
        self.request_times = defaultdict(list)
        self.limiter_lock = threading.Lock()
        self._initialized = True
    
    def wait_if_needed(self, host):
        """Wait if necessary to respect rate limits"""
        if self.requests_per_second <= 0:
            return  # No rate limiting
        
        current_time = time.time()
        
        with self.limiter_lock:
            # Clean old entries (keep last 60 seconds for burst protection)
            cutoff_time = current_time - 60
            self.request_times[host] = [t for t in self.request_times[host] if t > cutoff_time]
            
            recent_requests = self.request_times[host]
            
            # Check burst limit
            if len(recent_requests) >= self.burst_limit:
                wait_time = 1.0  # Wait 1 second if burst limit hit
                kodi_log(f"Rate limit: burst limit reached for {host}, waiting {wait_time}s", level=1)
                return wait_time
            
            # Check requests per second
            recent_window = current_time - 1.0
            requests_in_window = len([t for t in recent_requests if t > recent_window])
            
            if requests_in_window >= self.requests_per_second:
                # Calculate wait time based on oldest request in window
                oldest_in_window = min([t for t in recent_requests if t > recent_window])
                wait_time = 1.0 - (current_time - oldest_in_window)
                return max(wait_time, 0.1)  # Minimum 0.1s wait
        
        return 0
    
    def record_request(self, host):
        """Record that a request was made"""
        with self.limiter_lock:
            self.request_times[host].append(time.time())


def enhance_performance(func):
    """Decorator to add performance enhancements to request methods"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Initialize performance components if needed
        if not hasattr(self, '_perf_initialized'):
            self._connection_pool = ConnectionPool()
            self._memory_cache = RequestMemoryCache()
            self._rate_limiter = RateLimiter()
            self._perf_initialized = True
        
        return func(self, *args, **kwargs)
    return wrapper


class RequestAPI(jurialmunkey.reqapi.RequestAPI):
    error_notification = get_setting('connection_notifications')
    _basiccache = BasicCache

    @staticmethod
    def kodi_log(msg, level=0):
        kodi_log(msg, level)
    
    @enhance_performance
    def request(self, *args, **kwargs):
        """Enhanced request method with connection pooling and memory caching"""
        url = args[0] if args else kwargs.get('url')
        method = kwargs.get('method', 'GET').upper()
        
        if not url:
            return super().request(*args, **kwargs)
        
        # Parse URL for optimizations
        try:
            parsed_url = urlparse(url)
            host = parsed_url.netloc
        except Exception:
            return super().request(*args, **kwargs)
        
        # Check memory cache for GET requests (non-streaming)
        if (method == 'GET' and 
            not kwargs.get('stream', False) and 
            get_setting('use_memory_cache', True)):
            
            cached_response = self._memory_cache.get(
                url, method,
                params=kwargs.get('params'),
                headers=kwargs.get('headers')
            )
            if cached_response is not None:
                kodi_log(f"Memory cache hit for {url}", level=0)
                return cached_response
        
        # Rate limiting
        if get_setting('enable_rate_limiting', True):
            wait_time = self._rate_limiter.wait_if_needed(host)
            if wait_time > 0:
                time.sleep(wait_time)
        
        # Try to use connection pool for better performance
        if get_setting('use_connection_pool', True):
            session = self._connection_pool.get_session(host)
            if session:
                try:
                    # Make request using pooled connection
                    response = self._make_pooled_request(session, url, method, **kwargs)
                    
                    # Return session to pool
                    self._connection_pool.return_session(host, session)
                    
                    # Record request for rate limiting
                    if get_setting('enable_rate_limiting', True):
                        self._rate_limiter.record_request(host)
                    
                    # Cache successful GET responses in memory
                    if (method == 'GET' and 
                        hasattr(response, 'status_code') and 
                        response.status_code == 200 and
                        not kwargs.get('stream', False) and
                        get_setting('use_memory_cache', True)):
                        
                        self._memory_cache.set(
                            url, method, response,
                            params=kwargs.get('params'),
                            headers=kwargs.get('headers')
                        )
                    
                    return response
                    
                except Exception as e:
                    kodi_log(f"Pooled request failed for {url}: {e}", level=1)
                    # Return session to pool even on error
                    self._connection_pool.return_session(host, session)
        
        # Fallback to parent implementation
        response = super().request(*args, **kwargs)
        
        # Record request for rate limiting even on fallback
        if get_setting('enable_rate_limiting', True):
            self._rate_limiter.record_request(host)
        
        return response
    
    def _make_pooled_request(self, session, url, method, **kwargs):
        """Make request using pooled session"""
        # Set reasonable timeout if not specified
        if 'timeout' not in kwargs:
            kwargs['timeout'] = (5, 30)  # (connect, read) timeout
        
        if method == 'GET':
            return session.get(url, **kwargs)
        elif method == 'POST':
            return session.post(url, **kwargs)
        elif method == 'PUT':
            return session.put(url, **kwargs)
        elif method == 'DELETE':
            return session.delete(url, **kwargs)
        else:
            return session.request(method, url, **kwargs)


class NoCacheRequestAPI(RequestAPI):
    _basiccache = null_function
    
    @enhance_performance
    def request(self, *args, **kwargs):
        """Enhanced no-cache request with connection pooling but no caching"""
        # Temporarily disable memory caching for this request
        original_setting = get_setting('use_memory_cache', True)
        
        # Override memory cache setting temporarily
        import tmdbhelper.lib.addon.plugin as plugin_module
        if hasattr(plugin_module, '_settings_cache'):
            plugin_module._settings_cache = plugin_module._settings_cache or {}
            plugin_module._settings_cache['use_memory_cache'] = False
        
        try:
            return super().request(*args, **kwargs)
        finally:
            # Restore original setting
            if hasattr(plugin_module, '_settings_cache'):
                plugin_module._settings_cache['use_memory_cache'] = original_setting