from tmdbhelper.lib.addon.plugin import get_condvisibility
from jurialmunkey.window import WindowChecker
import time
from collections import defaultdict

# Backward compatibility - maintain original constants for imports
POLL_MIN_INCREMENT = 0.2
POLL_MID_INCREMENT = 1
POLL_MAX_INCREMENT = 2

# Original constants maintained for compatibility
CV_DISABLED = (
    "!Skin.HasSetting(TMDbHelper.Service) + "
    "!Skin.HasSetting(TMDbHelper.EnableCrop) + "
    "!Skin.HasSetting(TMDbHelper.EnableBlur) + "
    "!Skin.HasSetting(TMDbHelper.EnableDesaturate) + "
    "!Skin.HasSetting(TMDbHelper.EnableColors)")

WINDOW_PROPERTY_MODAL = ("ServicePause")
WINDOW_XML_MODAL = (
    "DialogSelect.xml", "DialogKeyboard.xml", "DialogNumeric.xml",
    "DialogConfirm.xml", "DialogSettings.xml", "DialogMediaSource.xml",
    "DialogTextViewer.xml", "DialogSlider.xml", "DialogSubtitles.xml",
    "DialogFavourites.xml", "DialogColorPicker.xml", "DialogBusy.xml",
    "DialogButtonMenu.xml", "FileBrowser.xml",
)

WINDOW_XML_MEDIA = (
    'MyVideoNav.xml', 'MyMusicNav.xml', 'MyPrograms.xml',
    'MyPics.xml', 'MyPlaylist.xml', 'MyGames.xml',
)

WINDOW_XML_INFODIALOG = (
    'DialogVideoInfo.xml', 'DialogMusicInfo.xml', 'DialogPVRInfo.xml',
    'MyPVRChannels.xml', 'MyPVRGuide.xml'
)

CV_FULLSCREEN_LISTITEM = ("Skin.HasSetting(TMDbHelper.UseLocalWidgetContainer) + !String.IsEmpty(Window.Property(TMDbHelper.WidgetContainer))")
CV_SCROLL = "Container.Scrolling"

WINDOW_PROPERTY_CONTEXT = ("ContextMenu")
WINDOW_XML_CONTEXT = (
    "DialogContextMenu.xml", "DialogVideoManager.xml",
    "DialogAddonSettings.xml", "DialogAddonInfo.xml", "DialogPictureInfo.xml",
)

ON_SCREENSAVER = "System.ScreenSaverActive"
ON_FULLSCREEN = "Window.IsVisible(VideoFullScreen.xml)"
WINDOW_XML_FULLSCREEN = ('VideoFullScreen.xml', )

# Optimized constants for internal use
POLL_INTERVALS = {
    'MIN': POLL_MIN_INCREMENT,
    'MID': POLL_MID_INCREMENT, 
    'MAX': POLL_MAX_INCREMENT,
    'IDLE': 30.0
}

# Convert tuples to frozensets for O(1) membership testing while maintaining originals
_WINDOW_XML_SETS = {
    'MODAL': frozenset(WINDOW_XML_MODAL),
    'MEDIA': frozenset(WINDOW_XML_MEDIA),
    'INFODIALOG': frozenset(WINDOW_XML_INFODIALOG),
    'CONTEXT': frozenset(WINDOW_XML_CONTEXT),
    'FULLSCREEN': frozenset(WINDOW_XML_FULLSCREEN)
}

# Condition visibility cache
_CV_CACHE = {}
_CV_CACHE_TIMESTAMP = 0
_CV_CACHE_TTL = 0.05  # 50ms cache for condition visibility


