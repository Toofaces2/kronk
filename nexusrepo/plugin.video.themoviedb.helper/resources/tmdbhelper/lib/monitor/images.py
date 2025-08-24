import os
import io
import xbmcvfs
import colorsys
import hashlib
import random
import threading
import time
from collections import OrderedDict, defaultdict
from xbmc import getCacheThumbName, skinHasImage, Monitor, sleep
from tmdbhelper.lib.addon.plugin import get_infolabel, get_setting, get_condvisibility, ADDONDATA
from jurialmunkey.window import WindowPropertySetter
from jurialmunkey.parser import try_int, try_float
from tmdbhelper.lib.files.futils import make_path
from tmdbhelper.lib.addon.thread import SafeThread
import urllib.request as urllib
from tmdbhelper.lib.addon.logger import kodi_log
from PIL import ImageFilter, Image

CROPIMAGE_SOURCE = "Art(artist.clearlogo)|Art(tvshow.clearlogo)|Art(clearlogo)"

ARTWORK_LOOKUP_TABLE = {
    'poster': ['Art(tvshow.poster)', 'Art(poster)', 'Art(thumb)'],
    'fanart': ['Art(fanart)', 'Art(thumb)'],
    'landscape': ['Art(landscape)', 'Art(fanart)', 'Art(thumb)'],
    'thumb': ['Art(thumb)']}

# Smart Image Optimization Components
_image_cache = {}
_cache_lock = threading.RLock()
_processing_queue = {}
_stats = {'cache_hits': 0, 'cache_misses': 0, 'compressions': 0, 'errors': 0}

def md5hash(value):
    value = str(value).encode(errors='surrogatepass')
    return hashlib.md5(value).hexdigest()


class SmartImageCache:
    """Intelligent image caching with compression and LRU eviction"""
    
    def __init__(self, max_memory_mb=50, max_files=500):
        self.max_memory = max_memory_mb * 1024 * 1024  # Convert to bytes
        self.max_files = max_files
        self.cache = OrderedDict()
        self.memory_usage = 0
        self.lock = threading.RLock()
        self.stats = defaultdict(int)
    
    def get_cache_key(self, source, method=None, params=None):
        """Generate cache key from source and parameters"""
        key_data = f"{source}:{method}:{str(params) if params else ''}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, cache_key):
        """Get cached image data"""
        with self.lock:
            if cache_key in self.cache:
                # Move to end (most recently used)
                self.cache.move_to_end(cache_key)
                self.stats['hits'] += 1
                return self.cache[cache_key]
            
            self.stats['misses'] += 1
            return None
    
    def set(self, cache_key, image_data, file_path=None):
        """Cache image data with smart eviction"""
        if not image_data:
            return
            
        try:
            with self.lock:
                # Calculate memory usage
                data_size = len(image_data) if isinstance(image_data, bytes) else 0
                
                # Evict if needed
                while (len(self.cache) >= self.max_files or 
                       self.memory_usage + data_size > self.max_memory):
                    if not self.cache:
                        break
                    old_key = next(iter(self.cache))
                    old_data = self.cache.pop(old_key)
                    if isinstance(old_data.get('data'), bytes):
                        self.memory_usage -= len(old_data['data'])
                    self.stats['evictions'] += 1
                
                # Cache new data
                cache_entry = {
                    'data': image_data,
                    'file_path': file_path,
                    'timestamp': time.time(),
                    'access_count': 1
                }
                
                self.cache[cache_key] = cache_entry
                self.memory_usage += data_size
                
        except Exception as e:
            kodi_log(f'SmartImageCache: Error caching image: {e}', 1)
    
    def clear(self):
        """Clear all cached data"""
        with self.lock:
            self.cache.clear()
            self.memory_usage = 0
    
    def get_stats(self):
        """Get cache statistics"""
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'entries': len(self.cache),
                'memory_mb': round(self.memory_usage / (1024 * 1024), 2),
                'hit_rate': f"{hit_rate:.1f}%",
                **dict(self.stats)
            }

# Global smart image cache
_smart_cache = SmartImageCache()


