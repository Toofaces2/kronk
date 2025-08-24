from tmdbhelper.lib.addon.plugin import get_language, get_setting
from tmdbhelper.lib.api.request import NoCacheRequestAPI
from tmdbhelper.lib.api.tmdb.mapping import ItemMapper
from tmdbhelper.lib.api.api_keys.tmdb import API_KEY
from jurialmunkey.ftools import cached_property

# Constants for better performance
API_URLS = {
    'STANDARD': 'https://api.themoviedb.org/3',
    'ALTERNATE': 'https://api.tmdb.org/3'
}

# Pre-compiled URL separators for better performance
URL_SEPARATORS = {
    'AND': '%2C',
    'OR': '%7C',
    'DEFAULT': '%2C'
}

# Cache API URL determination to avoid repeated setting lookups
_cached_api_url = None
_api_url_checked = False

def get_api_url():
    """Cached API URL determination"""
    global _cached_api_url, _api_url_checked
    if not _api_url_checked:
        _cached_api_url = API_URLS['ALTERNATE'] if get_setting('use_alternate_api_url') else API_URLS['STANDARD']
        _api_url_checked = True
    return _cached_api_url


class TMDbAPI(NoCacheRequestAPI):
    """Optimized TMDb API with improved caching and performance"""

    api_key = API_KEY
    api_url = get_api_url()
    append_to_response = ''
    append_to_response_person = ''
    api_name = 'TMDbAPI'

    def __init__(self, api_key=None, language=get_language()):
        api_key = api_key or self.api_key
        api_url = self.api_url
        api_name = self.api_name

        super(TMDbAPI, self).__init__(
            req_api_name=api_name,
            req_api_url=api_url,
            req_api_key=f'api_key={api_key}'
        )
        
        self.language = language
        TMDb.api_key = api_key
        
        # Cache frequently computed values
        self._cached_iso_language = None
        self._cached_iso_country = None
        self._cached_req_language = None
        self._cached_mapper = None

    @property
    def req_strip(self):
        """Optimized request strip with cached computation"""
        if not hasattr(self, '_cached_req_strip_add'):
            self._cached_req_strip_add = [
                (self.append_to_response, 'standard'),
                (self.append_to_response_person, 'person'),
                (self.append_to_response_tvshow, 'tvshow'),
                (self.append_to_response_tvshow_simple, 'tvshow_simple'),
                (self.append_to_response_movies_simple, 'movies_simple'),
                (self.req_language, f'{self.iso_language}_en')
            ]
        
        try:
            return self._req_strip + self._cached_req_strip_add
        except AttributeError:
            self._req_strip = [
                (self.req_api_url, self.req_api_name),
                (self.req_api_key, ''),
                ('is_xml=False', ''),
                ('is_xml=True', '')
            ]
            return self._req_strip + self._cached_req_strip_add

    @req_strip.setter
    def req_strip(self, value):
        self._req_strip = value
        # Invalidate cached req_strip_add when base changes
        if hasattr(self, '_cached_req_strip_add'):
            delattr(self, '_cached_req_strip_add')

    @property
    def req_language(self):
        """Cached request language to avoid repeated string operations"""
        if self._cached_req_language is None:
            self._cached_req_language = f'{self.iso_language}-{self.iso_country}'
        return self._cached_req_language

    @property
    def iso_language(self):
        """Cached ISO language code"""
        if self._cached_iso_language is None:
            self._cached_iso_language = self.language[:2]
        return self._cached_iso_language

    @property
    def iso_country(self):
        """Cached ISO country code"""
        if self._cached_iso_country is None:
            self._cached_iso_country = self.language[-2:]
        return self._cached_iso_country

    @property
    def genres(self):
        """Base class returns None - overridden in TMDb class"""
        return None

    @property
    def mapper(self):
        """Cached mapper instance to avoid repeated creation"""
        if self._cached_mapper is None:
            self._cached_mapper = ItemMapper(self.language, self.genres)
        return self._cached_mapper

    @staticmethod
    def get_url_separator(separator=None):
        """Optimized URL separator using dict lookup"""
        if separator in URL_SEPARATORS:
            return URL_SEPARATORS[separator]
        elif not separator:
            return URL_SEPARATORS['DEFAULT']
        else:
            return False

    @staticmethod
    def get_paginated_items(items, limit=None, page=1, total_pages=None):
        """Optimized pagination with early returns and reduced imports"""
        from jurialmunkey.parser import try_int
        
        # Handle total_pages pagination first (most common case)
        if total_pages and try_int(page) < try_int(total_pages):
            items.append({'next_page': try_int(page) + 1})
            return items
        
        # Handle limit-based pagination
        if limit is not None:
            from tmdbhelper.lib.items.pages import PaginatedItems
            paginated_items = PaginatedItems(items, page=page, limit=limit)
            return paginated_items.items + paginated_items.next_page
        
        return items

    def configure_request_kwargs(self, kwargs):
        """Base configuration - can be overridden in subclasses"""
        kwargs['language'] = self.req_language
        return kwargs

    def get_response_json(self, *args, postdata=None, headers=None, method=None, **kwargs):
        """Optimized response handling with efficient URL generation"""
        kwargs = self.configure_request_kwargs(kwargs)
        requrl = self.get_request_url(*args, **kwargs)
        return self.get_api_request_json(requrl, postdata=postdata, headers=headers, method=method)

    def invalidate_cache(self):
        """Clear cached values when language changes"""
        self._cached_iso_language = None
        self._cached_iso_country = None
        self._cached_req_language = None
        self._cached_mapper = None
        if hasattr(self, '_cached_req_strip_add'):
            delattr(self, '_cached_req_strip_add')