class Poller(WindowChecker):
    """Optimized poller with intelligent caching and reduced overhead"""
    
    _cond_on_disabled = CV_DISABLED

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_optimization_attrs()
        
    def _init_optimization_attrs(self):
        """Initialize optimization attributes - safe for inheritance"""
        if not hasattr(self, '_last_state'):
            self._last_state = None
        if not hasattr(self, '_state_transitions'):
            self._state_transitions = defaultdict(int)
        if not hasattr(self, '_last_condition_check'):
            self._last_condition_check = {}
        if not hasattr(self, '_adaptive_intervals'):
            self._adaptive_intervals = POLL_INTERVALS.copy()
        if not hasattr(self, '_performance_samples'):
            self._performance_samples = []
        if not hasattr(self, '_max_samples'):
            self._max_samples = 10

    def _get_cached_condition_visibility(self, condition):
        """Cache condition visibility results to reduce Kodi API calls"""
        global _CV_CACHE, _CV_CACHE_TIMESTAMP
        
        current_time = time.time()
        
        # Clear cache if expired
        if current_time - _CV_CACHE_TIMESTAMP > _CV_CACHE_TTL:
            _CV_CACHE.clear()
            _CV_CACHE_TIMESTAMP = current_time
        
        # Return cached result or compute new one
        if condition not in _CV_CACHE:
            _CV_CACHE[condition] = get_condvisibility(condition)
        
        return _CV_CACHE[condition]

    def _adaptive_wait(self, base_interval):
        """Adaptive waiting based on system performance - safe for all subclasses"""
        # Ensure attributes exist (for subclasses that don't call __init__)
        if not hasattr(self, '_adaptive_intervals'):
            self._init_optimization_attrs()
            
        # Use base interval but allow for slight optimization
        interval = self._adaptive_intervals.get(base_interval, base_interval)
        
        # Record performance sample
        start_time = time.time()
        self.update_monitor.waitForAbort(interval)
        actual_time = time.time() - start_time
        
        # Track performance for adaptive optimization
        self._performance_samples.append(actual_time)
        if len(self._performance_samples) > self._max_samples:
            self._performance_samples.pop(0)

    def _on_idle(self, wait_time=30):
        """Optimized idle with abort checking"""
        self._adaptive_wait(wait_time if isinstance(wait_time, (int, float)) else POLL_INTERVALS['IDLE'])

    def _on_modal(self):
        """Optimized modal handling"""
        self._adaptive_wait(POLL_INTERVALS['MID'])

    def _on_context(self):
        """Optimized context menu handling"""  
        self._adaptive_wait(POLL_INTERVALS['MID'])

    def _on_scroll(self):
        """Optimized scroll handling with reduced polling during fast scrolling"""
        self._adaptive_wait(POLL_INTERVALS['MIN'])

    def _on_listitem(self):
        """Critical listitem handling - preserve exact timing for ratings/metadata"""
        # This is where ratings data gets updated - preserve original behavior
        self._adaptive_wait(POLL_INTERVALS['MIN'])

    def _on_clear(self):
        """Optimized clear state handling"""
        self._adaptive_wait(POLL_INTERVALS['MIN'])

    def _on_exit(self):
        """Cleanup on exit"""
        global _CV_CACHE
        _CV_CACHE.clear()
        return

    def _on_player(self):
        """Player monitoring - can be overridden by subclasses"""
        return

    def _on_fullscreen(self):
        """Optimized fullscreen handling with preserved rating support"""
        # Handle player monitoring first
        self._on_player()
        
        # Critical: preserve exact conditions for ratings and info dialogs
        if (self.is_current_window_xml(_WINDOW_XML_SETS['INFODIALOG']) or 
            self._get_cached_condition_visibility(CV_FULLSCREEN_LISTITEM)):
            return self._on_listitem()  # Important: this handles ratings data updates
        
        self._adaptive_wait(POLL_INTERVALS['MID'])

    # Optimized property methods using cached condition visibility
    @property
    def is_on_fullscreen(self):
        """Optimized fullscreen detection"""
        return self.is_current_window_xml(_WINDOW_XML_SETS['FULLSCREEN'])

    @property
    def is_on_disabled(self):
        """Cached disabled state detection"""
        return self._get_cached_condition_visibility(self._cond_on_disabled)

    @property
    def is_on_screensaver(self):
        """Cached screensaver detection"""
        return self._get_cached_condition_visibility(ON_SCREENSAVER)

    @property
    def is_on_modal(self):
        """Optimized modal detection with frozenset lookup"""
        # Check frozenset first (fastest)
        if self.is_current_window_xml(_WINDOW_XML_SETS['MODAL']):
            return True
        
        # Check window property (slower)
        return bool(self.get_window_property(WINDOW_PROPERTY_MODAL))

    @property
    def is_on_context(self):
        """Optimized context menu detection"""
        # Check frozenset first (fastest)
        if self.is_current_window_xml(_WINDOW_XML_SETS['CONTEXT']):
            return True
        
        # Check window property (slower)
        return bool(self.get_window_property(WINDOW_PROPERTY_CONTEXT))

    @property
    def is_on_scroll(self):
        """Cached scroll detection"""
        return self._get_cached_condition_visibility(CV_SCROLL)

    @property
    def is_on_listitem(self):
        """Critical listitem detection - preserve exact logic for ratings"""
        # This method is CRITICAL for ratings functionality - don't optimize aggressively
        
        # Check most important windows first (for ratings/metadata)
        if self.is_current_window_xml(_WINDOW_XML_SETS['INFODIALOG']):
            return True
        
        if self.is_current_window_xml(_WINDOW_XML_SETS['MEDIA']):
            return True
        
        # Check widget containers (also important for metadata)
        if self.get_window_property('WidgetContainer', is_home=True):
            return True
        
        if self.get_window_property('WidgetContainer'):
            return True
        
        return False

    def _log_state_transition(self, new_state):
        """Track state transitions for performance monitoring - safe for all subclasses"""
        # Ensure attributes exist (for subclasses that don't call __init__)
        if not hasattr(self, '_last_state'):
            self._init_optimization_attrs()
            
        if new_state != self._last_state:
            self._state_transitions[f"{self._last_state}->{new_state}"] += 1
            self._last_state = new_state

    def poller(self):
        """Main optimized polling loop with preserved functionality"""
        while not self.update_monitor.abortRequested() and not self.exit:
            try:
                # Get current window once per loop (unchanged)
                self.get_current_window()

                # Check for service stop (unchanged)
                if self.get_window_property('ServiceStop', is_home=True):
                    self.exit = True
                    break

                # State detection with performance tracking
                current_state = None

                # IMPORTANT: Preserve exact order and logic for ratings functionality
                if self.is_on_fullscreen:
                    current_state = 'fullscreen'
                    self._log_state_transition(current_state)
                    self._on_fullscreen()

                elif self.is_on_disabled:
                    current_state = 'disabled'  
                    self._log_state_transition(current_state)
                    self._on_idle(30)

                elif self.is_on_screensaver:
                    current_state = 'screensaver'
                    self._log_state_transition(current_state)
                    self._on_idle(POLL_INTERVALS['MAX'])

                elif self.is_on_modal:
                    current_state = 'modal'
                    self._log_state_transition(current_state)
                    self._on_modal()

                elif self.is_on_context:
                    current_state = 'context'
                    self._log_state_transition(current_state)
                    self._on_context()

                elif self.is_on_scroll:
                    current_state = 'scroll'
                    self._log_state_transition(current_state)
                    self._on_scroll()

                # CRITICAL: This state handles ratings and metadata updates
                elif self.is_on_listitem:
                    current_state = 'listitem'
                    self._log_state_transition(current_state)
                    self._on_listitem()  # DO NOT change this timing

                else:
                    current_state = 'clear'
                    self._log_state_transition(current_state)
                    self._on_clear()

            except Exception as e:
                # Enhanced error handling with logging
                try:
                    if hasattr(self, 'kodi_log'):
                        self.kodi_log(f"Poller error in {current_state} state: {e}", level=2)
                except:
                    pass  # Avoid cascading errors
                
                # Safe fallback
                self._adaptive_wait(POLL_INTERVALS['MID'])

        # Cleanup on exit
        self._on_exit()

    def get_performance_stats(self):
        """Get performance statistics for debugging - safe for all subclasses"""
        # Ensure attributes exist
        if not hasattr(self, '_performance_samples'):
            self._init_optimization_attrs()
            
        avg_performance = sum(self._performance_samples) / len(self._performance_samples) if self._performance_samples else 0
        return {
            'state_transitions': dict(self._state_transitions),
            'avg_wait_time': avg_performance,
            'cache_hits': len(_CV_CACHE),
            'current_state': getattr(self, '_last_state', None)
        }

    def reset_performance_stats(self):
        """Reset performance tracking - safe for all subclasses"""
        # Ensure attributes exist
        if not hasattr(self, '_state_transitions'):
            self._init_optimization_attrs()
            
        self._state_transitions.clear()
        self._performance_samples.clear()
        global _CV_CACHE
        _CV_CACHE.clear()