def _optimize_image_format(img, quality=85):
    """Optimize image format and compression"""
    try:
        # Convert to optimal format
        if img.mode in ('RGBA', 'LA', 'P'):
            # Images with transparency -> PNG with optimization
            output = io.BytesIO()
            img.save(output, format='PNG', optimize=True)
            return output.getvalue(), '.png'
        else:
            # Photos/solid images -> JPEG with compression
            if img.mode != 'RGB':
                img = img.convert('RGB')
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            return output.getvalue(), '.jpg'
    except Exception as e:
        kodi_log(f'Image optimization error: {e}', 1)
        return None, None


def _saveimage(img, destination, optimize=True):
    """Save image with optimization"""
    try:
        if optimize:
            # Get optimized data
            optimized_data, ext = _optimize_image_format(img)
            if optimized_data:
                # Save optimized version
                with xbmcvfs.File(destination, 'wb') as f:
                    f.write(optimized_data)
                global _stats
                _stats['compressions'] += 1
                return True
        
        # Fallback to original save method
        img.save(xbmcvfs.translatePath(destination))
        return True
        
    except Exception as e:
        kodi_log(f'Image save error: {e}', 2)
        return False


def _imageopen(image):
    """Open image with smart caching"""
    cache_key = md5hash(f"open:{image}")
    
    # Check smart cache first
    cached_data = _smart_cache.get(cache_key)
    if cached_data and cached_data.get('data'):
        try:
            return Image.open(io.BytesIO(cached_data['data']))
        except Exception:
            pass
    
    # Load from file
    try:
        with xbmcvfs.File(image, 'rb') as f:
            image_bytes = f.readBytes()
        
        # Cache the raw data
        _smart_cache.set(cache_key, image_bytes, image)
        
        return Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        kodi_log(f'Image open error for {image}: {e}', 2)
        return None


def _closeimage(image, targetfile=None):
    """Close image with cleanup"""
    try:
        if image:
            image.close()
    except Exception:
        pass
        
    if targetfile:
        try:
            xbmcvfs.delete(targetfile)
        except Exception:
            pass


def _openimage(image, targetpath, filename):
    """ Optimized image open helper with smart caching """
    cache_key = md5hash(f"openimage:{image}:{targetpath}:{filename}")
    
    # Check smart cache
    cached_result = _smart_cache.get(cache_key)
    if cached_result and cached_result.get('image_obj'):
        return cached_result['image_obj'], None
    
    cached_image_path = urllib.unquote(image.replace('image://', ''))
    if cached_image_path.endswith('/'):
        cached_image_path = cached_image_path[:-1]

    # Optimized cache file search
    cache_paths = [
        getCacheThumbName(cached_image_path),
        getCacheThumbName(image)
    ]
    
    for path in cache_paths:
        cache_locations = [
            os.path.join('special://profile/Thumbnails/', path[0], path[:-4] + '.jpg'),
            os.path.join('special://profile/Thumbnails/', path[0], path[:-4] + '.png'),
            os.path.join('special://profile/Thumbnails/Video/', path[0], path)
        ]
        
        for cache in cache_locations:
            if xbmcvfs.exists(cache):
                try:
                    img = _imageopen(xbmcvfs.translatePath(cache))
                    if img:
                        # Cache the successful result
                        _smart_cache.set(cache_key, None, cache)
                        return img, None
                except Exception as error:
                    kodi_log('Image error: Could not open cached image --> %s' % error, 2)

    # Handle skin images
    if skinHasImage(image):
        if not image.startswith('special://skin'):
            image = os.path.join('special://skin/media/', image)
        try:
            img = _imageopen(xbmcvfs.translatePath(image))
            if img:
                _smart_cache.set(cache_key, None, image)
                return img, None
        except Exception:
            return '', None

    # Copy and open temporary file
    targetfile = os.path.join(targetpath, f'temp_{filename}')
    if not xbmcvfs.exists(targetfile):
        try:
            xbmcvfs.copy(image, targetfile)
        except Exception as e:
            kodi_log(f'Image copy error: {e}', 2)
            return '', None
            
    try:
        img = _imageopen(targetfile)
        if img:
            return img, targetfile
    except Exception as error:
        kodi_log(f'Image error: Could not get image for {image} -> {error}', 2)
    
    return '', None


