from jurialmunkey.window import get_property
from jurialmunkey.ftools import cached_property
from tmdbhelper.lib.addon.plugin import get_setting
from tmdbhelper.lib.addon.logger import kodi_log
from functools import wraps


class PlayerScrobbler():
    # Class-level constants to avoid repeated string operations
    VALID_MOVIE_TYPES = frozenset(['movie'])
    VALID_TV_TYPES = frozenset(['season', 'episode', 'tv'])
    SCROBBLE_METHODS = frozenset(['start', 'pause', 'stop'])
    WATCH_THRESHOLD = 75.0  # Percentage threshold for watched status
    
    # Pre-compile format strings for better performance
    CONTENT_ID_FORMAT = "{}.{}.{}.{}"
    LOG_FORMAT = "SCROBBLER: [{}] {}"
    
    def __init__(self, trakt_api, total_time):
        self.trakt_api = trakt_api
        self.current_time = 0
        self.total_time = total_time
        
        # Cache playerstring data once during initialization
        playerstring = self._get_playerstring()
        self.tvdb_id = playerstring.get('tvdb_id')
        self.imdb_id = playerstring.get('imdb_id')
        self.tmdb_id = playerstring.get('tmdb_id')
        self.tmdb_type = self._get_tmdb_type(playerstring.get('tmdb_type'))
        self.season = int(playerstring.get('season') or 0)
        self.episode = int(playerstring.get('episode') or 0)
        
        # State flags
        self.stopped = False
        self.started = False
        
        # Cache frequently used computed values
        self._content_id = None
        self._trakt_item = None
        self._auth_checked = False
        self._is_authorized = None
    
    def _get_playerstring(self):
        """Get playerstring data once and cache it"""
        from tmdbhelper.lib.player.details.playerstring import read_playerstring
        return read_playerstring()
    
    def _get_tmdb_type(self, tmdb_type):
        """Optimized tmdb_type determination using sets"""
        if not tmdb_type:
            return ''
        if tmdb_type in self.VALID_MOVIE_TYPES:
            return 'movie'
        if tmdb_type in self.VALID_TV_TYPES:
            return 'tv'
        return ''
    
    @staticmethod
    def is_trakt_authorized(func):
        """Optimized decorator with better caching and early exits"""
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Cache authorization check to avoid repeated property access
            if not self._auth_checked:
                self._is_authorized = (
                    get_property('TraktIsAuth', is_type=float) and
                    get_setting('trakt_scrobbling') and
                    self.trakt_api.is_authorized and
                    bool(self.trakt_item)
                )
                self._auth_checked = True
            
            if not self._is_authorized:
                return None
                
            return func(self, *args, **kwargs)
        return wrapper
    
    @staticmethod  
    def is_scrobbling(func):
        """Optimized decorator with combined conditions"""
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Combined condition check for better performance
            if (self.stopped or 
                not self.tmdb_type or 
                not self.tmdb_id or 
                not self.total_time):
                return None
            return func(self, *args, **kwargs)
        return wrapper

    @property
    def content_id(self):
        """Cached content_id to avoid repeated string formatting"""
        if self._content_id is None:
            self._content_id = self.CONTENT_ID_FORMAT.format(
                self.tmdb_type, self.tmdb_id, self.season, self.episode
            )
        return self._content_id

    @property
    def progress(self):
        """Optimized progress calculation with bounds checking"""
        if not self.total_time:
            return 0.0
        return min(100.0, max(0.0, (self.current_time / self.total_time) * 100))

    def is_match(self, tmdb_type, tmdb_id):
        """Optimized matching with string comparison avoided where possible"""
        # Use direct comparison first (faster for integers)
        if self.tmdb_id != tmdb_id:
            return False
        # Only do string comparison if needed
        return self.tmdb_type == tmdb_type

    @is_scrobbling
    def update_time(self, tmdb_type, tmdb_id, current_time):
        """Optimized time update with early exit"""
        if not self.is_match(tmdb_type, tmdb_id):
            return
        self.current_time = current_time
        # Invalidate cached progress-dependent values
        self._trakt_item = None

    @property
    def trakt_item(self):
        """Cached trakt_item with lazy evaluation"""
        if self._trakt_item is None:
            self._trakt_item = self._build_trakt_item()
        return self._trakt_item

    @is_scrobbling
    def _build_trakt_item(self):
        """Build trakt item data structure"""
        base_item = {'progress': self.progress}
        
        if self.tmdb_type == 'tv':
            if not (self.season and self.episode):
                return {}
            base_item.update({
                'show': {'ids': {'tmdb': self.tmdb_id}},
                'episode': {'season': self.season, 'number': self.episode}
            })
        elif self.tmdb_type == 'movie':
            base_item['movie'] = {'ids': {'tmdb': self.tmdb_id}}
        else:
            return {}
            
        return base_item

    @is_scrobbling
    @is_trakt_authorized
    def trakt_scrobbling(self, method):
        """Optimized trakt scrobbling with validation"""
        if method not in self.SCROBBLE_METHODS:
            return
        
        # Update progress in existing item rather than rebuilding
        current_item = self.trakt_item.copy()
        current_item['progress'] = self.progress
        
        self.trakt_api.get_api_request(
            f'https://api.trakt.tv/scrobble/{method}',
            postdata=current_item,
            headers=self.trakt_api.headers,
            method='json'
        )

    @is_scrobbling
    def start(self, tmdb_type, tmdb_id):
        """Optimized start with consolidated logging"""
        if not self.is_match(tmdb_type, tmdb_id):
            return self.stop(tmdb_type, tmdb_id)
        
        kodi_log(self.LOG_FORMAT.format('Start', self.content_id), 2)
        self.trakt_scrobbling('start')
        self.started = True

    @is_scrobbling
    def pause(self, tmdb_type, tmdb_id):
        """Optimized pause with consolidated logging"""
        if not self.is_match(tmdb_type, tmdb_id):
            return self.stop(tmdb_type, tmdb_id)
        
        kodi_log(self.LOG_FORMAT.format('Pause', self.content_id), 2)
        self.trakt_scrobbling('pause')

    @is_scrobbling
    def stop(self, tmdb_type, tmdb_id):
        """Optimized stop with early exit"""
        if not self.started:
            return
        
        kodi_log(self.LOG_FORMAT.format('Stop', self.content_id), 2)
        
        # Execute all stop actions
        self.trakt_scrobbling('stop')
        self._handle_watched_status()
        self._handle_tmdb_ratings()
        self._update_stats()
        
        self.stopped = True

    def _handle_watched_status(self):
        """Consolidated watched status handling"""
        if not self._should_mark_watched():
            return
        self._set_kodi_watched()

    def _handle_tmdb_ratings(self):
        """Consolidated TMDb ratings handling"""
        if not self._should_rate_tmdb():
            return
        self._set_tmdb_ratings()

    def _should_mark_watched(self):
        """Check if item should be marked as watched"""
        return (self.current_time and 
                self.progress >= self.WATCH_THRESHOLD)

    def _should_rate_tmdb(self):
        """Check if item should be rated on TMDb"""
        return (get_setting('tmdb_user_token', 'str') and
                get_setting('tmdb_user_rate_after_watching') and
                self.current_time and
                self.progress >= self.WATCH_THRESHOLD and
                self.content_id != get_property('Scrobbler.LastRated.ContentID'))

    @is_scrobbling
    @is_trakt_authorized
    def _update_stats(self):
        """Optimized stats update"""
        from tmdbhelper.lib.script.method.trakt import get_stats
        from tmdbhelper.lib.addon.consts import LASTACTIVITIES_DATA
        
        get_property(LASTACTIVITIES_DATA, clear_property=True)
        get_stats()

    @is_scrobbling
    def _set_tmdb_ratings(self):
        """Optimized TMDb ratings with reduced property access"""
        # Mark as rated to prevent duplicate ratings
        get_property('Scrobbler.LastRated.ContentID', set_property=self.content_id)
        
        from tmdbhelper.lib.script.sync.tmdb.menu import sync_item
        kodi_log(self.LOG_FORMAT.format('Rate', self.content_id), 2)
        
        sync_item(
            tmdb_type=self.tmdb_type,
            tmdb_id=self.tmdb_id,
            season=self.season or None,
            episode=self.episode or None,
            sync_type='rating'
        )

    @is_scrobbling
    def _set_kodi_watched(self):
        """Optimized Kodi watched status with consolidated RPC calls"""
        import tmdbhelper.lib.api.kodi.rpc as rpc
        
        if self.tmdb_type == 'tv':
            self._set_tv_watched(rpc)
        elif self.tmdb_type == 'movie':
            self._set_movie_watched(rpc)

    def _set_tv_watched(self, rpc):
        """Handle TV show watched status"""
        # Get TV show database ID
        tvshowid = rpc.KodiLibrary('tvshow').get_info(
            info='dbid',
            imdb_id=self.imdb_id,
            tmdb_id=self.tmdb_id,
            tvdb_id=self.tvdb_id
        )
        
        if not tvshowid:
            kodi_log(self.LOG_FORMAT.format('Kodi] No SHOW', self.content_id), 2)
            return
        
        # Get episode database ID
        dbid = rpc.KodiLibrary('episode', tvshowid).get_info(
            info='dbid',
            season=self.season,
            episode=self.episode
        )
        
        if not dbid:
            kodi_log(self.LOG_FORMAT.format('Kodi] No DBID', self.content_id), 2)
            return
        
        rpc.set_watched(dbid=dbid, dbtype='episode')
        kodi_log(self.LOG_FORMAT.format('Kodi', self.content_id), 2)

    def _set_movie_watched(self, rpc):
        """Handle movie watched status"""
        dbid = rpc.KodiLibrary('movie').get_info(
            info='dbid',
            imdb_id=self.imdb_id,
            tmdb_id=self.tmdb_id,
            tvdb_id=self.tvdb_id
        )
        
        if not dbid:
            kodi_log(self.LOG_FORMAT.format('Kodi] No DBID', self.content_id), 2)
            return
        
        rpc.set_watched(dbid=dbid, dbtype='movie')
        kodi_log(self.LOG_FORMAT.format('Kodi', self.content_id), 2)

    def invalidate_cache(self):
        """Method to manually invalidate caches if needed"""
        self._content_id = None
        self._trakt_item = None
        self._auth_checked = False
        self._is_authorized = None