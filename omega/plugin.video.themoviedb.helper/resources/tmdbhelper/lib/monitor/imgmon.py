#!/usr/bin/python
# -*- coding: utf-8 -*-
from tmdbhelper.lib.monitor.images import ImageManipulations, get_image_cache_stats
from tmdbhelper.lib.monitor.poller import Poller, POLL_MIN_INCREMENT
from tmdbhelper.lib.monitor.listitemtools import ListItemInfoGetter
from tmdbhelper.lib.addon.tmdate import set_timestamp, get_timestamp
from tmdbhelper.lib.addon.logger import kodi_try_except, kodi_log
from tmdbhelper.lib.addon.thread import SafeThread
from tmdbhelper.lib.files.locker import mutexlock
import hashlib
import time
from collections import OrderedDict


class SmartImageMonitor:
    """Smart monitoring with intelligent caching and throttling"""
    
    def __init__(self, max_cache_size=100):
        self.max_cache_size = max_cache_size
        self.item_cache = OrderedDict()  # LRU cache for processed items
        self.processing_history = {}  # Track what's been processed recently
        self.stats = {'cache_hits': 0, 'processing_requests': 0, 'skipped_duplicates': 0}
        
    def get_item_key(self, window_id, container_id, item_position, dbtype):
        """Generate unique key for current item state"""
        key_data = f"{window_id}:{container_id}:{item_position}:{dbtype}"
        return hashlib.md5(key_data.encode()).hexdigest()[:16]  # Shorter hash for performance
    
    def should_process_item(self, item_key, artwork_list):
        """Intelligent decision on whether to process this item"""
        current_time = time.time()
        
        # Check if we've processed this exact item recently (within 30 seconds)
        if item_key in self.processing_history:
            last_processed, last_artwork = self.processing_history[item_key]
            if current_time - last_processed < 30 and last_artwork == str(artwork_list):
                self.stats['skipped_duplicates'] += 1
                return False
        
        # Check if we have cached result
        if item_key in self.item_cache:
            self.item_cache.move_to_end(item_key)  # LRU update
            self.stats['cache_hits'] += 1
            return False
        
        self.stats['processing_requests'] += 1
        return True
    
    def mark_processed(self, item_key, artwork_list, result):
        """Mark item as processed and cache result"""
        current_time = time.time()
        
        # Update processing history
        self.processing_history[item_key] = (current_time, str(artwork_list))
        
        # Cache the result
        self.item_cache[item_key] = {
            'result': result,
            'timestamp': current_time,
            'artwork': artwork_list
        }
        
        # LRU eviction
        while len(self.item_cache) > self.max_cache_size:
            self.item_cache.popitem(last=False)
        
        # Clean old processing history (keep last 200 entries)
        if len(self.processing_history) > 200:
            # Keep only recent entries
            cutoff_time = current_time - 300  # 5 minutes
            self.processing_history = {
                k: v for k, v in self.processing_history.items() 
                if v[0] > cutoff_time
            }
    
    def get_stats(self):
        """Get monitoring statistics"""
        return {
            'cached_items': len(self.item_cache),
            'processing_history': len(self.processing_history),
            **self.stats
        }


