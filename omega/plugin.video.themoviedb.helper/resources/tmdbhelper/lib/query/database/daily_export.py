#!/usr/bin/python
# -*- coding: utf-8 -*-
from xbmc import executebuiltin
from tmdbhelper.lib.addon.logger import kodi_log

class TableDailyExport:
    conditions = None

    def __init__(self, parent):
        self.parent = parent

    def get_cached_or_trigger_update(self):
        """
        The main optimized function. It checks for expiry, triggers a background update if needed,
        and always returns the currently available data immediately.
        """
        # Check if the cache for this table is expired.
        if self.parent.is_expired(self.table):
            self.trigger_background_update()
            
        # Always return the data currently in the database, even if it's stale.
        # The UI will be instant, and the data will be updated silently in the background.
        return self.parent.get_cached_values(
            self.table,
            self.keys,
            conditions=self.conditions
        )

    def trigger_background_update(self):
        """
        Signals the background service to start the download and import process.
        This is a non-blocking "fire and forget" call.
        """
        kodi_log(f'CACHE: Stale cache for table "{self.table}". Triggering background update.')
        # Use a built-in Kodi command to call our own addon's service with specific parameters.
        # This tells service.py to run the 'update_daily_export' action for the specified list.
        command = f'RunPlugin(plugin://plugin.video.themoviedb.helper/?info=service_bridge&action=update_daily_export&export_list={self.export_list})'
        executebuiltin(command)