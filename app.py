import os
import requests
import re
import urllib.parse
import time
import json
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, send_file, Response, flash, get_flashed_messages, jsonify
from difflib import get_close_matches, SequenceMatcher  # For string similarity
from PIL import Image  # For image processing
from datetime import datetime  # For handling dates and times
from urllib.parse import unquote

# Native macOS file operations - no retry logic needed
# macOS SMB client handles transient errors automatically
def safe_listdir(path: str):
    """List directory contents. macOS handles SMB errors natively."""
    try:
        return os.listdir(path)
    except (OSError, PermissionError) as e:
        print(f"Error listing directory {path}: {e}", flush=True)
        return []

def safe_exists(path: str):
    """Check if path exists. macOS handles SMB errors natively."""
    try:
        return os.path.exists(path)
    except (OSError, PermissionError):
        return False

def safe_send_file(path: str, **kwargs):
    """Send file with basic error handling. macOS handles SMB errors natively."""
    return send_file(path, **kwargs)

# Unavailability tracking - persisted to JSON file
UNAVAILABLE_DATA_FILE = os.path.join(os.path.dirname(__file__), 'unavailable_artwork.json')

def load_unavailable_data():
    """Load unavailable artwork tracking from JSON file."""
    if os.path.exists(UNAVAILABLE_DATA_FILE):
        try:
            with open(UNAVAILABLE_DATA_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading unavailable data: {e}", flush=True)
            return {}
    return {}

def save_unavailable_data(data):
    """Save unavailable artwork tracking to JSON file."""
    try:
        with open(UNAVAILABLE_DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving unavailable data: {e}", flush=True)
        return False

def is_artwork_unavailable(directory, artwork_type):
    """Check if artwork type is marked as unavailable for a directory."""
    unavailable_data = load_unavailable_data()
    return unavailable_data.get(directory, {}).get(artwork_type, False)

def mark_artwork_unavailable(directory, artwork_type, unavailable=True):
    """Mark artwork type as unavailable (or available) for a directory."""
    unavailable_data = load_unavailable_data()
    if directory not in unavailable_data:
        unavailable_data[directory] = {}
    unavailable_data[directory][artwork_type] = unavailable
    return save_unavailable_data(unavailable_data)

# Local cache for artwork thumbnails
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'artwork_cache')
CACHE_METADATA_FILE = os.path.join(CACHE_DIR, 'cache_metadata.json')

def ensure_cache_dir():
    """Ensure the cache directory exists."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        print(f"Created cache directory: {CACHE_DIR}", flush=True)

def get_cache_path(directory, filename):
    """Get the local cache path for an artwork file."""
    # Use hash of directory name to avoid filesystem issues with special characters
    import hashlib
    dir_hash = hashlib.md5(directory.encode()).hexdigest()
    cache_subdir = os.path.join(CACHE_DIR, dir_hash)
    if not os.path.exists(cache_subdir):
        os.makedirs(cache_subdir)
    return os.path.join(cache_subdir, filename)

def copy_to_cache(source_path, directory, filename):
    """Copy an artwork file from SMB to local cache."""
    try:
        cache_path = get_cache_path(directory, filename)

        # Check if already cached and up to date
        if os.path.exists(cache_path):
            try:
                # Try to compare timestamps, but don't fail if SMB doesn't support it
                if os.path.getmtime(source_path) <= os.path.getmtime(cache_path):
                    return False  # Already cached and up to date
            except (OSError, PermissionError):
                # If timestamp comparison fails, just skip (already have cached version)
                return False

        # Read file content and write to cache (avoids metadata permission issues)
        with open(source_path, 'rb') as src:
            file_content = src.read()

        with open(cache_path, 'wb') as dst:
            dst.write(file_content)

        return True
    except Exception as e:
        print(f"Error copying to cache {source_path}: {e}", flush=True)
        return False

def get_cached_artwork_url(directory, filename):
    """Get the URL for cached artwork."""
    import hashlib
    dir_hash = hashlib.md5(directory.encode()).hexdigest()
    return f"/cache/{dir_hash}/{filename}"

def save_cache_metadata(metadata):
    """Save cache metadata (last refresh time, stats, etc.)."""
    ensure_cache_dir()
    try:
        with open(CACHE_METADATA_FILE, 'w') as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        print(f"Error saving cache metadata: {e}", flush=True)

def load_cache_metadata():
    """Load cache metadata."""
    if os.path.exists(CACHE_METADATA_FILE):
        try:
            with open(CACHE_METADATA_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading cache metadata: {e}", flush=True)
    return {}

def save_scan_cache(media_type, artwork_type, media_list, total):
    """Save directory scan results to avoid repeated SMB scans."""
    cache_file = os.path.join(CACHE_DIR, f'scan_cache_{media_type}_{artwork_type}.json')
    try:
        with open(cache_file, 'w') as f:
            json.dump({
                'media_list': media_list,
                'total': total,
                'timestamp': datetime.now().isoformat()
            }, f)
        print(f"Saved scan cache for {media_type}/{artwork_type}: {total} items", flush=True)
    except Exception as e:
        print(f"Error saving scan cache: {e}", flush=True)

def load_scan_cache(media_type, artwork_type):
    """Load cached directory scan results."""
    cache_file = os.path.join(CACHE_DIR, f'scan_cache_{media_type}_{artwork_type}.json')
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                print(f"Loaded scan cache for {media_type}/{artwork_type}: {data['total']} items from {data['timestamp']}", flush=True)
                return data['media_list'], data['total']
        except Exception as e:
            print(f"Error loading scan cache: {e}", flush=True)
    return None, None

def update_single_cache_entry(media_type, artwork_type, directory_path):
    """Update a single entry in the scan cache after downloading artwork."""
    cache_file = os.path.join(CACHE_DIR, f'scan_cache_{media_type}_{artwork_type}.json')
    if not os.path.exists(cache_file):
        print(f"Cache file doesn't exist, skipping update: {cache_file}", flush=True)
        return False

    try:
        # Load the current cache
        with open(cache_file, 'r') as f:
            data = json.load(f)

        media_list = data.get('media_list', [])

        # Find the entry matching this directory
        directory_name = os.path.basename(directory_path)
        for item in media_list:
            if item.get('directory') == directory_name or item.get('path') == directory_path:
                # Re-scan just this directory to get updated artwork status
                artwork_config = ARTWORK_TYPES[artwork_type]
                file_prefix = artwork_config['file_prefix']

                # Check for artwork files
                for ext in ['jpg', 'jpeg', 'png']:
                    artwork_path = os.path.join(directory_path, f'{file_prefix}.{ext}')
                    thumb_path = os.path.join(directory_path, f'{file_prefix}-thumb.{ext}')

                    if safe_exists(artwork_path):
                        # Update the status to "found"
                        item['has_artwork'] = True
                        item['artwork_status'] = 'found'

                        # Copy thumbnail to cache if exists
                        if safe_exists(thumb_path):
                            thumb_filename = f"{file_prefix}-thumb.{ext}"
                            copy_to_cache(thumb_path, directory_name, thumb_filename)
                            item['artwork_thumb'] = get_cached_artwork_url(directory_name, thumb_filename)

                        print(f"Updated cache entry for {directory_name}: artwork now found", flush=True)
                        break

                # Save the updated cache
                with open(cache_file, 'w') as f:
                    json.dump(data, f)

                return True

        print(f"Entry not found in cache for directory: {directory_name}", flush=True)
        return False

    except Exception as e:
        print(f"Error updating cache entry: {e}", flush=True)
        return False

# Initialize Flask application for managing movie and TV show posters
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'mediarr-default-secret-key-change-in-production')

# Custom Jinja2 filter to remove year information from movie titles for cleaner display
@app.template_filter('remove_year')
def remove_year(value):
    # Regex to remove years in the format 19xx, 20xx, 21xx, 22xx, or 23xx
    return re.sub(r'\b(19|20|21|22|23)\d{2}\b', '', value).strip()

# Fetch TMDb API key from environment variables for movie/TV show metadata
TMDB_API_KEY = os.getenv('TMDB_API_KEY')

# Base URLs for TMDb API and poster images
BASE_URL = "https://api.themoviedb.org/3"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/original"

# Define base folders for organizing movies and TV shows
# Environment variables allow flexible folder configuration without code changes
# Default paths use macOS Volumes for native app, override with env vars if needed
movie_folders_env = os.getenv('MOVIE_FOLDERS', '/Volumes/UNAS_Data/Media/Movies,/Volumes/UNAS_Data/Media/Kids Movies')
tv_folders_env = os.getenv('TV_FOLDERS', '/Volumes/UNAS_Data/Media/TV Shows,/Volumes/UNAS_Data/Media/Kids TV,/Volumes/UNAS_Data/Media/Anime')

# Parse comma-separated folder lists (don't check existence at startup due to SMB mount timing)
movie_folders = [folder.strip() for folder in movie_folders_env.split(',') if folder.strip()]
tv_folders = [folder.strip() for folder in tv_folders_env.split(',') if folder.strip()]

# Log the configured folders (actual existence will be checked when scanning)
print(f"Configured movie folders: {movie_folders}")
print(f"Configured TV folders: {tv_folders}")

# Ensure cache directory exists on startup
ensure_cache_dir()
print(f"Cache directory: {CACHE_DIR}")

# Function to normalize movie/TV show titles for consistent searching and comparison
def normalize_title(title):
    # Remove all non-alphanumeric characters and convert to lowercase
    return re.sub(r'[^a-z0-9]+', '', title.lower())

# Helper function to remove leading "The " from titles for more accurate sorting
def strip_leading_the(title):
    if title.lower().startswith("the "):
        return title[4:]  # Remove "The " (4 characters)
    return title

# Function to generate a URL-friendly and anchor-safe ID from the media title
def generate_clean_id(title):
    # Replace all non-alphanumeric characters with dashes and strip leading/trailing dashes
    clean_id = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    return clean_id

# Artwork type configuration
ARTWORK_TYPES = {
    'poster': {
        'name': 'Posters',
        'emoji': '🎭',
        'file_prefix': 'poster',
        'tmdb_key': 'posters',
        'default_height': 450
    },
    'logo': {
        'name': 'Logos',
        'emoji': '🏷️',
        'file_prefix': 'logo',
        'tmdb_key': 'logos',
        'default_height': 150
    },
    'backdrop': {
        'name': 'Backdrops',
        'emoji': '🎬',
        'file_prefix': 'backdrop',
        'tmdb_key': 'backdrops',
        'default_height': 200
    }
}

# Function to retrieve media directories and their associated artwork
def get_artwork_data(base_folders=None, artwork_type='poster', use_cache=True):
    # Default to movie folders if no folders specified
    if base_folders is None:
        base_folders = movie_folders

    # Determine media type for caching
    media_type = 'movie' if base_folders == movie_folders else 'tv'

    # Try to load from cache first
    if use_cache:
        cached_list, cached_total = load_scan_cache(media_type, artwork_type)
        if cached_list is not None:
            return cached_list, cached_total

    # Get artwork configuration
    artwork_config = ARTWORK_TYPES.get(artwork_type, ARTWORK_TYPES['poster'])
    file_prefix = artwork_config['file_prefix']

    media_list = []

    # Iterate through specified base folders to find media with artwork
    for base_folder in base_folders:
        # Check if folder exists using SMB-safe check
        if not safe_exists(base_folder):
            print(f"WARNING: Folder does not exist (yet): {base_folder}", flush=True)
            continue

        directories = safe_listdir(base_folder)
        print(f"Scanning {base_folder}: found {len(directories)} directories", flush=True)
        for media_dir in sorted(directories):
            if media_dir.lower() in ["@eadir", "#recycle"]:  # Skip Synology NAS system folders (case-insensitive)
                continue

            media_path = os.path.join(base_folder, media_dir)

            if os.path.isdir(media_path):
                artwork = None
                artwork_thumb = None
                artwork_dimensions = None
                artwork_last_modified = None

                # Search for artwork files in various image formats
                for ext in ['jpg', 'jpeg', 'png']:
                    thumb_path = os.path.join(media_path, f"{file_prefix}-thumb.{ext}")
                    artwork_path = os.path.join(media_path, f"{file_prefix}.{ext}")

                    # Copy thumbnail to local cache and use cached URL
                    if safe_exists(thumb_path):
                        thumb_filename = f"{file_prefix}-thumb.{ext}"
                        copy_to_cache(thumb_path, media_dir, thumb_filename)
                        artwork_thumb = get_cached_artwork_url(media_dir, thumb_filename)

                    # Full artwork still served from SMB (only thumbnails are cached)
                    if safe_exists(artwork_path):
                        artwork = f"/artwork/{urllib.parse.quote(media_dir)}/{file_prefix}.{ext}"

                        # Get artwork image dimensions
                        try:
                            with Image.open(artwork_path) as img:
                                artwork_dimensions = f"{img.width}x{img.height}"
                        except Exception:
                            artwork_dimensions = "Unknown"

                        # Get last modified timestamp of the artwork
                        try:
                            timestamp = os.path.getmtime(artwork_path)
                            artwork_last_modified = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                        except (BlockingIOError, OSError):
                            artwork_last_modified = None
                        break

                # Check for all artwork types to populate indicator badges
                has_poster = False
                has_logo = False
                has_backdrop = False

                for ext in ['jpg', 'jpeg', 'png']:
                    if safe_exists(os.path.join(media_path, f"poster-thumb.{ext}")):
                        has_poster = True
                    if safe_exists(os.path.join(media_path, f"logo-thumb.{ext}")):
                        has_logo = True
                    if safe_exists(os.path.join(media_path, f"backdrop-thumb.{ext}")):
                        has_backdrop = True

                # Generate a clean ID for HTML anchor and URL purposes
                clean_id = generate_clean_id(media_dir)

                # Check if artwork types are marked as unavailable
                poster_unavailable = is_artwork_unavailable(media_dir, 'poster')
                logo_unavailable = is_artwork_unavailable(media_dir, 'logo')
                backdrop_unavailable = is_artwork_unavailable(media_dir, 'backdrop')

                media_list.append({
                    'title': media_dir,
                    'artwork': artwork,
                    'artwork_thumb': artwork_thumb,
                    'artwork_dimensions': artwork_dimensions,
                    'artwork_last_modified': artwork_last_modified,
                    'clean_id': clean_id,
                    'has_artwork': bool(artwork_thumb),
                    'has_poster': has_poster,
                    'has_logo': has_logo,
                    'has_backdrop': has_backdrop,
                    'poster_unavailable': poster_unavailable,
                    'logo_unavailable': logo_unavailable,
                    'backdrop_unavailable': backdrop_unavailable,
                    'tmdb_id': None  # Will be populated later if needed
                })

    # Sort media list, ignoring leading "The" for more natural sorting
    media_list = sorted(media_list, key=lambda x: strip_leading_the(x['title'].lower()))

    # Log final count for debugging
    total_count = len(media_list)
    print(f"Scan complete: {total_count} total items found for {artwork_type}", flush=True)

    # Save scan results to cache
    save_scan_cache(media_type, artwork_type, media_list, total_count)

    return media_list, total_count

# Route for the main index page - movies with artwork type tabs
@app.route('/')
@app.route('/movies')
@app.route('/movies/<artwork_type>')
def index(artwork_type='poster'):
    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        artwork_type = 'poster'

    movies, total_movies = get_artwork_data(movie_folders, artwork_type)

    # Render the unified collection page with tabs
    return render_template('collection.html',
                         media=movies,
                         total_media=total_movies,
                         media_type='movie',
                         artwork_type=artwork_type,
                         artwork_types=ARTWORK_TYPES)

# Route for TV shows page with artwork type tabs
@app.route('/tv')
@app.route('/tv/<artwork_type>')
def tv_shows(artwork_type='poster'):
    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        artwork_type = 'poster'

    tv_shows, total_tv_shows = get_artwork_data(tv_folders, artwork_type)

    # Render the unified collection page with tabs
    return render_template('collection.html',
                         media=tv_shows,
                         total_media=total_tv_shows,
                         media_type='tv',
                         artwork_type=artwork_type,
                         artwork_types=ARTWORK_TYPES)

# Route to trigger a manual refresh of media directories and rebuild cache
@app.route('/refresh')
def refresh():
    # Clear the cache directory to force re-scan
    import shutil
    if os.path.exists(CACHE_DIR):
        try:
            shutil.rmtree(CACHE_DIR)
            print("Cache directory cleared", flush=True)
        except Exception as e:
            print(f"Error clearing cache: {e}", flush=True)

    ensure_cache_dir()

    # Save cache rebuild timestamp
    save_cache_metadata({
        'last_refresh': datetime.now().isoformat(),
        'status': 'rebuilding'
    })

    flash('Cache cleared! Rebuilding from SMB shares...', 'success')
    return redirect(url_for('index'))

# Route for searching movies using TMDb API
@app.route('/search_movie', methods=['GET'])
def search_movie():
    # Get search query, artwork type, and directory from URL parameters
    query = request.args.get('query', '')
    artwork_type = request.args.get('artwork_type', 'poster')
    directory = request.args.get('directory', '')

    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        artwork_type = 'poster'

    # Search movies on TMDb using the API
    print(f"Searching TMDb for: {query}", flush=True)
    print(f"API Key present: {bool(TMDB_API_KEY)}", flush=True)
    response = requests.get(f"{BASE_URL}/search/movie", params={"api_key": TMDB_API_KEY, "query": query})
    print(f"TMDb response status: {response.status_code}", flush=True)
    response_data = response.json()
    print(f"TMDb response: {response_data}", flush=True)
    results = response_data.get('results', [])

    # Generate clean IDs for each movie result
    for result in results:
        result['clean_id'] = generate_clean_id(result['title'])

    # Render search results template
    return render_template('search_results.html',
                         query=query,
                         results=results,
                         content_type='movie',
                         artwork_type=artwork_type,
                         directory=directory)
# Route for searching TV shows using TMDb API
@app.route('/search_tv', methods=['GET'])
def search_tv():
    # Decode the URL-encoded query parameter to handle special characters
    query = unquote(request.args.get('query', ''))
    artwork_type = request.args.get('artwork_type', 'poster')
    directory = request.args.get('directory', '')

    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        artwork_type = 'poster'

    # Log the received search query for debugging purposes
    app.logger.info(f"Search TV query received: {query}")

    # Send search request to TMDb API for TV shows, with filters for English-language results
    response = requests.get(f"{BASE_URL}/search/tv", params={
        "api_key": TMDB_API_KEY,
        "query": query,
        "include_adult": False,
        "language": "en-US",
        "page": 1
    })
    results = response.json().get('results', [])

    # Log the number of results returned by the API
    app.logger.info(f"TMDb API returned {len(results)} results for query: {query}")

    # Generate clean IDs for each TV show result for URL and anchor purposes
    for result in results:
        result['clean_id'] = generate_clean_id(result['name'])
        app.logger.info(f"Result processed: {result['name']} -> Clean ID: {result['clean_id']}")

    # Render search results template with TV show results
    return render_template('search_results.html',
                         query=query,
                         results=results,
                         content_type="tv",
                         artwork_type=artwork_type,
                         directory=directory)

# Route for selecting a movie and displaying available artwork
@app.route('/select_movie/<int:movie_id>',methods=['GET'])
@app.route('/select_movie/<int:movie_id>/<artwork_type>', methods=['GET'])
def select_movie(movie_id, artwork_type='poster'):
    # Get directory from URL parameters
    directory = request.args.get('directory', '')

    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        artwork_type = 'poster'

    artwork_config = ARTWORK_TYPES[artwork_type]
    tmdb_key = artwork_config['tmdb_key']

    # Fetch detailed information about the selected movie from TMDb API
    movie_details = requests.get(f"{BASE_URL}/movie/{movie_id}", params={"api_key": TMDB_API_KEY}).json()

    # Extract movie title and generate a clean ID for URL/anchor purposes
    movie_title = movie_details.get('title', '')
    clean_id = generate_clean_id(movie_title)

    # Request available artwork for the selected movie from TMDb API
    artwork_response = requests.get(f"{BASE_URL}/movie/{movie_id}/images", params={"api_key": TMDB_API_KEY}).json()
    artwork_items = artwork_response.get(tmdb_key, [])

    # Filter artwork to include only English language items
    # Posters: Only 'en' language
    # Logos/Backdrops: 'en' or None (no language metadata)
    if artwork_type == 'poster':
        artwork_items = [item for item in artwork_items if item.get('iso_639_1') == 'en']
    else:
        # For logos and backdrops, include items without language or with 'en'
        artwork_items = [item for item in artwork_items if item.get('iso_639_1') in ['en', None]]

    # If no artwork available and we have a directory, mark as unavailable and redirect
    if len(artwork_items) == 0 and directory:
        print(f"No {artwork_type} artwork available for {movie_title}, marking as unavailable", flush=True)
        mark_artwork_unavailable(directory, artwork_type, True)
        flash(f'No {artwork_type} artwork available on TMDb. Marked as unavailable.', 'info')
        return redirect(url_for('index', artwork_type=artwork_type, show_missing='true'))

    # Sort artwork by resolution in descending order (highest resolution first)
    artwork_sorted = sorted(artwork_items, key=lambda x: x['width'] * x['height'], reverse=True)

    # Format artwork details for display
    formatted_artwork = [{
        'url': f"{POSTER_BASE_URL}{item['file_path']}",
        'size': f"{item['width']}x{item['height']}",
        'language': item.get('iso_639_1', 'N/A')
    } for item in artwork_sorted]

    # Render artwork selection template
    return render_template('artwork_selection.html',
                         media_title=movie_title,
                         content_type='movie',
                         artwork=formatted_artwork,
                         artwork_type=artwork_type,
                         artwork_config=artwork_config,
                         tmdb_id=movie_id)

# Route for selecting a TV show and displaying available artwork
@app.route('/select_tv/<int:tv_id>', methods=['GET'])
@app.route('/select_tv/<int:tv_id>/<artwork_type>', methods=['GET'])
def select_tv(tv_id, artwork_type='poster'):
    # Get directory from URL parameters
    directory = request.args.get('directory', '')

    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        artwork_type = 'poster'

    artwork_config = ARTWORK_TYPES[artwork_type]
    tmdb_key = artwork_config['tmdb_key']

    # Fetch detailed information about the selected TV show from TMDb API
    tv_details = requests.get(f"{BASE_URL}/tv/{tv_id}", params={"api_key": TMDB_API_KEY}).json()

    # Extract TV show title and generate a clean ID for URL/anchor purposes
    tv_title = tv_details.get('name', '')
    clean_id = generate_clean_id(tv_title)

    # Request available artwork for the selected TV show from TMDb API
    artwork_response = requests.get(f"{BASE_URL}/tv/{tv_id}/images", params={"api_key": TMDB_API_KEY}).json()
    artwork_items = artwork_response.get(tmdb_key, [])

    # Filter artwork to include only English language items
    # Posters: Only 'en' language
    # Logos/Backdrops: 'en' or None (no language metadata)
    if artwork_type == 'poster':
        artwork_items = [item for item in artwork_items if item.get('iso_639_1') == 'en']
    else:
        artwork_items = [item for item in artwork_items if item.get('iso_639_1') in ['en', None]]

    # If no artwork available and we have a directory, mark as unavailable and redirect
    if len(artwork_items) == 0 and directory:
        print(f"No {artwork_type} artwork available for {tv_title}, marking as unavailable", flush=True)
        mark_artwork_unavailable(directory, artwork_type, True)
        flash(f'No {artwork_type} artwork available on TMDb. Marked as unavailable.', 'info')
        return redirect(url_for('tv_shows', artwork_type=artwork_type, show_missing='true'))

    # Sort artwork by resolution in descending order (highest resolution first)
    artwork_sorted = sorted(artwork_items, key=lambda x: x['width'] * x['height'], reverse=True)

    # Format artwork details for display
    formatted_artwork = [{
        'url': f"{POSTER_BASE_URL}{item['file_path']}",
        'size': f"{item['width']}x{item['height']}",
        'language': item.get('iso_639_1', 'N/A')
    } for item in artwork_sorted]

    # Render artwork selection template
    return render_template('artwork_selection.html',
                         media_title=tv_title,
                         content_type='tv',
                         artwork=formatted_artwork,
                         artwork_type=artwork_type,
                         artwork_config=artwork_config,
                         tmdb_id=tv_id)

# Function to handle artwork download and thumbnail creation
def save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type='poster'):
    # Get artwork configuration
    artwork_config = ARTWORK_TYPES.get(artwork_type, ARTWORK_TYPES['poster'])
    file_prefix = artwork_config['file_prefix']

    # Logos should be PNG to preserve transparency, others are JPEG
    file_ext = 'png' if artwork_type == 'logo' else 'jpg'

    # Define full paths for the artwork and thumbnail
    full_artwork_path = os.path.join(save_dir, f'{file_prefix}.{file_ext}')
    thumb_artwork_path = os.path.join(save_dir, f'{file_prefix}-thumb.{file_ext}')

    try:
        # Remove any existing artwork files in the directory
        # Try multiple times with delay if file is busy
        for ext in ['jpg', 'jpeg', 'png']:
            existing_artwork = os.path.join(save_dir, f'{file_prefix}.{ext}')
            existing_thumb = os.path.join(save_dir, f'{file_prefix}-thumb.{ext}')

            # Remove existing artwork file
            if os.path.exists(existing_artwork):
                try:
                    os.remove(existing_artwork)
                    app.logger.info(f"Removed existing file: {existing_artwork}")
                except OSError as e:
                    if e.errno == 16:  # Resource busy
                        # Try to rename it to .old first, then remove
                        try:
                            old_path = existing_artwork + '.old'
                            if os.path.exists(old_path):
                                os.remove(old_path)
                            os.rename(existing_artwork, old_path)
                            os.remove(old_path)
                            app.logger.info(f"Removed busy file via rename: {existing_artwork}")
                        except Exception as rename_err:
                            app.logger.warning(f"Could not remove {existing_artwork}: {rename_err}")
                    else:
                        app.logger.warning(f"Could not remove {existing_artwork}: {e}")

            # Remove existing thumbnail file
            if os.path.exists(existing_thumb):
                try:
                    os.remove(existing_thumb)
                    app.logger.info(f"Removed existing file: {existing_thumb}")
                except OSError as e:
                    if e.errno == 16:  # Resource busy
                        # Try to rename it to .old first, then remove
                        try:
                            old_path = existing_thumb + '.old'
                            if os.path.exists(old_path):
                                os.remove(old_path)
                            os.rename(existing_thumb, old_path)
                            os.remove(old_path)
                            app.logger.info(f"Removed busy file via rename: {existing_thumb}")
                        except Exception as rename_err:
                            app.logger.warning(f"Could not remove {existing_thumb}: {rename_err}")
                    else:
                        app.logger.warning(f"Could not remove {existing_thumb}: {e}")

        # Download the full-resolution artwork from the URL
        response = requests.get(artwork_url)
        if response.status_code == 200:
            # Save the downloaded artwork image
            with open(full_artwork_path, 'wb') as file:
                file.write(response.content)

            # Create a thumbnail using Pillow image processing library
            with Image.open(full_artwork_path) as img:
                # For non-logo artwork, convert RGBA to RGB (logos keep transparency)
                if artwork_type != 'logo':
                    if img.mode in ('RGBA', 'LA', 'P'):
                        # Create white background for transparent images
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                        img = background
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                else:
                    # Logos: ensure RGBA mode for transparency
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')

                # Different thumbnail sizes for different artwork types
                if artwork_type == 'poster':
                    # Posters: 300x450
                    target_ratio = 300 / 450
                    thumb_size = (300, 450)
                elif artwork_type == 'logo':
                    # Logos: maintain aspect ratio, max width 400
                    thumb_size = (400, int(400 / (img.width / img.height)))
                    target_ratio = None  # Skip cropping for logos
                else:  # backdrop
                    # Backdrops: 400x225 (16:9 ratio)
                    target_ratio = 400 / 225
                    thumb_size = (400, 225)

                # Crop the image to match the target aspect ratio (skip for logos)
                if target_ratio is not None:
                    aspect_ratio = img.width / img.height
                    if aspect_ratio > target_ratio:
                        # Image is wider than desired ratio, crop the sides
                        new_width = int(img.height * target_ratio)
                        left = (img.width - new_width) // 2
                        img = img.crop((left, 0, left + new_width, img.height))
                    else:
                        # Image is taller than desired ratio, crop the top and bottom
                        new_height = int(img.width / target_ratio)
                        top = (img.height - new_height) // 2
                        img = img.crop((0, top, img.width, top + new_height))

                # Resize the image with high-quality Lanczos resampling
                img = img.resize(thumb_size, Image.LANCZOS)

                # Save the thumbnail - PNG for logos (transparency), JPEG for others
                if artwork_type == 'logo':
                    img.save(thumb_artwork_path, "PNG", optimize=True)
                else:
                    img.save(thumb_artwork_path, "JPEG", quality=90)

            app.logger.info(f"{artwork_config['name']} and thumbnail saved successfully for '{media_title}'")
            return full_artwork_path  # Return the local path where the artwork was saved
        else:
            app.logger.error(f"Failed to download {artwork_type} for '{media_title}'. Status code: {response.status_code}")
            return None

    except Exception as e:
        app.logger.error(f"Error saving {artwork_type} and generating thumbnail for '{media_title}': {e}")
        return None

# Route for handling artwork selection and downloading (posters, logos, backdrops)
@app.route('/select_artwork', methods=['POST'])
def select_artwork():
    # Log the received form data for debugging and tracking
    app.logger.info("Received form data: %s", request.form)

    # Validate that all required form data is present
    if 'artwork_url' not in request.form or 'media_title' not in request.form or 'media_type' not in request.form:
        app.logger.error("Missing form data: %s", request.form)
        return "Bad Request: Missing form data", 400

    try:
        # Extract form data for artwork download
        artwork_url = request.form['artwork_url']
        media_title = request.form['media_title']
        media_type = request.form['media_type']  # Should be either 'movie' or 'tv'
        artwork_type = request.form.get('artwork_type', 'poster')  # Default to poster for backwards compat

        # Validate artwork type
        if artwork_type not in ARTWORK_TYPES:
            artwork_type = 'poster'

        # Log detailed information about the artwork selection
        app.logger.info(f"Artwork URL: {artwork_url}, Media Title: {media_title}, Media Type: {media_type}, Artwork Type: {artwork_type}")

        # Select base folders based on media type (movies or TV shows)
        base_folders = movie_folders if media_type == 'movie' else tv_folders

        # Initialize variables for directory matching
        save_dir = None
        possible_dirs = []
        best_similarity = 0
        best_match_dir = None

        # Normalize media title for comparison
        normalized_media_title = normalize_title(media_title)

        # Search for an exact or closest matching directory
        for base_folder in base_folders:
            directories = safe_listdir(base_folder)
            possible_dirs.extend(directories)

            for directory in directories:
                normalized_dir_name = normalize_title(directory)
                # Calculate string similarity between media title and directory name
                similarity = SequenceMatcher(None, normalized_media_title, normalized_dir_name).ratio()

                # Update best match if current similarity is higher
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match_dir = os.path.join(base_folder, directory)

                # If exact match found, set save directory
                if directory == media_title:
                    save_dir = os.path.join(base_folder, directory)
                    break

            if save_dir:
                break

        # If an exact match is found, proceed with downloading
        if save_dir:
            local_artwork_path = save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type)
            if local_artwork_path:
                # Send Slack notification about successful artwork download
                artwork_name = ARTWORK_TYPES[artwork_type]['name']
                message = f"{artwork_name[:-1]} for '{media_title}' has been downloaded!"  # Remove trailing 's'
                send_slack_notification(message, local_artwork_path, artwork_url)
                # Flash message for browser notification
                flash(message, 'success')

                # Update the cache entry for this specific item
                update_single_cache_entry(media_type, artwork_type, save_dir)
            else:
                flash(f"Failed to download {ARTWORK_TYPES[artwork_type]['name'][:-1]} for '{media_title}'", 'error')
            # Redirect back to the same artwork type tab with missing filter enabled
            redirect_url = url_for('tv_shows' if media_type == 'tv' else 'index', artwork_type=artwork_type, show_missing='true')
            return redirect(f"{redirect_url}#{generate_clean_id(media_title)}")

        # If no exact match, use best similarity match above a threshold
        similarity_threshold = 0.8
        if best_similarity >= similarity_threshold:
            save_dir = best_match_dir
            local_artwork_path = save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type)
            if local_artwork_path:
                # Update the cache entry for this specific item
                update_single_cache_entry(media_type, artwork_type, save_dir)

                # Send Slack notification about successful artwork download
                artwork_name = ARTWORK_TYPES[artwork_type]['name']
                message = f"{artwork_name[:-1]} for '{media_title}' has been downloaded!"
                send_slack_notification(message, local_artwork_path, artwork_url)
                # Flash message for browser notification
                flash(message, 'success')
            else:
                flash(f"Failed to download {ARTWORK_TYPES[artwork_type]['name'][:-1]} for '{media_title}'", 'error')
            # Redirect back to the same artwork type tab with missing filter enabled
            redirect_url = url_for('tv_shows' if media_type == 'tv' else 'index', artwork_type=artwork_type, show_missing='true')
            return redirect(f"{redirect_url}#{generate_clean_id(media_title)}")

        # If no suitable directory found, present user with directory selection options
        similar_dirs = get_close_matches(media_title, possible_dirs, n=5, cutoff=0.5)
        return render_template('select_directory.html',
                             similar_dirs=similar_dirs,
                             media_title=media_title,
                             artwork_url=artwork_url,
                             media_type=media_type,
                             artwork_type=artwork_type)

    except FileNotFoundError as fnf_error:
        # Log and handle file not found errors
        app.logger.error("File not found: %s", fnf_error)
        return "Directory not found", 404
    except Exception as e:
        # Log and handle any unexpected errors
        app.logger.exception("Unexpected error in select_artwork route: %s", e)
        return "Internal Server Error", 500

# Legacy route for backwards compatibility
@app.route('/select_poster', methods=['POST'])
def select_poster():
    return select_artwork()

# Route for serving artwork (posters, logos, backdrops) from the file system
@app.route('/artwork/<path:filename>')
def serve_artwork(filename):
    # Combine movie and TV folders to search both sets of paths
    base_folders = movie_folders + tv_folders

    # Check if a "refresh" flag is present in the URL query parameters
    refresh = request.args.get('refresh', 'false')
    for base_folder in base_folders:
        full_path = os.path.join(base_folder, filename)
        # Skip Synology NAS special directories
        if '@eaDir' in full_path:
            continue
        if os.path.exists(full_path):
            # Serve the file from the appropriate directory using safe_send_file
            # to handle BlockingIOError on SMB mounts
            response = safe_send_file(full_path)
            if refresh == 'true':
                # If refresh is requested, set no-cache headers
                response.cache_control.no_cache = True
                response.cache_control.must_revalidate = True
                response.cache_control.max_age = 0
            else:
                # Set long-term caching for efficiency
                response.cache_control.max_age = 31536000  # 1 year in seconds
            return response

    # Log an error if the file is not found
    app.logger.error(f"File not found for {filename} in any base folder.")
    return "File not found", 404

# Route for serving cached artwork (local, fast!)
@app.route('/cache/<path:filename>')
def serve_cached_artwork(filename):
    """Serve artwork from local cache - much faster than SMB!"""
    try:
        cache_file_path = os.path.join(CACHE_DIR, filename)
        if os.path.exists(cache_file_path):
            response = send_file(cache_file_path)
            # Set long-term caching since these are local files
            response.cache_control.max_age = 31536000  # 1 year
            return response
        else:
            app.logger.warning(f"Cached file not found: {filename}")
            return "Cached file not found", 404
    except Exception as e:
        app.logger.error(f"Error serving cached file {filename}: {e}")
        return "Error serving cached file", 500

# Legacy route for backwards compatibility with old /poster/ URLs
@app.route('/poster/<path:filename>')
def serve_poster_legacy(filename):
    return serve_artwork(filename)

# Route for manually confirming the directory and saving the artwork
@app.route('/confirm_directory', methods=['POST'])
def confirm_directory():
    # Extract form data for manual artwork directory selection
    selected_directory = request.form.get('selected_directory')
    media_title = request.form.get('media_title')
    artwork_url = request.form.get('artwork_url')
    content_type = request.form.get('content_type', 'movie')  # Default to 'movie'
    artwork_type = request.form.get('artwork_type', 'poster')  # Default to 'poster'

    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        artwork_type = 'poster'

    # Log all received form data for debugging
    app.logger.info(f"Received data: selected_directory={selected_directory}, media_title={media_title}, artwork_url={artwork_url}, content_type={content_type}, artwork_type={artwork_type}")

    # Validate form data
    if not selected_directory or not media_title or not artwork_url:
        app.logger.error("Missing form data: selected_directory=%s, media_title=%s, artwork_url=%s",
                         selected_directory, media_title, artwork_url)
        return "Bad Request: Missing form data", 400

    # Find the correct base folder for the selected directory
    save_dir = None
    base_folders = movie_folders if content_type == 'movie' else tv_folders

    for base_folder in base_folders:
        if selected_directory in safe_listdir(base_folder):
            save_dir = os.path.join(base_folder, selected_directory)
            break

    if not save_dir:
        # Log an error if directory not found
        app.logger.error(f"Selected directory '{selected_directory}' not found in base folders.")
        return "Directory not found", 404

    # Save the artwork and get the local path
    local_artwork_path = save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type)
    if local_artwork_path:
        # Send Slack notification about successful download
        artwork_name = ARTWORK_TYPES[artwork_type]['name']
        message = f"{artwork_name[:-1]} for '{media_title}' has been downloaded!"
        send_slack_notification(message, local_artwork_path, artwork_url)
        app.logger.info(f"{artwork_name} successfully saved to {local_artwork_path}")
    else:
        app.logger.error(f"Failed to save {artwork_type} for '{media_title}'")
        return f"Failed to save {artwork_type}", 500

    # Generate clean ID for navigation anchor
    anchor = generate_clean_id(media_title)

    # Determine redirect URL based on content type and include artwork type
    redirect_url = url_for('index' if content_type == 'movie' else 'tv_shows', artwork_type=artwork_type)

    # Log the redirect URL for verification
    app.logger.info(f"Redirect URL: {redirect_url}#{anchor}")

    return redirect(f"{redirect_url}#{anchor}")

# Function to send Slack notifications about poster downloads
def send_slack_notification(message, local_poster_path, poster_url):
    # Retrieve Slack webhook URL from environment variables
    slack_webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if slack_webhook_url:
        # Prepare Slack payload with message and poster details
        payload = {
            "text": message,
            "attachments": [
                {
                    "text": f"Poster saved to: {local_poster_path}",
                    "image_url": poster_url  # Display original TMDb poster in Slack
                }
            ]
        }
        try:
            # Send notification to Slack
            response = requests.post(slack_webhook_url, json=payload)
            if response.status_code == 200:
                print(f"Slack notification sent successfully for '{local_poster_path}'")
            else:
                print(f"Failed to send Slack notification. Status code: {response.status_code}")
        except Exception as e:
            print(f"Error sending Slack notification: {e}")
    else:
        print("Slack webhook URL not set.")

# API endpoint to toggle artwork unavailability
@app.route('/api/toggle_unavailable', methods=['POST'])
def toggle_unavailable():
    try:
        data = request.json
        directory = data.get('directory')
        artwork_type = data.get('artwork_type')

        if not directory or not artwork_type:
            return jsonify({'success': False, 'error': 'Missing directory or artwork_type'}), 400

        if artwork_type not in ARTWORK_TYPES:
            return jsonify({'success': False, 'error': 'Invalid artwork_type'}), 400

        # Check current status and toggle
        current_status = is_artwork_unavailable(directory, artwork_type)
        new_status = not current_status

        # Save the new status
        success = mark_artwork_unavailable(directory, artwork_type, new_status)

        if success:
            return jsonify({
                'success': True,
                'unavailable': new_status,
                'message': f"{artwork_type.capitalize()} marked as {'unavailable' if new_status else 'available'}"
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save unavailability data'}), 500

    except Exception as e:
        app.logger.error(f"Error toggling unavailability: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Main entry point for running the Flask application
if __name__ == '__main__':
    # Start the app, listening on all network interfaces at port 6789
    app.run(
        host="0.0.0.0",
        port=6789,
        debug=False,
        use_reloader=False,
    )