class TMDb(TMDbAPI):
    """Enhanced TMDb API with comprehensive append_to_response optimization"""
    
    # Pre-defined append strings for different content types
    append_to_response = 'credits,images,release_dates,external_ids,keywords,reviews,videos,watch/providers'
    append_to_response_tvshow = 'aggregate_credits,images,content_ratings,external_ids,keywords,reviews,videos,watch/providers'
    append_to_response_person = 'images,external_ids,movie_credits,tv_credits'
    append_to_response_movies_simple = 'images,external_ids,release_dates'
    append_to_response_tvshow_simple = 'images,external_ids,content_ratings'
    api_name = 'TMDb'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Cache setting values to avoid repeated lookups
        self._setting_ignore_regionreleasefilter = None
        self._setting_checked = False
        
        # Cache computed language strings
        self._cached_include_image_language = None
        self._cached_include_video_language = None

    @property
    def tmdb_database(self):
        """Lazy-loaded database with proper circular import handling"""
        if not hasattr(self, '_tmdb_database'):
            from tmdbhelper.lib.query.database.database import FindQueriesDatabase
            self._tmdb_database = FindQueriesDatabase()
            self._tmdb_database.tmdb_api = self  # Must override attribute to avoid circular import
        return self._tmdb_database

    @property
    def get_tmdb_id(self):
        """Direct access to database get_tmdb_id method"""
        return self.tmdb_database.get_tmdb_id

    @cached_property
    def genres(self):
        """Cached genres from database"""
        return self.tmdb_database.genres

    @property
    def iso_region(self):
        """Cached region setting with efficient lookup"""
        if not self.setting_ignore_regionreleasefilter:
            return self.iso_country
        return None

    @property
    def setting_ignore_regionreleasefilter(self):
        """Cached setting lookup to avoid repeated API calls"""
        if not self._setting_checked:
            self._setting_ignore_regionreleasefilter = get_setting('ignore_regionreleasefilter')
            self._setting_checked = True
        return self._setting_ignore_regionreleasefilter

    @property
    def include_image_language(self):
        """Cached image language string"""
        if self._cached_include_image_language is None:
            self._cached_include_image_language = f'{self.iso_language},null,en'
        return self._cached_include_image_language

    @property
    def include_video_language(self):
        """Cached video language string"""
        if self._cached_include_video_language is None:
            self._cached_include_video_language = f'{self.iso_language},null,en'
        return self._cached_include_video_language

    def configure_request_kwargs(self, kwargs):
        """Enhanced request configuration with all TMDb-specific parameters"""
        # Start with base configuration
        kwargs = super().configure_request_kwargs(kwargs)
        
        # Add TMDb-specific parameters efficiently
        region = self.iso_region
        if region:
            kwargs['region'] = region
            
        kwargs.update({
            'include_image_language': self.include_image_language,
            'include_video_language': self.include_video_language
        })
        
        return kwargs

    def invalidate_cache(self):
        """Extended cache invalidation for TMDb-specific cached values"""
        super().invalidate_cache()
        
        # Clear TMDb-specific caches
        self._setting_checked = False
        self._setting_ignore_regionreleasefilter = None
        self._cached_include_image_language = None
        self._cached_include_video_language = None
        
        # Clear database cache if it exists
        if hasattr(self, '_tmdb_database'):
            delattr(self, '_tmdb_database')

    def reset_settings_cache(self):
        """Force settings cache refresh (useful for settings changes)"""
        self._setting_checked = False
        self._setting_ignore_regionreleasefilter = None
        # Also invalidate global API URL cache
        global _api_url_checked
        _api_url_checked = False