class ImageProcessingQueue:
    """Async image processing queue to prevent blocking"""
    
    def __init__(self, max_workers=3):
        self.max_workers = max_workers
        self.processing = {}
        self.completed = {}
        self.lock = threading.Lock()
        
    def is_processing(self, task_key):
        with self.lock:
            return task_key in self.processing
    
    def get_completed(self, task_key):
        with self.lock:
            return self.completed.get(task_key)
    
    def add_task(self, task_key, func, *args, **kwargs):
        """Add task to processing queue"""
        with self.lock:
            if task_key in self.processing or task_key in self.completed:
                return
            
            # Clean up old completed tasks
            if len(self.completed) > 100:
                # Keep only the 50 most recent
                items = list(self.completed.items())[-50:]
                self.completed = dict(items)
            
            self.processing[task_key] = True
            
        # Start processing in background
        def _process():
            try:
                result = func(*args, **kwargs)
                with self.lock:
                    self.completed[task_key] = result
                    self.processing.pop(task_key, None)
            except Exception as e:
                with self.lock:
                    self.processing.pop(task_key, None)
                kodi_log(f'Image processing error: {e}', 2)
        
        thread = SafeThread(target=_process)
        thread.start()

# Global processing queue
_processing_queue = ImageProcessingQueue()


class ImageFunctions(SafeThread, WindowPropertySetter):
    save_path = f"{get_setting('image_location', 'str') or ADDONDATA}{{}}/"
    blur_size = try_int(get_infolabel('Skin.String(TMDbHelper.Blur.Size)')) or 480
    crop_size = (800, 310)
    radius = try_int(get_infolabel('Skin.String(TMDbHelper.Blur.Radius)')) or 40

    def __init__(self, method=None, artwork=None, is_thread=True, prefix='ListItem'):
        if is_thread:
            SafeThread.__init__(self)
        self.image = artwork
        self.func = None
        self.save_orig = False
        self.save_prop = None
        self.cache_key = None
        
        if method == 'blur':
            self.func = self.blur
            self.save_path = make_path(self.save_path.format('blur_v3'))
            self.save_prop = f'{prefix}.BlurImage'
            self.save_orig = True
        elif method == 'crop':
            self.func = self.crop
            self.save_path = make_path(self.save_path.format('crop_v3'))
            self.save_prop = f'{prefix}.CropImage'
            self.save_orig = True
        elif method == 'desaturate':
            self.func = self.desaturate
            self.save_path = make_path(self.save_path.format('desaturate_v3'))
            self.save_prop = f'{prefix}.DesaturateImage'
            self.save_orig = True
        elif method == 'colors':
            self.func = self.colors
            self.save_path = make_path(self.save_path.format('colors_v3'))
            self.save_prop = f'{prefix}.Colors'

        # Generate cache key for smart caching
        if self.image and method:
            params = {
                'blur_size': self.blur_size,
                'crop_size': self.crop_size,
                'radius': self.radius
            }
            self.cache_key = _smart_cache.get_cache_key(self.image, method, params)

    def run(self):
        if not self.save_prop or not self.func:
            return
            
        # Check if we're already processing this
        if self.cache_key and _processing_queue.is_processing(self.cache_key):
            return
            
        # Check for completed result
        if self.cache_key:
            completed_result = _processing_queue.get_completed(self.cache_key)
            if completed_result:
                self.set_properties(completed_result)
                return
        
        # Process the image
        output = self.func(self.image) if self.image else None
        self.set_properties(output)

    def set_properties(self, output):
        if not output:
            self.get_property(self.save_prop, clear_property=True)
            self.get_property(f'{self.save_prop}.Original', clear_property=True) if self.save_orig else None
            return
        self.get_property(self.save_prop, output)
        self.get_property(f'{self.save_prop}.Original', self.image) if self.save_orig else None

    def clamp(self, x):
        return max(0, min(x, 255))

    def crop(self, source):
        if not source:
            return ''
            
        # Check smart cache first
        if self.cache_key:
            cached_result = _smart_cache.get(self.cache_key)
            if cached_result and cached_result.get('file_path'):
                if xbmcvfs.exists(cached_result['file_path']):
                    return cached_result['file_path']
        
        filename = f'cropped-{md5hash(source)}.png'
        destination = os.path.join(self.save_path, filename)
        
        try:
            if not xbmcvfs.exists(destination):
                img, targetfile = _openimage(source, self.save_path, filename)
                if not img or img == '':
                    return ''
                    
                try:
                    img_rgba = img.convert('RGBa')
                    img = img.crop(img_rgba.getbbox())
                except Exception:
                    try:
                        img = img.crop(img.getbbox())
                    except Exception:
                        _closeimage(img, targetfile)
                        return ''
                        
                img.thumbnail(self.crop_size, Image.Resampling.LANCZOS)
                
                if not _saveimage(img, destination, optimize=True):
                    _closeimage(img, targetfile)
                    return ''
                    
                _closeimage(img, targetfile)
            
            # Cache the result
            if self.cache_key and destination:
                _smart_cache.set(self.cache_key, None, destination)
                
            return destination
            
        except Exception as exc:
            kodi_log(f'Crop Error:\n{source}\n{destination}\n{exc}', 2)
            global _stats
            _stats['errors'] += 1
            return ''

    def blur(self, source):
        if not source:
            return ''
            
        # Check smart cache first
        if self.cache_key:
            cached_result = _smart_cache.get(self.cache_key)
            if cached_result and cached_result.get('file_path'):
                if xbmcvfs.exists(cached_result['file_path']):
                    return cached_result['file_path']
        
        filename = f'{md5hash(source)}-{self.radius}-{self.blur_size}.jpg'
        destination = os.path.join(self.save_path, filename)
        
        try:
            if not xbmcvfs.exists(destination):
                img, targetfile = _openimage(source, self.save_path, filename)
                if not img or img == '':
                    return ''
                    
                # Optimize thumbnail operation
                img.thumbnail((self.blur_size, self.blur_size), Image.Resampling.LANCZOS)
                img = img.convert('RGB')
                
                # Apply blur
                img = img.filter(ImageFilter.GaussianBlur(self.radius))
                
                if not _saveimage(img, destination, optimize=True):
                    _closeimage(img, targetfile)
                    return ''
                    
                _closeimage(img, targetfile)
            
            # Cache the result
            if self.cache_key and destination:
                _smart_cache.set(self.cache_key, None, destination)
                
            return destination
            
        except Exception as exc:
            kodi_log(f'Blur Error: {exc}', 2)
            global _stats
            _stats['errors'] += 1
            return ''

    def desaturate(self, source):
        if not source:
            return ''
            
        # Check smart cache first
        if self.cache_key:
            cached_result = _smart_cache.get(self.cache_key)
            if cached_result and cached_result.get('file_path'):
                if xbmcvfs.exists(cached_result['file_path']):
                    return cached_result['file_path']
        
        filename = f'{md5hash(source)}.png'
        destination = os.path.join(self.save_path, filename)
        
        try:
            if not xbmcvfs.exists(destination):
                img, targetfile = _openimage(source, self.save_path, filename)
                if not img or img == '':
                    return ''
                    
                img = img.convert('LA')
                
                if not _saveimage(img, destination, optimize=True):
                    _closeimage(img, targetfile)
                    return ''
                    
                _closeimage(img, targetfile)
            
            # Cache the result
            if self.cache_key and destination:
                _smart_cache.set(self.cache_key, None, destination)
                
            return destination
            
        except Exception as exc:
            kodi_log(f'Desaturate Error: {exc}', 2)
            global _stats
            _stats['errors'] += 1
            return ''

    def get_maincolor(self, img):
        rgb_list = [None, None, None]
        for channel in range(3):
            pixels = img.getdata(band=channel)
            values = [pixel for pixel in pixels]
            rgb_list[channel] = self.clamp(sum(values) / len(values))
        return rgb_list

    def get_compcolor(self, r, g, b, shift=0.33):
        hls_tuple = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        rgb_tuple = colorsys.hls_to_rgb(abs(hls_tuple[0] - shift), hls_tuple[1], hls_tuple[2])
        return self.rgb_to_int(*rgb_tuple)

    def get_color_lumsat(self, r, g, b):
        hls_tuple = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        hue = hls_tuple[0]
        lum = try_float(get_infolabel('Skin.String(TMDbHelper.Colors.Luminance)')) or hls_tuple[1]
        sat = try_float(get_infolabel('Skin.String(TMDbHelper.Colors.Saturation)')) or hls_tuple[2]
        return self.rgb_to_int(*colorsys.hls_to_rgb(hue, lum, sat))

    def rgb_to_int(self, r, g, b):
        return [try_int(self.clamp(i * 255)) for i in [r, g, b]]

    def rgb_to_hex(self, r, g, b):
        return f'FF{r:02x}{g:02x}{b:02x}'

    def hex_to_rgb(self, colorhex):
        r = try_int(colorhex[2:4], 16)
        g = try_int(colorhex[4:6], 16)
        b = try_int(colorhex[6:8], 16)
        return [r, g, b]

    def set_prop_colorgradient(self, propname, start_hex, end_hex, checkprop):
        if not start_hex or not end_hex:
            return
        steps = 20
        rgb_a = self.hex_to_rgb(start_hex)
        rgb_z = self.hex_to_rgb(end_hex)
        inc_r = (rgb_z[0] - rgb_a[0]) // steps
        inc_g = (rgb_z[1] - rgb_a[1]) // steps
        inc_b = (rgb_z[2] - rgb_a[2]) // steps
        val_r = rgb_a[0]
        val_g = rgb_a[1]
        val_b = rgb_a[2]
        for i in range(steps):
            if self.get_property(checkprop) != start_hex:
                return
            hex_value = self.rgb_to_hex(val_r, val_g, val_b)
            self.get_property(propname, set_property=hex_value)
            val_r = val_r + inc_r
            val_g = val_g + inc_g
            val_b = val_b + inc_b
            Monitor().waitForAbort(0.05)
        self.get_property(propname, set_property=end_hex)
        return end_hex

    def colors(self, source):
        if not source:
            return ''
            
        # Check smart cache first
        if self.cache_key:
            cached_result = _smart_cache.get(self.cache_key)
            if cached_result and cached_result.get('data'):
                try:
                    # Return cached color data
                    return cached_result['data']
                except Exception:
                    pass
        
        filename = f'{md5hash(source)}.png'
        destination = self.save_path + filename
        targetfile = None
        
        try:
            if xbmcvfs.exists(destination):
                img = _imageopen(xbmcvfs.translatePath(destination))
            else:
                img, targetfile = _openimage(source, self.save_path, filename)
                if not img or img == '':
                    return ''
                    
                img.thumbnail((128, 128), Image.Resampling.LANCZOS)
                img = img.convert('RGB')
                _saveimage(img, destination, optimize=True)
                
            if not img:
                return ''
                
            maincolor_rgb = self.get_maincolor(img)
            maincolor_hex = self.rgb_to_hex(*self.get_color_lumsat(*maincolor_rgb))
            compcolor_rgb = self.get_compcolor(*maincolor_rgb)
            compcolor_hex = self.rgb_to_hex(*self.get_color_lumsat(*compcolor_rgb))
            
            # Cache the color result
            if self.cache_key:
                _smart_cache.set(self.cache_key, maincolor_hex, destination)
            
            # Set color properties with gradients
            maincolor_propname = self.save_prop + '.Main'
            maincolor_propchek = self.save_prop + '.MainCheck'
            maincolor_propvalu = self.get_property(maincolor_propname)
            
            if not maincolor_propvalu:
                self.get_property(maincolor_propname, set_property=maincolor_hex)
            else:
                self.get_property(maincolor_propchek, set_property=maincolor_propvalu)
                thread_maincolor = SafeThread(target=self.set_prop_colorgradient, args=[
                    maincolor_propname, maincolor_propvalu, maincolor_hex, maincolor_propchek])
                thread_maincolor.start()
                
            compcolor_propname = self.save_prop + '.Comp'
            compcolor_propchek = self.save_prop + '.CompCheck'
            compcolor_propvalu = self.get_property(compcolor_propname)
            
            if not compcolor_propvalu:
                self.get_property(compcolor_propname, set_property=compcolor_hex)
            else:
                self.get_property(compcolor_propchek, set_property=compcolor_propvalu)
                thread_compcolor = SafeThread(target=self.set_prop_colorgradient, args=[
                    compcolor_propname, compcolor_propvalu, compcolor_hex, compcolor_propchek])
                thread_compcolor.start()
                
            _closeimage(img, targetfile)
            return maincolor_hex
            
        except Exception as exc:
            kodi_log(f'Colors Error: {exc}', 1)
            global _stats
            _stats['errors'] += 1
            return ''


