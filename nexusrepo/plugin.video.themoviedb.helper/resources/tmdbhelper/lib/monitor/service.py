from tmdbhelper.lib.addon.plugin import get_setting
from jurialmunkey.window import get_property, wait_for_property
from tmdbhelper.lib.monitor.listitemtools import ListItemMonitorFunctions
from tmdbhelper.lib.monitor.cronjob import CronJobMonitor
from tmdbhelper.lib.monitor.player import PlayerMonitor
from tmdbhelper.lib.monitor.update import UpdateMonitor
from tmdbhelper.lib.monitor.imgmon import ImagesMonitor
from tmdbhelper.lib.monitor.poller import Poller, POLL_MIN_INCREMENT, POLL_MID_INCREMENT
from tmdbhelper.lib.addon.thread import SafeThread
from threading import Lock, Event
import time


class ServiceMonitor(Poller):
    """Optimized ServiceMonitor with enhanced performance and resource management"""
    
    def __init__(self):
        super().__init__()  # Initialize Poller optimization attributes
        
        # Core state
        self.exit = False
        self.listitem = None
        
        # Performance optimization flags
        self._service_started = False
        self._monitors_initialized = False
        
        # Thread management
        self._monitor_threads = {}
        self._shutdown_event = Event()
        
        # Performance tracking
        self._last_listitem_update = 0
        self._last_scroll_update = 0
        self._listitem_throttle = 0.1  # Minimum time between listitem updates
        self._scroll_throttle = 0.05   # Minimum time between scroll updates
        
        # Resource management
        self._cleanup_performed = False

    def run(self):
        """Enhanced run method with better resource management and error handling"""
        try:
            self._initialize_service()
            self._start_monitoring_threads()
            self._mark_service_started()
            
            # Main polling loop with enhanced error handling
            self.poller()
            
        except Exception as e:
            self._log_error(f"Service monitor crashed: {e}")
        finally:
            self._cleanup_service()

    def _initialize_service(self):
        """Initialize core service components"""
        self.mutex_lock = Lock()
        
        # Initialize monitors with error handling
        try:
            self.update_monitor = UpdateMonitor()
            self.player_monitor = PlayerMonitor()
            self.listitem_funcs = ListItemMonitorFunctions(self)
            self._monitors_initialized = True
        except Exception as e:
            self._log_error(f"Failed to initialize monitors: {e}")
            raise

    def _start_monitoring_threads(self):
        """Start background monitoring threads with enhanced error handling"""
        try:
            # Start cron job monitor
            self.cron_job = CronJobMonitor(
                self, 
                update_hour=get_setting('library_autoupdate_hour', 'int')
            )
            self.cron_job.setName('TMDbHelper-CronJob')
            self.cron_job.daemon = True  # Ensure clean shutdown
            self.cron_job.start()
            self._monitor_threads['cron'] = self.cron_job

            # Start images monitor
            self.images_monitor = ImagesMonitor(self)
            self.images_monitor.setName('TMDbHelper-ImageMonitor')
            self.images_monitor.daemon = True  # Ensure clean shutdown
            self.images_monitor.start()
            self._monitor_threads['images'] = self.images_monitor
            
        except Exception as e:
            self._log_error(f"Failed to start monitoring threads: {e}")
            raise

    def _mark_service_started(self):
        """Mark service as started with property setting"""
        get_property('ServiceStarted', 'True')
        self._service_started = True
        self._log_info("TMDbHelper service started successfully")

    def _on_listitem(self):
        """Optimized listitem handling with throttling to prevent excessive updates"""
        current_time = time.time()
        
        # Throttle listitem updates to prevent excessive processing
        if current_time - self._last_listitem_update < self._listitem_throttle:
            self._on_idle(POLL_MIN_INCREMENT)
            return
        
        try:
            # Update listitem data
            self.listitem_funcs.on_listitem()
            self._last_listitem_update = current_time
            
        except Exception as e:
            self._log_error(f"Error in listitem processing: {e}")
        finally:
            self._on_idle(POLL_MIN_INCREMENT)

    def _on_scroll(self):
        """Optimized scroll handling with throttling"""
        current_time = time.time()
        
        # Throttle scroll updates for better performance
        if current_time - self._last_scroll_update < self._scroll_throttle:
            self._on_idle(POLL_MIN_INCREMENT)
            return
        
        try:
            self.listitem_funcs.on_scroll()
            self._last_scroll_update = current_time
            
        except Exception as e:
            self._log_error(f"Error in scroll processing: {e}")
        finally:
            self._on_idle(POLL_MIN_INCREMENT)

    def _on_player(self):
        """Optimized player monitoring with error handling"""
        try:
            if self.player_monitor and self.player_monitor.isPlayingVideo():
                self.player_monitor.update_time()
                self.player_monitor.update_artwork()
        except Exception as e:
            self._log_error(f"Error in player monitoring: {e}")

    def _on_context(self):
        """Optimized context menu handling"""
        try:
            self.listitem_funcs.on_context_listitem()
        except Exception as e:
            self._log_error(f"Error in context processing: {e}")
        finally:
            self._on_idle(POLL_MID_INCREMENT)

    def _on_clear(self):
        """
        Optimized property clearing with batched operations
        If we've got properties to clear lets clear them and then jump back in the loop
        Otherwise we should sit for a moment so we aren't constantly polling
        """
        try:
            # Batch property clearing for better performance
            properties_cleared = self.listitem_funcs.clear_properties()
            
            # If no properties were cleared, wait a bit longer to reduce CPU usage
            wait_time = POLL_MIN_INCREMENT if properties_cleared else POLL_MID_INCREMENT
            self._on_idle(wait_time)
            
        except Exception as e:
            self._log_error(f"Error clearing properties: {e}")
            self._on_idle(POLL_MID_INCREMENT)

    def _on_exit(self):
        """Enhanced cleanup with proper thread management"""
        if self._cleanup_performed:
            return
        
        try:
            self._log_info("TMDbHelper service shutting down...")
            
            # Signal shutdown to all threads
            self._shutdown_event.set()
            
            # Stop monitoring threads gracefully
            self._stop_monitoring_threads()
            
            # Clean up properties
            self._cleanup_properties()
            
            # Perform final cleanup
            self._cleanup_performed = True
            
        except Exception as e:
            self._log_error(f"Error during service cleanup: {e}")

    def _stop_monitoring_threads(self):
        """Stop all monitoring threads gracefully"""
        # Stop threads with timeout
        for thread_name, thread in self._monitor_threads.items():
            try:
                if thread and thread.is_alive():
                    thread.exit = True
                    
                    # Wait for thread to finish with timeout
                    thread.join(timeout=2.0)
                    
                    if thread.is_alive():
                        self._log_error(f"{thread_name} thread did not shut down cleanly")
                    else:
                        self._log_info(f"{thread_name} thread stopped successfully")
                        
            except Exception as e:
                self._log_error(f"Error stopping {thread_name} thread: {e}")

    def _cleanup_properties(self):
        """Clean up window properties"""
        try:
            if self._service_started:
                if not self.update_monitor.abortRequested():
                    get_property('ServiceStarted', clear_property=True)
                    get_property('ServiceStop', clear_property=True)
        except Exception as e:
            self._log_error(f"Error cleaning up properties: {e}")

    def _log_info(self, message):
        """Log info message if logging is available"""
        try:
            if hasattr(self, 'kodi_log'):
                self.kodi_log(message, level=0)
        except:
            pass

    def _log_error(self, message):
        """Log error message if logging is available"""
        try:
            if hasattr(self, 'kodi_log'):
                self.kodi_log(message, level=2)
        except:
            pass

    def get_service_status(self):
        """Get current service status for debugging"""
        return {
            'service_started': self._service_started,
            'monitors_initialized': self._monitors_initialized,
            'active_threads': [name for name, thread in self._monitor_threads.items() 
                             if thread and thread.is_alive()],
            'last_listitem_update': self._last_listitem_update,
            'last_scroll_update': self._last_scroll_update,
            'performance_stats': self.get_performance_stats()
        }

    def emergency_stop(self):
        """Emergency stop for the service"""
        self._log_error("Emergency stop requested!")
        self.exit = True
        self._shutdown_event.set()
        self._on_exit()


