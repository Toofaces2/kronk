from xbmcgui import Dialog, Window
from jurialmunkey.ftools import cached_property
from tmdbhelper.lib.addon.plugin import get_localized
from tmdbhelper.lib.api.request import NoCacheRequestAPI
from tmdbhelper.lib.api.api_keys.trakt import CLIENT_ID, CLIENT_SECRET, USER_TOKEN
from tmdbhelper.lib.api.trakt.authenticator import TraktAuthenticator
from tmdbhelper.lib.files.locker import mutexlock
from threading import Thread
import time

# Constants for better performance and maintainability
API_ENDPOINTS = {
    'BASE': 'https://api.trakt.tv/',
    'OAUTH_DEVICE_CODE': 'https://api.trakt.tv/oauth/device/code',
    'OAUTH_DEVICE_TOKEN': 'https://api.trakt.tv/oauth/device/token',
    'OAUTH_REVOKE': 'https://api.trakt.tv/oauth/revoke',
    'OAUTH_TOKEN': 'https://api.trakt.tv/oauth/token'
}

# Cache window properties to avoid repeated lookups
WINDOW_PROPERTIES = {
    'TRAKT_LOGIN_REQUIRED': 'TMDbHelper.Trakt.LoginRequired',
    'TRAKT_AUTH_RUNNING': 'TMDbHelper.TraktAuthCheckRunning',
    'TRAKT_ATTEMPTED_LOGIN': 'TraktAttemptedLogin'
}

# Pre-compile headers for better performance
BASE_HEADERS_TEMPLATE = {
    'trakt-api-version': '2',
    'Content-Type': 'application/json'
}