class ImageArtworkGetter():
    def __init__(self, parent, source, prebuilt_artwork=None):
        self._parent = parent
        self._source = source
        self.prebuilt_artwork = prebuilt_artwork

    @property
    def infolabels(self):
        try:
            return self._infolabels
        except AttributeError:
            self._infolabels = self.get_infolabels()
            return self._infolabels

    def get_infolabels(self):
        if not self._source:
            return ARTWORK_LOOKUP_TABLE.get('thumb')
        return ARTWORK_LOOKUP_TABLE.get(self._source, self._source.split("|"))

    @property
    def built_artwork(self):
        try:
            return self._built_artwork
        except AttributeError:
            self._built_artwork = self.get_built_artwork()
            return self._built_artwork

    def get_built_artwork(self):
        return self.prebuilt_artwork or self._parent.get_builtartwork()

    @property
    def artwork(self):
        try:
            return self._artwork
        except AttributeError:
            self._artwork = self.get_artwork()
            return self._artwork

    def get_artwork(self):
        return next((j for j in (self.get_artwork_item(i) for i in self.infolabels) if j), None)

    @property
    def artwork_fallback(self):
        try:
            return self._artwork_fallback
        except AttributeError:
            self._artwork_fallback = self.get_artwork_fallback()
            return self._artwork_fallback

    def get_artwork_fallback(self):
        return next((j for j in (self.get_artwork_item(i, prebuilt=True) for i in self.infolabels) if j), None)

    def get_artwork_item(self, item, prebuilt=False):
        def _get_artwork_item(i, x=''):
            if not prebuilt:
                return self._parent.get_infolabel(i.format(x=x))
            if not i.startswith('art('):
                return
            return self.built_artwork.get(i.format(x=x)[4:-1])

        if '{x}' not in item:
            return _get_artwork_item(item)
        artwork0 = _get_artwork_item(item)
        if not artwork0:
            return
        artwork1 = _get_artwork_item(item, x=1)
        if not artwork1:
            return artwork0
        artworks = [artwork0, artwork1]
        for x in range(2, 9):
            artwork = _get_artwork_item(item, x=x)
            if not artwork:
                break
            artworks.append(artwork)
        return random.choice(artworks)