class ImagesMonitor(SafeThread, ListItemInfoGetter, ImageManipulations, Poller):
    _cond_on_disabled = (
        "!Skin.HasSetting(TMDbHelper.EnableCrop) + "
        "!Skin.HasSetting(TMDbHelper.EnableBlur) + "
        "!Skin.HasSetting(TMDbHelper.EnableDesaturate) + "
        "!Skin.HasSetting(TMDbHelper.EnableColors)")

    _allow_list = ('crop', 'blur', 'desaturate', 'colors', )
    _check_list = (
        'Art(fanart)', 'Art(poster)', 'Art(clearlogo)',
        'Art(tvshow.fanart)', 'Art(tvshow.poster)', 'Art(tvshow.clearlogo)', 
        'Art(artist.fanart)', 'Art(artist.poster)', 'Art(artist.clearlogo)',
        'Art(thumb)', 'Art(icon)',
    )
    _dbtype_refresh = ('', None, 'addon', 'file', 'genre', 'country', 'studio', 'year', 'tag', 'director')
    _next_refresh_increment = 15  # Increased from 10 for better performance
    _this_refresh_increment = 5   # Increased from 3 for less frequent updates

    def __init__(self, parent):
        SafeThread.__init__(self)
        self._cur_item = 0
        self._pre_item = 1
        self._cur_window = 0
        self._pre_window = 1
        self._next_refresh = 0
        self._this_refresh = 0
        self.exit = False
        self.update_monitor = parent.update_monitor
        self.crop_image_cur = None
        self.blur_image_cur = None
        self.remote_artwork = {}
        self._allow_on_scroll = True
        self._parent = parent
        
        # Smart monitoring components
        self._smart_monitor = SmartImageMonitor()
        self._last_stats_log = 0
        self._processing_throttle = 0  # Throttle rapid processing requests
        self._rapid_scroll_detection = []  # Track rapid scrolling
        
        # Performance optimization flags
        self._skip_expensive_operations = False
        self._batch_mode = False

    def is_rapid_scrolling(self):
        """Detect if user is rapidly scrolling (reduce processing during rapid scroll)"""
        current_time = time.time()
        
        # Keep track of recent item changes
        self._rapid_scroll_detection.append(current_time)
        
        # Clean old entries (keep last 5 seconds)
        cutoff = current_time - 5
        self._rapid_scroll_detection = [t for t in self._rapid_scroll_detection if t > cutoff]
        
        # If more than 10 changes in 5 seconds, consider it rapid scrolling
        return len(self._rapid_scroll_detection) > 10

    def is_next_refresh(self):
        """Enhanced refresh logic with smart throttling"""
        self.setup_current_item()
        
        # Always refresh on window change
        if not self.is_same_window(update=True):
            self._rapid_scroll_detection.clear()  # Reset on window change
            return True

        # Check for item change
        if not self.is_same_item(update=True):
            # If rapid scrolling, be more conservative
            if self.is_rapid_scrolling():
                self._skip_expensive_operations = True
                # Only process every 3rd item during rapid scroll
                if len(self._rapid_scroll_detection) % 3 != 0:
                    return False
            else:
                self._skip_expensive_operations = False
            return True

        # Time-based refresh
        if not self._next_refresh:
            self._next_refresh = set_timestamp(self._next_refresh_increment)
            return False

        if not get_timestamp(self._next_refresh):
            return True

        return False

    def should_process_current_item(self):
        """Intelligent decision on whether to process current item"""
        try:
            # Get current item info
            dbtype = self.get_infolabel('ListItem.DBTYPE') or ''
            
            # Skip certain content types that don't benefit from image processing
            if dbtype in self._dbtype_refresh:
                return False
            
            # Get artwork list for comparison
            artwork_list = []
            for check_item in self._check_list:
                artwork = self.get_infolabel(check_item.replace('Art(', '').replace(')', ''))
                if artwork:
                    artwork_list.append(artwork)
            
            if not artwork_list:
                return False  # No artwork to process
            
            # Generate item key
            item_key = self._smart_monitor.get_item_key(
                self._cur_window, 
                self.get_current_container_id(),
                self._cur_item,
                dbtype
            )
            
            # Use smart monitoring to decide
            return self._smart_monitor.should_process_item(item_key, artwork_list)
            
        except Exception as e:
            kodi_log(f'ImagesMonitor: Error in should_process_current_item: {e}', 2)
            return False

    def get_current_container_id(self):
        """Get current container ID safely"""
        try:
            return self.get_infolabel('System.CurrentControlId') or '0'
        except Exception:
            return '0'

    @kodi_try_except('lib.monitor.imgmon.on_listitem')
    def on_listitem(self):
        """Optimized listitem processing with smart throttling"""
        # Throttle rapid requests
        current_time = time.time()
        if current_time - self._processing_throttle < 0.1:  # Max 10 requests per second
            return
        
        self._processing_throttle = current_time
        
        # Use smart monitoring to decide if processing is needed
        if not self.should_process_current_item():
            return
        
        # Process with parent mutex lock
        with self._parent.mutex_lock:
            self.update_artwork()

    def update_artwork(self, forced=False):
        """Enhanced artwork update with smart optimizations"""
        self.setup_current_container()
        
        if not forced and not self.is_next_refresh():
            return
        
        # Reset refresh timers
        self._this_refresh = 0
        self._next_refresh = 0
        
        try:
            # Get processing options based on performance state
            processing_options = {
                'use_winprops': True,
                'built_artwork': self.remote_artwork.get(self._pre_item),
                'allow_list': self._allow_list
            }
            
            # Reduce processing during rapid scrolling or low performance
            if self._skip_expensive_operations:
                # Only do essential operations
                processing_options['allow_list'] = ('crop',)  # Only crop, skip blur/colors
            
            # Process images
            result = self.get_image_manipulations(**processing_options)
            
            # Cache the result
            if hasattr(self, '_smart_monitor'):
                dbtype = self.get_infolabel('ListItem.DBTYPE') or ''
                artwork_list = []
                for check_item in self._check_list:
                    artwork = self.get_infolabel(check_item.replace('Art(', '').replace(')', ''))
                    if artwork:
                        artwork_list.append(artwork)
                
                item_key = self._smart_monitor.get_item_key(
                    self._cur_window,
                    self.get_current_container_id(), 
                    self._cur_item,
                    dbtype
                )
                
                self._smart_monitor.mark_processed(item_key, artwork_list, result)
            
            # Log performance stats periodically
            if current_time := time.time():
                if current_time - self._last_stats_log > 300:  # Every 5 minutes
                    self._log_performance_stats()
                    self._last_stats_log = current_time
            
            return result
            
        except Exception as e:
            kodi_log(f'ImagesMonitor: Error in update_artwork: {e}', 2)
            return {}

    def _log_performance_stats(self):
        """Log performance statistics"""
        try:
            monitor_stats = self._smart_monitor.get_stats()
            image_stats = get_image_cache_stats()
            
            kodi_log(
                f'ImagesMonitor Stats: {monitor_stats["processing_requests"]} requests, '
                f'{monitor_stats["cache_hits"]} cache hits, '
                f'{monitor_stats["skipped_duplicates"]} duplicates skipped',
                1
            )
            
            # Log image cache stats
            smart_cache = image_stats.get('smart_cache', {})
            if smart_cache:
                kodi_log(
                    f'Image Cache: {smart_cache.get("entries", 0)} entries, '
                    f'{smart_cache.get("memory_mb", 0)}MB, '
                    f'{smart_cache.get("hit_rate", "0%")} hit rate',
                    1
                )
                
        except Exception as e:
            kodi_log(f'Error logging performance stats: {e}', 2)

    def _on_listitem(self):
        """Handle listitem events with scroll awareness"""
        if self._allow_on_scroll:
            return self.on_listitem()
        self._on_idle(POLL_MIN_INCREMENT)

    def _on_scroll(self):
        """Handle scroll events with smart processing"""
        if self._allow_on_scroll:
            # During rapid scroll, reduce frequency
            if self.is_rapid_scrolling():
                # Process less frequently during rapid scroll
                self._on_idle(POLL_MIN_INCREMENT * 2)
            else:
                return self.on_listitem()
        else:
            self._on_idle(POLL_MIN_INCREMENT)

    def _on_idle(self, poll_time):
        """Enhanced idle handling"""
        # Use idle time for cache maintenance
        try:
            # Clean up smart monitor caches occasionally
            if hasattr(self, '_smart_monitor'):
                current_time = time.time()
                if not hasattr(self, '_last_cleanup') or current_time - self._last_cleanup > 600:
                    # Clean every 10 minutes
                    if len(self._smart_monitor.processing_history) > 150:
                        # Trim processing history
                        cutoff_time = current_time - 300
                        self._smart_monitor.processing_history = {
                            k: v for k, v in self._smart_monitor.processing_history.items()
                            if v[0] > cutoff_time
                        }
                    self._last_cleanup = current_time
        except Exception as e:
            kodi_log(f'Error in idle cleanup: {e}', 2)
        
        # Call parent idle with specified time
        super()._on_idle(poll_time) if hasattr(super(), '_on_idle') else None

    def run(self):
        """Main monitoring loop with enhanced error handling"""
        try:
            kodi_log('ImagesMonitor: Starting optimized image monitoring', 1)
            self.poller()
        except Exception as e:
            kodi_log(f'ImagesMonitor: Error in main loop: {e}', 2)
        finally:
            kodi_log('ImagesMonitor: Stopped', 1)

    def stop(self):
        """Clean shutdown with stats logging"""
        try:
            if hasattr(self, '_smart_monitor'):
                final_stats = self._smart_monitor.get_stats()
                kodi_log(f'ImagesMonitor: Final stats - {final_stats}', 1)
        except Exception:
            pass
        
        self.exit = True

    def get_monitor_stats(self):
        """Get comprehensive monitoring statistics"""
        try:
            stats = {
                'smart_monitor': self._smart_monitor.get_stats() if hasattr(self, '_smart_monitor') else {},
                'image_cache': get_image_cache_stats(),
                'rapid_scroll_events': len(self._rapid_scroll_detection),
                'skip_expensive_ops': self._skip_expensive_operations
            }
            return stats
        except Exception as e:
            kodi_log(f'Error getting monitor stats: {e}', 2)
            return {}