class TraktAPI(NoCacheRequestAPI):
    """Optimized TraktAPI with improved caching, threading, and performance"""
    
    # Class-level shared window instance
    _shared_window = None
    _window_lock = Thread()
    
    # Cached class attributes
    client_id = CLIENT_ID
    client_secret = CLIENT_SECRET
    user_token = USER_TOKEN
    
    def __init__(self, client_id=None, client_secret=None, user_token=None, 
                 login_if_required=False, force=False):
        super(TraktAPI, self).__init__(
            req_api_url=API_ENDPOINTS['BASE'], 
            req_api_name='TraktAPI', 
            timeout=20
        )

        # Update class-level credentials if provided
        TraktAPI.client_id = client_id or self.client_id
        TraktAPI.client_secret = client_secret or self.client_secret
        TraktAPI.user_token = user_token or self.user_token
        self.login_if_required = login_if_required
        
        # Cache frequently used values
        self._cached_headers_base = None
        self._last_auth_check = 0
        self._auth_cache_ttl = 5.0  # Cache auth status for 5 seconds
        self._cached_auth_status = None
    
    @property
    def window(self):
        """Cached window instance to avoid repeated instantiation"""
        if TraktAPI._shared_window is None:
            TraktAPI._shared_window = Window(10000)
        return TraktAPI._shared_window
    
    @property
    def headers_base(self):
        """Cached base headers to avoid repeated dict creation"""
        if self._cached_headers_base is None:
            self._cached_headers_base = BASE_HEADERS_TEMPLATE.copy()
            self._cached_headers_base['trakt-api-key'] = self.client_id
        return self._cached_headers_base
    
    @property
    def headers(self):
        """Optimized headers with authentication"""
        return self.get_headers(self.authenticator.access_token)

    def get_headers(self, access_token=None):
        """Optimized header generation with reduced dict operations"""
        headers = self.headers_base.copy()
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'
        return headers

    def get_headers_authorization(self, access_token=None):
        """Simplified authorization header generation"""
        return {'Authorization': f'Bearer {access_token}'} if access_token else {}

    @headers.setter
    def headers(self, value):
        """Headers setter - no-op for compatibility"""
        return

    @cached_property
    def authenticator(self):
        """Cached authenticator instance"""
        return TraktAuthenticator(self)

    @cached_property
    def dialog_noapikey_header(self):
        """Cached dialog header string"""
        return f'{get_localized(32007)} {self.req_api_name} {get_localized(32011)}'

    @cached_property
    def dialog_noapikey_text(self):
        """Cached dialog text string"""
        return get_localized(32012)

    def get_device_code(self):
        """Get device code for OAuth flow"""
        return self.get_api_request_json(
            API_ENDPOINTS['OAUTH_DEVICE_CODE'], 
            postdata={'client_id': self.client_id}
        )

    def get_authorisation_token(self, device_code):
        """Get authorization token using device code"""
        return self.get_api_request_json(
            API_ENDPOINTS['OAUTH_DEVICE_TOKEN'], 
            postdata={
                'code': device_code,
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }
        )

    def del_authorisation_token(self, access_token):
        """Revoke authorization token"""
        return self.get_api_request(
            API_ENDPOINTS['OAUTH_REVOKE'], 
            postdata={
                'token': access_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }
        )

    def set_authorisation_token(self, refresh_token):
        """Refresh authorization token"""
        return self.get_api_request_json(
            API_ENDPOINTS['OAUTH_TOKEN'], 
            postdata={
                'refresh_token': refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
                'grant_type': 'refresh_token'
            }
        )

    @property
    def is_authorized(self):
        """Cached authorization status to reduce API calls"""
        current_time = time.time()
        
        # Return cached result if within TTL
        if (self._cached_auth_status is not None and 
            current_time - self._last_auth_check < self._auth_cache_ttl):
            return self._cached_auth_status
        
        # Update cache
        self._cached_auth_status = self.authenticator.is_authorized
        self._last_auth_check = current_time
        return self._cached_auth_status

    def invalidate_auth_cache(self):
        """Manually invalidate auth cache when needed"""
        self._cached_auth_status = None
        self._last_auth_check = 0

    def authorize(self, forced=False, background=False):
        """Optimized authorization with better background handling"""
        if not self.is_authorized and (forced or self.login_if_required):
            if background:
                self._handle_background_auth()
                return False
            self.ask_to_login()
        return self.is_authorized

    def _handle_background_auth(self):
        """Handle background authorization efficiently"""
        self.authenticator.attempted_login = True
        self.window.setProperty(WINDOW_PROPERTIES['TRAKT_LOGIN_REQUIRED'], 'True')

    @property
    def attempted_login(self):
        """Get attempted login status"""
        return self.authenticator.attempted_login

    @attempted_login.setter
    def attempted_login(self, value):
        """Set attempted login status with window property sync"""
        self.authenticator.attempted_login = value
        self.window.setProperty(WINDOW_PROPERTIES['TRAKT_ATTEMPTED_LOGIN'], str(value))

    # Use class-level constant for mutex name
    mutex_lockname = 'TraktAskingForLogin'

    @mutexlock
    def ask_to_login(self):
        """Optimized login dialog with early exit"""
        if self.attempted_login:
            return

        dialog_response = Dialog().yesnocustom(
            self.dialog_noapikey_header,
            self.dialog_noapikey_text,
            nolabel=get_localized(222),
            yeslabel=get_localized(186),
            customlabel=get_localized(13170)
        )
        
        # Use dict lookup for better performance than if/elif
        response_handlers = {
            1: self.login,
            2: lambda: setattr(self, 'attempted_login', True)
        }

        handler = response_handlers.get(dialog_response)
        if handler:
            return handler()

    def logout(self):
        """Optimized logout with cache invalidation"""
        # Invalidate caches
        self.invalidate_auth_cache()
        
        # Reset authenticator
        self.authenticator = TraktAuthenticator(self)
        self.authenticator.logout()

    def login(self):
        """Optimized login with cache invalidation"""
        # Reset authenticator and caches
        self.authenticator = TraktAuthenticator(self)
        result = self.authenticator.login()
        
        # Invalidate auth cache to force refresh
        self.invalidate_auth_cache()
        return result

    def delete_response(self, *args, **kwargs):
        """Optimized DELETE request"""
        return self.get_simple_api_request(
            self.get_request_url(*args, **kwargs),
            headers=self.headers,
            method='delete'
        )

    def post_response(self, *args, postdata=None, response_method='post', **kwargs):
        """Optimized POST request with efficient JSON serialization"""
        url = self.get_request_url(*args, **kwargs)
        
        # Only serialize postdata if it exists
        if postdata:
            from tmdbhelper.lib.files.futils import json_dumps as data_dumps
            postdata = data_dumps(postdata)
        
        return self.get_simple_api_request(
            url,
            headers=self.headers,
            postdata=postdata,
            method=response_method
        )

    def get_response(self, *args, **kwargs):
        """Optimized GET request"""
        return self.get_api_request(
            self.get_request_url(*args, **kwargs), 
            headers=self.headers
        )

    def get_response_json(self, *args, **kwargs):
        """Optimized JSON GET request with better error handling"""
        try:
            response = self.get_api_request(
                self.get_request_url(*args, **kwargs), 
                headers=self.headers
            )
            return response.json() if response else {}
        except (ValueError, AttributeError):
            return {}

    @cached_property
    def trakt_syncdata(self):
        """Cached sync data instance"""
        return self.get_trakt_syncdata()

    def get_trakt_syncdata(self):
        """Get Trakt sync data if authorized"""
        if not self.is_authorized:
            return None
        
        from tmdbhelper.lib.api.trakt.sync.datasync import SyncData
        return SyncData(self)

    def start_auth_in_background(self):
        """Optimized background authentication with proper thread management"""
        # Check if auth check is already running
        if self.window.getProperty(WINDOW_PROPERTIES['TRAKT_AUTH_RUNNING']) == 'True':
            return
        
        def _run_auth_check():
            """Background auth check with proper cleanup"""
            try:
                self.window.setProperty(WINDOW_PROPERTIES['TRAKT_AUTH_RUNNING'], 'True')
                self.authorize(background=True)
            except Exception as e:
                # Log error but don't crash
                if hasattr(self, 'kodi_log'):
                    self.kodi_log(f"Background auth check failed: {e}", level=2)
            finally:
                self.window.setProperty(WINDOW_PROPERTIES['TRAKT_AUTH_RUNNING'], 'False')

        # Use daemon thread to avoid hanging on exit
        auth_thread = Thread(target=_run_auth_check, daemon=True)
        auth_thread.start()

    def cleanup(self):
        """Cleanup method for proper resource management"""
        # Clear cached properties
        if hasattr(self, '_cached_headers_base'):
            self._cached_headers_base = None
        
        # Invalidate auth cache
        self.invalidate_auth_cache()
        
        # Clear window properties if we're the last instance
        if TraktAPI._shared_window:
            self.window.setProperty(WINDOW_PROPERTIES['TRAKT_AUTH_RUNNING'], 'False')