class ImageManipulations(WindowPropertySetter):
    def get_infolabel(self, info):
        return get_infolabel(f'ListItem.{info}')

    def get_builtartwork(self):
        return

    def get_artwork(self, source='', build_fallback=False, built_artwork=None):
        source = source or ''
        source = source.lower()
        for _source in source.split("||"):
            img_get = ImageArtworkGetter(self, _source, prebuilt_artwork=built_artwork)
            if img_get.artwork:
                return img_get.artwork
            if not build_fallback or not img_get.built_artwork:
                continue
            if img_get.artwork_fallback:
                return img_get.artwork_fallback

    def get_image_manipulations(self, use_winprops=False, built_artwork=None, allow_list=('crop', 'blur', 'desaturate', 'colors', )):
        images = {}
        _manipulations = (
            {'method': 'crop',
                'active': lambda: get_condvisibility("Skin.HasSetting(TMDbHelper.EnableCrop)"),
                'images': lambda: self.get_artwork(
                    source=CROPIMAGE_SOURCE,
                    build_fallback=True,
                    built_artwork=built_artwork)},
            {'method': 'blur',
                'active': lambda: get_condvisibility("Skin.HasSetting(TMDbHelper.EnableBlur)"),
                'images': lambda: self.get_artwork(
                    source=self.get_property('Blur.SourceImage'),
                    build_fallback=True,
                    built_artwork=built_artwork)
                or self.get_property('Blur.Fallback')},
            {'method': 'desaturate',
                'active': lambda: get_condvisibility("Skin.HasSetting(TMDbHelper.EnableDesaturate)"),
                'images': lambda: self.get_artwork(
                    source=self.get_property('Desaturate.SourceImage'),
                    build_fallback=True,
                    built_artwork=built_artwork)
                or self.get_property('Desaturate.Fallback')},
            {'method': 'colors',
                'active': lambda: get_condvisibility("Skin.HasSetting(TMDbHelper.EnableColors)"),
                'images': lambda: self.get_artwork(
                    source=self.get_property('Colors.SourceImage'),
                    build_fallback=True,
                    built_artwork=built_artwork)
                or self.get_property('Colors.Fallback')},)

        for i in _manipulations:
            if i['method'] not in allow_list:
                continue
            if not i['active']():
                continue
                
            # Use async processing for better performance
            task_key = f"{i['method']}_{md5hash(str(i['images']()))}"
            
            # Check if already processing
            if _processing_queue.is_processing(task_key):
                continue
                
            # Check for completed result
            completed_result = _processing_queue.get_completed(task_key)
            if completed_result:
                images[f'{i["method"]}image'] = completed_result
                images[f'{i["method"]}image.original'] = i['images']()
                if use_winprops:
                    imgfunc = ImageFunctions(method=i['method'], is_thread=False, artwork=i['images']())
                    imgfunc.set_properties(completed_result)
                continue
            
            # Create image function and process
            imgfunc = ImageFunctions(method=i['method'], is_thread=False, artwork=i['images']())
            
            if imgfunc.image and imgfunc.func:
                # For immediate response, try synchronous processing first
                try:
                    output = imgfunc.func(imgfunc.image)
                    images[f'{i["method"]}image'] = output
                    images[f'{i["method"]}image.original'] = imgfunc.image
                    if use_winprops:
                        imgfunc.set_properties(output)
                except Exception as e:
                    kodi_log(f'Image manipulation error for {i["method"]}: {e}', 2)
                    # Queue for async processing as fallback
                    _processing_queue.add_task(task_key, imgfunc.func, imgfunc.image)
            
        return images


