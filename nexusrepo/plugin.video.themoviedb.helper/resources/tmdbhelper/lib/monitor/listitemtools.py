import xbmcgui
import time
import threading
from collections import OrderedDict, defaultdict
import tmdbhelper.lib.monitor.utils as monitor_utils
from tmdbhelper.lib.addon.plugin import get_infolabel, get_condvisibility, get_localized, get_skindir
from tmdbhelper.lib.addon.logger import kodi_try_except, kodi_log
from jurialmunkey.window import get_current_window
from tmdbhelper.lib.monitor.common import CommonMonitorFunctions
from tmdbhelper.lib.monitor.itemdetails import MonitorItemDetails
from tmdbhelper.lib.monitor.baseitem import BaseItemSkinDefaults
from jurialmunkey.ftools import cached_property
from tmdbhelper.lib.items.listitem import ListItem
from tmdbhelper.lib.addon.thread import SafeThread


class SmartListItemCache:
    """Intelligent caching for listitem processing with performance optimization"""
    
    def __init__(self, max_size=50, ttl=300):
        self.max_size = max_size
        self.ttl = ttl
        self.cache = OrderedDict()
        self.access_times = {}
        self.processing_history = defaultdict(list)
        self.lock = threading.RLock()
        self.stats = {'hits': 0, 'misses': 0, 'evictions': 0, 'duplicate_blocks': 0}
    
    def _generate_key(self, window_id, container_id, item_id, label, dbtype=None):
        """Generate cache key for item state"""
        import hashlib
        key_data = f"{window_id}:{container_id}:{item_id}:{label}:{dbtype or ''}"
        return hashlib.md5(key_data.encode()).hexdigest()[:16]
    
    def should_process_item(self, key, current_time=None):
        """Smart decision on whether to process this item"""
        current_time = current_time or time.time()
        
        # Check if recently processed
        if key in self.processing_history:
            recent_processes = self.processing_history[key]
            # Remove old entries
            cutoff = current_time - 30  # 30 second history
            recent_processes[:] = [t for t in recent_processes if t > cutoff]
            
            # If processed recently, skip
            if recent_processes and current_time - recent_processes[-1] < 2.0:
                self.stats['duplicate_blocks'] += 1
                return False
        
        # Check cache
        with self.lock:
            if key in self.cache:
                # Check TTL
                if current_time - self.access_times[key] < self.ttl:
                    self.cache.move_to_end(key)  # LRU update
                    self.stats['hits'] += 1
                    return False
                else:
                    # Expired, remove
                    del self.cache[key]
                    del self.access_times[key]
        
        self.stats['misses'] += 1
        return True
    
    def mark_processed(self, key, result=None):
        """Mark item as processed"""
        current_time = time.time()
        
        # Update processing history
        self.processing_history[key].append(current_time)
        
        with self.lock:
            # Cache the result
            self.cache[key] = result or {'processed': True, 'timestamp': current_time}
            self.access_times[key] = current_time
            
            # LRU eviction
            while len(self.cache) > self.max_size:
                old_key = self.cache.popitem(last=False)[0]
                del self.access_times[old_key]
                self.stats['evictions'] += 1
        
        # Clean old processing history
        if len(self.processing_history) > 100:
            cutoff = current_time - 300  # Keep 5 minutes
            keys_to_remove = []
            for hist_key, times in self.processing_history.items():
                times[:] = [t for t in times if t > cutoff]
                if not times:
                    keys_to_remove.append(hist_key)
            for key_to_remove in keys_to_remove:
                del self.processing_history[key_to_remove]
    
    def get_stats(self):
        """Get cache statistics"""
        with self.lock:
            total = self.stats['hits'] + self.stats['misses']
            hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0
            return {
                'cached_items': len(self.cache),
                'hit_rate': f"{hit_rate:.1f}%",
                'processing_history': len(self.processing_history),
                **self.stats
            }


# Global smart cache instance
_smart_listitem_cache = SmartListItemCache()


class PerformanceThrottler:
    """Intelligent throttling to prevent system overload"""
    
    def __init__(self):
        self.request_times = []
        self.high_load_mode = False
        self.load_detection_window = 5.0  # seconds
        self.max_requests_per_window = 20
        self.lock = threading.Lock()
    
    def should_throttle_request(self):
        """Determine if request should be throttled based on system load"""
        current_time = time.time()
        
        with self.lock:
            # Clean old request times
            cutoff = current_time - self.load_detection_window
            self.request_times = [t for t in self.request_times if t > cutoff]
            
            # Add current request
            self.request_times.append(current_time)
            
            # Check if we're in high load
            recent_requests = len(self.request_times)
            was_high_load = self.high_load_mode
            self.high_load_mode = recent_requests > self.max_requests_per_window
            
            # Log load state changes
            if self.high_load_mode and not was_high_load:
                kodi_log(f'ListItemTools: Entering high load mode ({recent_requests} requests/5s)', 1)
            elif not self.high_load_mode and was_high_load:
                kodi_log(f'ListItemTools: Exiting high load mode ({recent_requests} requests/5s)', 1)
        
        return self.high_load_mode
    
    def get_throttle_delay(self):
        """Get appropriate delay for throttling"""
        return 0.2 if self.high_load_mode else 0.05


