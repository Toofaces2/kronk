from tmdbhelper.lib.script.sync.tmdb.item import ItemSync
from jurialmunkey.ftools import cached_property
from tmdbhelper.lib.addon.dialog import busy_decorator
from tmdbhelper.lib.addon.plugin import get_localized


class ItemRating(ItemSync):
    """Optimized TMDb rating sync with improved caching and performance"""
    
    # Class constants for better performance
    localized_name_add = 32485
    localized_name_rem = 32530
    tmdb_list_type = 'rating'
    convert_episodes = False
    convert_seasons = False
    allow_seasons = True
    allow_episodes = True
    
    # Rating constants
    MIN_RATING = 0
    MAX_RATING = 100
    RATING_STEP = 5
    TMDB_RATING_SCALE = 10.0  # TMDb uses 0-10 scale
    
    # Cache localized strings at class level to avoid repeated lookups
    _cached_localized_strings = {}

    @classmethod
    def _get_cached_localized(cls, string_id):
        """Cache localized strings for better performance across instances"""
        if string_id not in cls._cached_localized_strings:
            cls._cached_localized_strings[string_id] = get_localized(string_id)
        return cls._cached_localized_strings[string_id]

    @cached_property
    def input_rating_options(self):
        """Optimized rating options generation"""
        # Generate rating options: [0, 100, 95, 90, ..., 5]
        return [self.MIN_RATING] + list(reversed(range(self.RATING_STEP, self.MAX_RATING + self.RATING_STEP, self.RATING_STEP)))

    @cached_property
    def input_rating_choices(self):
        """Optimized rating choice strings with cached localization"""
        remove_rating_str = self._get_cached_localized(38022)
        rating_str = self._get_cached_localized(563)
        
        return [
            remove_rating_str if rating == self.MIN_RATING else f'{rating_str}: {rating}%'
            for rating in self.input_rating_options
        ]

    @cached_property
    def input_rating(self):
        """Optimized rating input with better UX and validation"""
        from xbmcgui import Dialog
        
        dialog_result = Dialog().select(
            self.item_name, 
            self.input_rating_choices, 
            preselect=self.preselect
        )
        
        # Handle user cancellation
        if dialog_result == -1:
            return None
            
        # Get selected rating value
        selected_rating = self.input_rating_options[dialog_result]
        
        # Convert to TMDb scale (0-10) with 0.5 increments
        if selected_rating == self.MIN_RATING:
            return self.MIN_RATING  # 0 for removal
        
        # Convert percentage to TMDb scale and round to nearest 0.5
        tmdb_rating = (selected_rating / self.TMDB_RATING_SCALE)
        return round(tmdb_rating * 2) / 2

    @cached_property
    def preselect(self):
        """Optimized preselection with better error handling"""
        try:
            # Convert current sync_value back to percentage for selection
            current_percentage = int(self.sync_value) if self.sync_value else self.MIN_RATING
            return self.input_rating_options.index(current_percentage)
        except (ValueError, TypeError, AttributeError):
            return 0  # Default to "Remove Rating"

    @cached_property
    def post_response_args(self):
        """Optimized API endpoint argument construction"""
        args = [self.tmdb_type, self.tmdb_id]
        
        # Add season/episode path components if applicable
        if self.episode is not None and self.season is not None:
            args.extend(['season', self.season, 'episode', self.episode])
            
        args.append(self.tmdb_list_type)
        return args

    def get_post_response_data(self):
        """Optimized post data generation"""
        if self.input_rating is None or self.input_rating == self.MIN_RATING:
            return None  # No data needed for deletion
        return {"value": f'{self.input_rating}'}

    @cached_property
    def post_response_data(self):
        """Cached post response data"""
        return self.get_post_response_data()

    @cached_property
    def post_response_method(self):
        """Optimized HTTP method determination"""
        return 'json_delete' if (self.input_rating is None or self.input_rating == self.MIN_RATING) else 'json'

    @busy_decorator
    def get_sync_response(self):
        """Optimized sync response with better error handling and user feedback"""
        # Validate input rating
        if self.input_rating is None:
            return None  # User cancelled
        
        try:
            # Make API request
            sync_response = self.tmdb_user_api.get_authorised_response_json_v3(
                *self.post_response_args,
                postdata=self.post_response_data,
                method=self.post_response_method,
            )
            
            # Force ratings database update for immediate feedback
            self._force_ratings_update()
            
            # Update display name
            self.name = self.get_updated_name()
            
            # Show success notification
            self._show_success_notification()
            
            return sync_response
            
        except Exception as e:
            # Log error and show user-friendly message
            if hasattr(self, 'kodi_log'):
                self.kodi_log(f"Failed to sync rating: {e}", level=2)
            
            self._show_error_notification()
            return None

    def _force_ratings_update(self):
        """Force ratings database update with error handling"""
        try:
            self.query_database.get_user_ratings(
                self.tmdb_type,
                self.tmdb_id,
                self.season,
                self.episode,
                forced=True
            )
        except Exception as e:
            if hasattr(self, 'kodi_log'):
                self.kodi_log(f"Failed to update ratings cache: {e}", level=1)

    def _show_success_notification(self):
        """Show success notification to user"""
        try:
            from xbmcgui import Dialog
            
            if self.input_rating == self.MIN_RATING:
                title = self._get_cached_localized(32530)  # "Rating Removed"
                message = self.item_name
            else:
                title = self._get_cached_localized(32485)  # "Rating Added"
                message = f'{self.item_name} ({int(self.input_rating * 10)}%)'
            
            Dialog().notification(
                heading=title,
                message=message,
                icon='info',
                time=2000
            )
        except Exception:
            pass  # Fail silently for notifications

    def _show_error_notification(self):
        """Show error notification to user"""
        try:
            from xbmcgui import Dialog
            Dialog().notification(
                heading=self._get_cached_localized(257),  # "Error"
                message=self._get_cached_localized(32533),  # "Failed to update rating"
                icon='error',
                time=3000
            )
        except Exception:
            pass  # Fail silently for notifications

    def get_sync_value(self):
        """Optimized sync value retrieval with caching"""
        try:
            rating = self.query_database.get_user_ratings(
                self.tmdb_type,
                self.tmdb_id,
                self.season,
                self.episode
            )
            return rating
        except Exception as e:
            if hasattr(self, 'kodi_log'):
                self.kodi_log(f"Failed to get sync value: {e}", level=1)
            return None

    def get_updated_name(self):
        """Optimized name generation with cached strings"""
        if not self.input_rating or self.input_rating == self.MIN_RATING:
            return self._get_cached_localized(32530)  # "Delete Rating"
        
        percentage = int(self.input_rating * 10)
        
        if not self.sync_value:
            # Adding new rating
            add_rating_str = self._get_cached_localized(32485)
            return f'{add_rating_str}: {percentage}%'
        else:
            # Changing existing rating
            change_rating_str = self._get_cached_localized(32489)
            return f'{change_rating_str}: {percentage}%'

    def get_name(self):
        """Optimized name generation for display"""
        if not self.sync_value:
            return self._get_cached_localized(32485)  # "Add Rating"
        
        change_rating_str = self._get_cached_localized(32489)
        return f'{change_rating_str}: {self.sync_value}%'

    @classmethod
    def clear_localized_cache(cls):
        """Clear cached localized strings (useful for language changes)"""
        cls._cached_localized_strings.clear()

    def validate_rating_range(self, rating):
        """Validate rating is within acceptable range"""
        if rating is None:
            return True  # None is valid for removal
        return self.MIN_RATING <= rating <= (self.MAX_RATING / self.TMDB_RATING_SCALE)

    def convert_percentage_to_tmdb_scale(self, percentage):
        """Convert percentage rating to TMDb scale (0-10)"""
        if percentage == 0:
            return 0
        return round((percentage / self.TMDB_RATING_SCALE) * 2) / 2

    def convert_tmdb_scale_to_percentage(self, tmdb_rating):
        """Convert TMDb scale rating (0-10) to percentage"""
        if tmdb_rating == 0:
            return 0
        return int(tmdb_rating * 10)