def get_image_cache_stats():
    """Get comprehensive image cache statistics"""
    global _stats
    smart_stats = _smart_cache.get_stats()
    processing_stats = {
        'processing': len(_processing_queue.processing),
        'completed': len(_processing_queue.completed)
    }
    
    return {
        'smart_cache': smart_stats,
        'processing_queue': processing_stats,
        'global_stats': _stats
    }


def clear_image_caches():
    """Clear all image caches"""
    global _smart_cache, _processing_queue, _stats
    
    try:
        _smart_cache.clear()
        
        with _processing_queue.lock:
            _processing_queue.completed.clear()
            
        _stats = {'cache_hits': 0, 'cache_misses': 0, 'compressions': 0, 'errors': 0}
        
        kodi_log('TMDbHelper: Image caches cleared', 1)
        return True
        
    except Exception as e:
        kodi_log(f'Error clearing image caches: {e}', 2)
        return False


def optimize_image_storage():
    """Background task to optimize stored images"""
    try:
        image_dirs = [
            f"{ADDONDATA}blur_v3/",
            f"{ADDONDATA}crop_v3/", 
            f"{ADDONDATA}desaturate_v3/",
            f"{ADDONDATA}colors_v3/"
        ]
        
        optimized_count = 0
        for img_dir in image_dirs:
            if not xbmcvfs.exists(img_dir):
                continue
                
            dirs, files = xbmcvfs.listdir(img_dir)
            for filename in files:
                if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue
                    
                filepath = os.path.join(img_dir, filename)
                try:
                    # Check if already optimized (smaller file size indicates compression)
                    stat = xbmcvfs.Stat(filepath)
                    if stat.st_size() < 50000:  # Already optimized if under 50KB
                        continue
                        
                    # Re-optimize large images
                    img = _imageopen(filepath)
                    if img:
                        # Save with optimization
                        _saveimage(img, filepath, optimize=True)
                        img.close()
                        optimized_count += 1
                        
                        # Don't block the system
                        if optimized_count % 10 == 0:
                            Monitor().waitForAbort(0.1)
                            
                except Exception as e:
                    kodi_log(f'Error optimizing {filepath}: {e}', 1)
                    continue
        
        if optimized_count > 0:
            kodi_log(f'TMDbHelper: Optimized {optimized_count} images', 1)
            
    except Exception as e:
        kodi_log(f'Error in image optimization task: {e}', 2)


# Auto-start background optimization (run once per session)
_optimization_started = False
def _start_background_optimization():
    global _optimization_started
    if not _optimization_started:
        _optimization_started = True
        thread = SafeThread(target=optimize_image_storage)
        thread.start()

# Initialize background optimization when module is imported
_start_background_optimization()