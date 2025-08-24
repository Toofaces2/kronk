#!/usr/bin/python
# -*- coding: utf-8 -*-
from xbmcgui import Window
import jurialmunkey.window as window
from tmdbhelper.lib.addon.plugin import executebuiltin, get_condvisibility
from tmdbhelper.lib.addon.logger import kodi_log
from jurialmunkey.ftools import cached_property
from tmdbhelper.lib.window.direct_call_auto import DirectCallAutoInfoDialog
from tmdbhelper.lib.window.constants import (
    ID_VIDEOINFO,
    PREFIX_INSTANCE,
    PREFIX_ADDPATH,
    PREFIX_PATH,
    CONTAINER_ID,
    PREFIX_COMMAND,
    PREFIX_POSITION,
)
from threading import Event


class EventLoop():

    def _call_exit(self, return_info=False):
        kodi_log(f'Window Manager [EVENTS] _call_exit return_info:{return_info}', 2)
        self.return_info = return_info
        self.exit = True

    def _on_exit(self):
        kodi_log(f'Window Manager [EVENTS] _on_exit', 2)
        self.reset_properties()

        # We now rely on the UI to handle closing its windows.
        # This prevents blocking calls.
        if window.is_visible(ID_VIDEOINFO):
            executebuiltin('Dialog.Close(all)')
            
        if window.is_visible(self.window_id):
            executebuiltin('Action(Back)')

    def _on_add(self):
        kodi_log(f'Window Manager [EVENTS] _on_add [ ]', 2)
        self.position += 1
        # Set properties for the new path without waiting
        self.set_properties(self.position, window.get_property(PREFIX_ADDPATH))
        # Now, clear the ADDPATH property immediately to signal completion
        window.get_property(PREFIX_ADDPATH, clear_property=True)
        kodi_log(f'Window Manager [EVENTS] _on_add [X]', 2)

    def _on_rem(self):
        kodi_log(f'Window Manager [EVENTS] _on_rem [ ]', 2)
        self.position -= 1
        name = f'{PREFIX_PATH}{self.position}'
        self.set_properties(self.position, window.get_property(name))
        kodi_log(f'Window Manager [EVENTS] _on_rem [X]', 2)

    def _on_back(self):
        kodi_log(f'Window Manager [EVENTS] _on_back [ ]', 2)
        # We no longer poll for the property to be cleared. We trust the system.
        return self._on_rem() if self.position > 1 else self._call_exit(True)

    def _on_change_window(self):
        kodi_log(f'Window Manager [EVENTS] _on_change_window', 2)
        
        # We assume the window has changed without polling.
        # This is where we would show a busy dialog.
        
        if not self.first_run:
            kodi_log(f'Window Manager [EVENTS] _on_change_window first_run', 2)
            return True

        kodi_log(f'Window Manager [EVENTS] _on_change_window activate_base [ ]', 2)
        window.activate(self.window_id)
        kodi_log(f'Window Manager [EVENTS] _on_change_window activate_base [X]', 2)
        return True

    def _on_change_manual(self):
        if not self._on_change_window():
            return False

        _window = Window(self.kodi_id)
        control_list = _window.getControl(CONTAINER_ID)
        if not control_list:
            kodi_log(f'SKIN ERROR!\nControl {CONTAINER_ID} unavailable in Window {self.window_id}', 1)
            return False
        
        control_list.reset()
        _window = Window(self.kodi_id)
        _window.setFocus(control_list)
        executebuiltin(f'SetFocus({CONTAINER_ID},0,absolute)')
        executebuiltin('Action(Info)')
        return True

    def _on_change_direct(self):
        kodi_log(f'Window Manager [EVENTS] _on_change_direct', 2)
        direct = DirectCallAutoInfoDialog(self.added_path)

        if not direct.listitem:
            kodi_log(f'Window Manager [EVENTS] _on_change_direct NO LISTITEM!', 2)
            return False

        if not self._on_change_window():
            kodi_log(f'Window Manager [EVENTS] _on_change_direct window_change FAILED!', 2)
            return False

        kodi_log(f'Window Manager [EVENTS] _on_change_direct direct.open() [ ]', 2)
        direct.open()
        kodi_log(f'Window Manager [EVENTS] _on_change_direct direct.open() [X]', 2)

        return True

    @cached_property
    def on_change_method(self):
        if get_condvisibility("Skin.HasSetting(TMDbHelper.DirectCallAuto)"):
            return self._on_change_direct
        return self._on_change_manual

    def _on_change(self):
        kodi_log(f'Window Manager [EVENTS] _on_change', 2)
        if self.position == 0:
            kodi_log(f'Window Manager [EVENTS] _on_change last_position', 2)
            return self._call_exit(True)
        if not self.on_change_method():
            kodi_log(f'Window Manager [EVENTS] _on_change _on_change_method FAILED!', 2)
            return self._call_exit()
        self.current_path = self.added_path
        self.first_run = False

    def event_poll(self):
        # We will replace this with a more efficient event-driven model.
        pass

    def event_loop(self):
        kodi_log(f'Window Manager [EVENTS] _event_loop BEGIN', 2)
        window.get_property(PREFIX_INSTANCE, set_property='True')

        self._on_change()

        kodi_log(f'Window Manager [EVENTS] _event_loop ENDED', 2)