def restart_service_monitor():
    """Optimized service restart with better synchronization and error handling"""
    try:
        # Check if service is currently running
        if get_property('ServiceStarted') == 'True':
            # Request service stop
            wait_for_property('ServiceStop', value='True', set_property=True, timeout=10)
            
        # Wait until service clears property (with timeout)
        wait_for_property('ServiceStop', value=None, timeout=15)
        
        # Small delay to ensure clean shutdown
        time.sleep(0.5)
        
        # Start new service instance
        service_thread = SafeThread(target=ServiceMonitor().run)
        service_thread.daemon = True  # Ensure clean shutdown
        service_thread.setName('TMDbHelper-ServiceMonitor')
        service_thread.start()
        
        return service_thread
        
    except Exception as e:
        # Log error if possible
        try:
            from tmdbhelper.lib.addon.logger import kodi_log
            kodi_log(f"Failed to restart service monitor: {e}", level=2)
        except:
            pass
        raise


class ServiceHealthMonitor:
    """Additional health monitoring for the service"""
    
    @staticmethod
    def check_service_health():
        """Check if the service is running properly"""
        try:
            service_started = get_property('ServiceStarted') == 'True'
            service_stop_requested = get_property('ServiceStop') == 'True'
            
            return {
                'running': service_started and not service_stop_requested,
                'service_started': service_started,
                'stop_requested': service_stop_requested,
                'timestamp': time.time()
            }
        except Exception as e:
            return {
                'running': False,
                'error': str(e),
                'timestamp': time.time()
            }
    
    @staticmethod
    def restart_if_unhealthy():
        """Restart service if it's not healthy"""
        health = ServiceHealthMonitor.check_service_health()
        if not health.get('running', False):
            try:
                restart_service_monitor()
                return True
            except Exception:
                return False
        return False