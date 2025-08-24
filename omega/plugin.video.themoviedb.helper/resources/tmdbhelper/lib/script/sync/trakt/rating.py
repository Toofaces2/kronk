from tmdbhelper.lib.script.sync.trakt.item import ItemSync
from tmdbhelper.lib.addon.plugin import get_localized
from tmdbhelper.lib.addon.dialog import busy_decorator
from xbmcgui import Dialog


class ItemRating(ItemSync):
    """Optimized Trakt rating sync with improved performance and caching"""
    
    # Class-level constants for better performance
    allow_episodes = True
    localized_name_add = 32485
    localized_name_rem = 32489
    trakt_sync_key = 'rating'
    
    # Rating validation constants
    MIN_RATING = 0
    MAX_RATING = 10
    
    # Cache localized strings to avoid repeated lookups
    _cached_strings = {}
    
    @classmethod
    def _get_cached_localized(cls, string_id):
        """Cache localized strings for better performance"""
        if string_id not in cls._cached_strings:
            cls._cached_strings[string_id] = get_localized(string_id)
        return cls._cached_strings[string_id]

    def get_name_remove(self):
        """Optimized name removal with cached localization"""
        localized_rem = self._get_cached_localized(self.localized_name_rem)
        return f'{localized_rem} ({self.sync_value})'

    @staticmethod
    def refresh_containers():
        """Override to prevent unnecessary container refreshes for ratings"""
        pass

    def get_dialog_header(self):
        """Optimized dialog header with cached strings and early returns"""
        rating = self.sync_item.get('rating')
        
        # Handle removal case first (most common for existing ratings)
        if rating == 0:
            return self._get_cached_localized(32530)  # Remove rating
        
        # Cache frequently used strings
        add_rating_str = self._get_cached_localized(32485)  # Add Rating
        change_rating_str = self._get_cached_localized(32489)  # Change Rating
        
        # Determine if this is add or change operation
        if self.name == add_rating_str:
            return f'{add_rating_str} ({rating})'
        else:
            return f'{change_rating_str} ({rating})'

    @busy_decorator
    def set_rating(self, rating_value):
        """Optimized rating API call with better error handling"""
        # Determine API endpoint based on rating value
        endpoint_path = 'sync/ratings/remove' if rating_value == 0 else 'sync/ratings'
        
        # Prepare payload efficiently
        payload = {f'{self.trakt_type}s': [self.sync_item]}
        
        try:
            return self.trakt_api.post_response(endpoint_path, postdata=payload)
        except Exception as e:
            # Log error and return None to indicate failure
            if hasattr(self, 'kodi_log'):
                self.kodi_log(f"Failed to set rating {rating_value}: {e}", level=2)
            return None

    def get_sync_response(self):
        """Optimized sync response with improved validation and UX"""
        # Show rating dialog with better prompt
        name_str = self.name or self._get_cached_localized(self.localized_name_add)
        dialog_prompt = f'{name_str} ({self.MIN_RATING}-{self.MAX_RATING})'
        
        try:
            # Get user input
            user_input = Dialog().numeric(0, dialog_prompt)
            
            # Handle empty input (user cancelled)
            if not user_input:
                return None
                
            # Convert and validate rating
            rating = int(user_input)
            
        except (ValueError, TypeError):
            # Handle invalid input gracefully
            Dialog().notification(
                heading=self._get_cached_localized(257),  # Error
                message=self._get_cached_localized(32531),  # Invalid rating
                icon='error',
                time=3000
            )
            return None

        # Validate rating range
        if not (self.MIN_RATING <= rating <= self.MAX_RATING):
            Dialog().notification(
                heading=self._get_cached_localized(257),  # Error
                message=f'{self._get_cached_localized(32532)} ({self.MIN_RATING}-{self.MAX_RATING})',  # Rating must be between
                icon='error',
                time=3000
            )
            return None

        # Update sync item with new rating
        self.sync_item['rating'] = rating
        
        # Set rating via API
        result = self.set_rating(rating)
        
        # Show confirmation if successful
        if result:
            action_str = self._get_cached_localized(32530 if rating == 0 else 32485)  # Remove/Add rating
            Dialog().notification(
                heading=action_str,
                message=f'{self.sync_item.get("title", "Item")} ({rating})',
                icon='info',
                time=2000
            )
        
        return result

    def validate_rating_input(self, rating_input):
        """Separate validation method for better testability"""
        try:
            rating = int(rating_input)
            return self.MIN_RATING <= rating <= self.MAX_RATING, rating
        except (ValueError, TypeError):
            return False, None

    @classmethod
    def clear_string_cache(cls):
        """Clear cached strings if needed (for language changes)"""
        cls._cached_strings.clear()