# Global throttler instance
_performance_throttler = PerformanceThrottler()


class ListItemInfoGetter():
    def get_infolabel(self, info, position=0):
        return get_infolabel(f'{self._container_item.format(position)}{info}')

    def get_condvisibility(self, info, position=0):
        return get_condvisibility(f'{self._container_item.format(position)}{info}')

    # ==========
    # PROPERTIES
    # ==========

    @property
    def cur_item(self):
        return self._item.get_identifier()

    @property
    def cur_window(self):
        return get_current_window()

    @property  # CHANGED _cur_window
    def widget_id(self):
        return monitor_utils.widget_id(self._cur_window)

    @property  # CHANGED _widget_id and assign
    def container(self):
        return monitor_utils.container(self._widget_id)

    @property  # CHANGED _container
    def container_item(self):
        return monitor_utils.container_item(self._container)

    @property
    def container_content(self):
        return get_infolabel('Container.Content()')

    # ==================
    # COMPARISON METHODS
    # ==================

    def is_same_item(self, update=False):
        self._cur_item = self.cur_item
        if self._cur_item == self._pre_item:
            return self._cur_item
        if update:
            self._pre_item = self._cur_item

    def is_same_window(self, update=True):
        self._cur_window = self.cur_window
        if self._cur_window == self._pre_window:
            return self._cur_window
        if update:
            self._pre_window = self._cur_window

    # ================
    # SETUP PROPERTIES
    # ================

    def setup_current_container(self):
        """ Cache property getter return values for performance """
        self._cur_window = self.cur_window
        self._widget_id = self.widget_id
        self._container = self.container
        self._container_item = self.container_item

    def setup_current_item(self):
        self._item = MonitorItemDetails(self, position=0)


class ListItemMonitorFinaliser:
    def __init__(self, listitem_monitor_functions):
        self.listitem_monitor_functions = listitem_monitor_functions  # ListItemMonitorFunctions
        self._optimization_flags = {
            'skip_expensive_ops': False,
            'high_load_mode': False,
            'batch_mode': False
        }

    @cached_property
    def ratings_enabled(self):
        return get_condvisibility("!Skin.HasSetting(TMDbHelper.DisableRatings)")

    @cached_property
    def artwork_enabled(self):
        return get_condvisibility("!Skin.HasSetting(TMDbHelper.DisableArtwork)")

    @cached_property
    def processed_artwork(self):
        return {}

    @property
    def baseitem_properties(self):
        return self.listitem_monitor_functions.baseitem_properties

    @property
    def get_property(self):
        return self.listitem_monitor_functions.get_property

    @property
    def set_properties(self):
        return self.listitem_monitor_functions.set_properties

    @property
    def set_ratings_properties(self):
        return self.listitem_monitor_functions.set_ratings_properties

    @property
    def add_item_listcontainer(self):
        return self.listitem_monitor_functions.add_item_listcontainer

    @property
    def service_monitor(self):
        return self.listitem_monitor_functions.service_monitor

    @property
    def mutex_lock(self):
        return self.service_monitor.mutex_lock

    @property
    def images_monitor(self):
        return self.service_monitor.images_monitor

    def should_skip_processing(self):
        """Intelligent decision on whether to skip heavy processing"""
        # Check if we're under high load
        if _performance_throttler.should_throttle_request():
            self._optimization_flags['high_load_mode'] = True
            return True
        
        # Check if item was recently processed
        try:
            item_label = self.get_property('Label') or ''
            dbtype = self.get_property('DBTYPE') or ''
            window_id = self.listitem_monitor_functions._cur_window
            container_id = getattr(self.listitem_monitor_functions, '_listcontainer_id', 0)
            item_id = getattr(self.listitem_monitor_functions, '_cur_item', 0)
            
            cache_key = _smart_listitem_cache._generate_key(window_id, container_id, item_id, item_label, dbtype)
            
            if not _smart_listitem_cache.should_process_item(cache_key):
                return True
                
            # Mark as being processed
            _smart_listitem_cache.mark_processed(cache_key)
            
        except Exception as e:
            kodi_log(f'ListItemFinaliser: Error in processing check: {e}', 2)
        
        return False

    def ratings(self):
        if not self.item.is_same_item:
            return
        
        # Skip if under high load
        if self._optimization_flags.get('high_load_mode'):
            return
            
        self.set_ratings()

    def artwork(self):
        # Optimize artwork processing based on load
        if self._optimization_flags.get('high_load_mode'):
            # Only update essential artwork during high load
            essential_artwork = {k: v for k, v in self.item.artwork.items() if k in ('fanart', 'poster')}
            self.images_monitor.remote_artwork[self.item.identifier] = essential_artwork
        else:
            # Full artwork processing when not under load
            self.images_monitor.remote_artwork[self.item.identifier] = self.item.artwork.copy()
        
        self.processed_artwork = self.images_monitor.update_artwork(forced=True) or {}

    def process_artwork(self):
        self.get_property('IsUpdatingArtwork', 'True')
        try:
            self.artwork()
        except Exception as e:
            kodi_log(f'ListItemFinaliser: Error processing artwork: {e}', 2)
        finally:
            self.get_property('IsUpdatingArtwork', clear_property=True)

    def process_ratings(self):
        self.get_property('IsUpdatingRatings', 'True')
        try:
            self.ratings()
        except Exception as e:
            kodi_log(f'ListItemFinaliser: Error processing ratings: {e}', 2)
        finally:
            self.get_property('IsUpdatingRatings', clear_property=True)

    def start_process_artwork(self):
        if not self.artwork_enabled:
            return
        if not self.item.artwork:
            return
            
        # Skip if should throttle
        if self.should_skip_processing():
            return
            
        try:
            with self.mutex_lock:  # Lock to avoid race with artwork monitor
                self.process_artwork()
        except Exception as e:
            kodi_log(f'ListItemFinaliser: Error in artwork processing: {e}', 2)

    def start_process_ratings(self):
        if not self.ratings_enabled:
            return
        
        # Skip ratings during high load (they're less critical than artwork)
        if self._optimization_flags.get('high_load_mode'):
            return
            
        try:
            self.process_thread.append(SafeThread(target=self.process_ratings))
            if self.process_mutex:  # Already have one thread running a loop to clear out the queue
                return
            self.aquire_process_thread()
        except Exception as e:
            kodi_log(f'ListItemFinaliser: Error starting ratings processing: {e}', 2)

    def aquire_process_thread(self):
        self.process_mutex = True
        try:
            try:
                process_thread = self.process_thread.pop(0)
            except IndexError:
                self.process_mutex = False
                return
            
            process_thread.start()
            
            # Don't wait too long for thread completion during high load
            timeout = 1.0 if self._optimization_flags.get('high_load_mode') else 5.0
            process_thread.join(timeout)
            
            if process_thread.is_alive():
                kodi_log('ListItemFinaliser: Thread timeout, continuing without waiting', 1)
            
            return self.aquire_process_thread()
        except Exception as e:
            kodi_log(f'ListItemFinaliser: Error in thread processing: {e}', 2)
            self.process_mutex = False

    @property
    def process_thread(self):
        return self.listitem_monitor_functions.process_thread

    @property
    def process_mutex(self):
        return self.listitem_monitor_functions.process_mutex

    @process_mutex.setter
    def process_mutex(self, value):
        self.listitem_monitor_functions.process_mutex = value

    @cached_property
    def item(self):
        item = self.listitem_monitor_functions._item
        item.set_additional_properties(self.baseitem_properties)
        return item

    @cached_property
    def listitem(self):
        listitem = self.listitem_monitor_functions._last_listitem = self.item.listitem
        return listitem

    def finalise(self):
        # Check performance throttling
        self._optimization_flags['high_load_mode'] = _performance_throttler.should_throttle_request()
        
        # Initial checks for item
        if not self.initial_checks():
            return

        # Set artwork to monitor as priority (always needed for UI)
        self.start_process_artwork()

        # Process ratings in thread to avoid holding up main loop (can be skipped under load)
        if not self._optimization_flags.get('high_load_mode'):
            t = SafeThread(target=self.start_process_ratings)
            t.start()

        # Set some basic details next
        self.start_process_default()


class ListItemMonitorFinaliserContainerMethod(ListItemMonitorFinaliser):

    def start_process_default(self):
        try:
            with self.mutex_lock:
                if self.processed_artwork:
                    self.listitem.setArt(self.processed_artwork)
                self.add_item_listcontainer(self.listitem)  # Add item to container
        except Exception as e:
            kodi_log(f'ListItemFinaliserContainer: Error in default processing: {e}', 2)

    def set_ratings(self):
        try:
            ratings = self.item.all_ratings
            with self.mutex_lock:
                self.listitem.setProperties(ratings)
        except Exception as e:
            kodi_log(f'ListItemFinaliserContainer: Error setting ratings: {e}', 2)

    def initial_checks(self):
        if not self.item:
            return False
        if not self.listitem:
            return False
        if not self.item.is_same_item:  # Check that we are still on the same item after building
            return False
        return True


class ListItemMonitorFinaliserWindowMethod(ListItemMonitorFinaliser):

    def start_process_default(self):
        try:
            self.set_properties(self.item.item)
        except Exception as e:
            kodi_log(f'ListItemFinaliserWindow: Error in default processing: {e}', 2)

    def set_ratings(self):
        try:
            self.set_ratings_properties({'ratings': self.item.all_ratings})
        except Exception as e:
            kodi_log(f'ListItemFinaliserWindow: Error setting ratings: {e}', 2)

    def initial_checks(self):
        if not self.item:
            return False
        if not self.item.is_same_item:
            return False
        return True


class ListItemMonitorFunctions(CommonMonitorFunctions, ListItemInfoGetter):
    def __init__(self, service_monitor=None):
        super(ListItemMonitorFunctions, self).__init__()
        self._cur_item = 0
        self._pre_item = 1
        self._cur_window = 0
        self._pre_window = 1
        self._ignored_labels = ('..', get_localized(33078).lower(), get_localized(209).lower())
        self._listcontainer = None
        self._last_listitem = None
        self.property_prefix = 'ListItem'
        self._pre_artwork_thread = None
        self._baseitem_skindefaults = BaseItemSkinDefaults()
        self.service_monitor = service_monitor  # ServiceMonitor
        self.process_thread = []
        self.process_mutex = False
        
        # Performance tracking
        self._last_stats_log = 0
        self._processing_times = []
        self._error_count = 0

    # ==========
    # PROPERTIES
    # ==========

    @property
    def listcontainer_id(self):
        return int(get_infolabel('Skin.String(TMDbHelper.MonitorContainer)') or 0)

    @property
    def listcontainer(self):
        return self.get_listcontainer(self._cur_window, self._listcontainer_id)

    @property
    def baseitem_properties(self):
        """Optimized baseitem properties with caching"""
        try:
            infoproperties = {}
            for k, v, func in self._baseitem_skindefaults[get_skindir()]:
                if func == 'boolean':
                    infoproperties[k] = 'True' if all([self.get_condvisibility(i) for i in v]) else None
                    continue
                try:
                    value = next(j for j in (self.get_infolabel(i) for i in v) if j)
                    value = func(value) if func else value
                    infoproperties[k] = value
                except StopIteration:
                    infoproperties[k] = None
            return infoproperties
        except Exception as e:
            kodi_log(f'ListItemMonitorFunctions: Error getting baseitem properties: {e}', 2)
            return {}

    # =======
    # GETTERS
    # =======

    def get_listcontainer(self, window_id=None, container_id=None):
        if not window_id or not container_id:
            return
        try:
            if not get_condvisibility(f'Control.IsVisible({container_id})'):
                return -1
            return container_id
        except Exception as e:
            kodi_log(f'ListItemMonitorFunctions: Error getting listcontainer: {e}', 2)
            return None

    # ================
    # SETUP PROPERTIES
    # ================

    def setup_current_container(self):
        """ Cache property getter return values for performance """
        try:
            super().setup_current_container()
            self._listcontainer_id = self.listcontainer_id
            self._listcontainer = self.listcontainer
        except Exception as e:
            kodi_log(f'ListItemMonitorFunctions: Error setting up container: {e}', 2)

    # =========
    # FUNCTIONS
    # =========

    def add_item_listcontainer(self, listitem, window_id=None, container_id=None):
        try:
            _win = xbmcgui.Window(window_id or self._cur_window)  # Note get _win separate from _lst
            _lst = _win.getControl(container_id or self._listcontainer)  # Note must get _lst in same func as addItem else crash
        except Exception as e:
            kodi_log(f'ListItemMonitorFunctions: Error getting window/control: {e}', 2)
            return None
            
        if not _lst:
            return None
            
        try:
            _lst.addItem(listitem)  # Note dont delay adding listitem after retrieving list else memory reference changes
            return listitem
        except Exception as e:
            kodi_log(f'ListItemMonitorFunctions: Error adding item to container: {e}', 2)
            return None

    def log_performance_stats(self):
        """Log performance statistics periodically"""
        current_time = time.time()
        if current_time - self._last_stats_log > 300:  # Every 5 minutes
            try:
                cache_stats = _smart_listitem_cache.get_stats()
                
                # Calculate average processing time
                if self._processing_times:
                    avg_time = sum(self._processing_times) / len(self._processing_times)
                    self._processing_times = self._processing_times[-50:]  # Keep last 50
                else:
                    avg_time = 0
                
                kodi_log(
                    f'ListItemMonitor Stats: Cache {cache_stats["hit_rate"]}, '
                    f'Avg processing {avg_time:.3f}s, '
                    f'Errors: {self._error_count}',
                    1
                )
                
                self._last_stats_log = current_time
                self._error_count = 0  # Reset error count
                
            except Exception as e:
                kodi_log(f'Error logging performance stats: {e}', 2)

    # =======
    # ACTIONS
    # =======

    def on_finalise(self):
        func = (
            ListItemMonitorFinaliserContainerMethod
            if self._listcontainer else
            ListItemMonitorFinaliserWindowMethod
        )
        func(self).finalise()

    @kodi_try_except('lib.monitor.listitem.on_listitem')
    def on_listitem(self):
        start_time = time.time()
        
        try:
            # Apply throttling delay if needed
            throttle_delay = _performance_throttler.get_throttle_delay()
            if throttle_delay > 0:
                time.sleep(throttle_delay)
            
            self.setup_current_container()
            self.setup_current_item()

            # We want to set a special container but it doesn't exist so exit
            if self._listcontainer == -1:
                return

            # Check if the item has changed before retrieving details again
            if self.is_same_item(update=True) and self.is_same_window(update=True):
                return

            # Ignore some special folders like next page and parent folder
            label = (self.get_infolabel('Label') or '').lower().split(' (', 1)[0]
            if label in self._ignored_labels:
                return self.on_exit()

            # Set a property for skins to check if item details are updating
            self.get_property('IsUpdating', 'True')

            # Finish up setting our details to the container/window
            self.on_finalise()

        except Exception as e:
            kodi_log(f'ListItemMonitorFunctions: Error in on_listitem: {e}', 2)
            self._error_count += 1
        finally:
            # Clear property for skins to check if item details are updating
            self.get_property('IsUpdating', clear_property=True)
            
            # Track processing time
            processing_time = time.time() - start_time
            self._processing_times.append(processing_time)
            
            # Log stats periodically
            self.log_performance_stats()

    @kodi_try_except('lib.monitor.listitem.on_context_listitem')
    def on_context_listitem(self):
        if not self._last_listitem:
            return
        try:
            _id_dialog = xbmcgui.getCurrentWindowDialogId()
            _id_d_list = self.get_listcontainer(_id_dialog, self._listcontainer_id)
            if not _id_d_list or _id_d_list == -1:
                return
            _id_window = xbmcgui.getCurrentWindowId()
            _id_w_list = self.get_listcontainer(_id_window, self._listcontainer_id)
            if not _id_w_list or _id_w_list == -1:
                return
            self.add_item_listcontainer(self._last_listitem, _id_dialog, _id_d_list)
        except Exception as e:
            kodi_log(f'ListItemMonitorFunctions: Error in context listitem: {e}', 2)

    def on_scroll(self):
        return

    def on_exit(self, is_done=True):
        try:
            if self._listcontainer:
                self.add_item_listcontainer(ListItem().get_listitem())

            self.clear_properties()

            if is_done:
                self.get_property('IsUpdating', clear_property=True)
        except Exception as e:
            kodi_log(f'ListItemMonitorFunctions: Error in on_exit: {e}', 2)

    def get_performance_stats(self):
        """Get comprehensive performance statistics"""
        try:
            return {
                'smart_cache': _smart_listitem_cache.get_stats(),
                'throttler_high_load': _performance_throttler.high_load_mode,
                'recent_requests': len(_performance_throttler.request_times),
                'processing_times_count': len(self._processing_times),
                'error_count': self._error_count
            }
        except Exception as e:
            kodi_log(f'Error getting performance stats: {e}', 2)
            return {}

    def clear_performance_caches(self):
        """Clear performance caches"""
        try:
            global _smart_listitem_cache, _performance_throttler
            _smart_listitem_cache = SmartListItemCache()
            _performance_throttler = PerformanceThrottler()
            self._processing_times.clear()
            self._error_count = 0
            kodi_log('ListItemMonitorFunctions: Performance caches cleared', 1)
        except Exception as e:
            kodi_log(f'Error clearing performance caches: {e}', 2)