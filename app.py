import os
import requests
import re
import urllib.parse
import json
import time
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, send_file, Response
from difflib import get_close_matches, SequenceMatcher  # For string similarity
from PIL import Image  # For image processing
from datetime import datetime  # For handling dates and times
from urllib.parse import unquote

# ============================================================================
# ARTWORK CONFIGURATION
# ============================================================================
# Configuration for all artwork types (posters, logos, backdrops)
# This makes the code extensible and avoids hardcoding artwork-specific logic
ARTWORK_TYPES = {
    'poster': {
        'name': 'Poster',
        'emoji': '🎭',
        'tmdb_key': 'posters',  # Key in TMDb API response
        'base_filename': 'poster',
        'extensions': ['jpg', 'jpeg', 'png'],
        'thumbnail_size': (300, 450),
        'aspect_ratio': (2, 3),
        'filter_language': True,  # Filter to English only
    },
    'logo': {
        'name': 'Logo',
        'emoji': '🏷️',
        'tmdb_key': 'logos',
        'base_filename': 'logo',
        'extensions': ['png', 'jpg', 'jpeg'],  # PNG preferred for transparency
        'thumbnail_size': (300, 150),
        'aspect_ratio': (2, 1),
        'filter_language': False,  # Logos are often language-agnostic
        'preferred_extension': 'png',  # For transparency
    },
    'backdrop': {
        'name': 'Backdrop',
        'emoji': '🎬',
        'tmdb_key': 'backdrops',
        'base_filename': 'backdrop',
        'extensions': ['jpg', 'jpeg', 'png'],
        'thumbnail_size': (300, 169),
        'aspect_ratio': (16, 9),
        'filter_language': False,
    }
}

# SMB-safe directory listing helper
def safe_listdir(path: str, retries: int = 8, base_delay: float = 0.05):
    """
    Safely list directory contents with retry logic for SMB mounts.
    Degrades gracefully on BlockingIOError instead of raising 500 errors.
    """
    last_exc = None
    for attempt in range(retries):
        try:
            return os.listdir(path)
        except BlockingIOError as e:
            last_exc = e
            time.sleep(base_delay * (2 ** attempt))
    return []  # degrade gracefully, never 500

# SMB-safe file reading helper
def safe_send_file(path: str, retries: int = 8, base_delay: float = 0.05, **kwargs):
    """
    Safely send a file with retry logic for SMB mounts.
    Handles BlockingIOError by retrying with exponential backoff.
    """
    last_exc = None
    for attempt in range(retries):
        try:
            return send_file(path, **kwargs)
        except BlockingIOError as e:
            last_exc = e
            if attempt < retries - 1:  # Don't sleep on the last attempt
                time.sleep(base_delay * (2 ** attempt))
    # If all retries fail, raise the last exception
    raise last_exc

# Initialize Flask application for managing movie and TV show backdrops
app = Flask(__name__)

# Custom Jinja2 filter to remove year information from movie titles for cleaner display
@app.template_filter('remove_year')
def remove_year(value):
    # Regex to remove years in the format 19xx, 20xx, 21xx, 22xx, or 23xx
    return re.sub(r'\b(19|20|21|22|23)\d{2}\b', '', value).strip()

# Custom Jinja2 filter to remove year information from movie titles for cleaner display
@app.template_filter('remove_year')
def remove_year(value):
    # Regex to remove years in the format 19xx, 20xx, 21xx, 22xx, or 23xx
    return re.sub(r'\b(19|20|21|22|23)\d{2}\b', '', value).strip()

# Custom Jinja2 filter to remove {tmdb-xxxxx} patterns from movie titles
@app.template_filter('remove_tmdb')
def remove_tmdb(value):
    # Remove patterns like {tmdb-xxxxx}
    return re.sub(r'\{tmdb\d+\}', '', value).strip()

@app.template_filter('escapejs')
def escapejs_filter(value):
    """
    Escapes single and double quotes in a string for safe JavaScript usage.
    """
    if not isinstance(value, str):
        return value
    return value.replace("'", "\\'").replace('"', '\\"')

# Fetch TMDb API key from environment variables for movie/TV show metadata
TMDB_API_KEY = os.getenv('TMDB_API_KEY')

# Base URLs for TMDb API and backdrop images
BASE_URL = "https://api.themoviedb.org/3"
BACKDROP_BASE_URL = "https://image.tmdb.org/t/p/original"

# Define base folders for organizing movies and TV shows
# Environment variables allow flexible folder configuration without code changes
movie_folders_env = os.getenv('MOVIE_FOLDERS', '/movies,/kids-movies,/anime')
tv_folders_env = os.getenv('TV_FOLDERS', '/tv,/kids-tv')

# Parse comma-separated folder lists and filter out non-existent paths
movie_folders = [folder.strip() for folder in movie_folders_env.split(',') if folder.strip() and os.path.exists(folder.strip())]
tv_folders = [folder.strip() for folder in tv_folders_env.split(',') if folder.strip() and os.path.exists(folder.strip())]

# Log the folders being used for verification
app.logger.info(f"Movie folders: {movie_folders}")
app.logger.info(f"TV folders: {tv_folders}")

# Path to the mapping file that stores TMDb ID -> Directory relationships
MAPPING_FILE = os.path.join(os.path.dirname(__file__), 'tmdb_directory_mapping.json')

# Path to the artwork unavailability tracking file
UNAVAILABLE_FILE = os.path.join(os.path.dirname(__file__), 'artwork_unavailable.json')

# ============================================================================
# ARTWORK UNAVAILABILITY PERSISTENCE
# ============================================================================

def load_unavailable_artwork():
    """
    Load artwork unavailability data from JSON file.
    Format: {"{media_type}_{tmdb_id}": {"poster": false, "logo": true, "backdrop": false}}
    """
    if os.path.exists(UNAVAILABLE_FILE):
        try:
            with open(UNAVAILABLE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            app.logger.error(f"Error loading unavailable artwork file: {e}")
            return {}
    return {}

def save_unavailable_artwork(data):
    """Save artwork unavailability data to JSON file."""
    try:
        with open(UNAVAILABLE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        app.logger.info(f"Saved unavailable artwork data to {UNAVAILABLE_FILE}")
    except Exception as e:
        app.logger.error(f"Error saving unavailable artwork file: {e}")

def extract_tmdb_id(directory_name):
    """
    Extract TMDb ID from directory name like 'Movie Name (2014) {tmdb-12345}'.
    Returns the TMDb ID as a string, or None if not found.
    """
    match = re.search(r'\{tmdb-(\d+)\}', directory_name)
    return match.group(1) if match else None

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
    # Remove year patterns like "(2024)" or "2024"
    title_without_year = re.sub(r'\(\d{4}\)|\b\d{4}\b', '', title).strip()
    # Remove TMDb IDs in curly braces
    title_without_tmdb = re.sub(r'\{tmdb\d+\}', '', title_without_year).strip()
    # Generate a clean ID by replacing non-alphanumeric characters with dashes
    clean_id = re.sub(r'[^a-z0-9]+', '-', title_without_tmdb.lower()).strip('-')
    return clean_id

# Function to load the TMDb ID to directory mapping from disk
def load_directory_mapping():
    """Load the mapping file that remembers which TMDb IDs go to which directories"""
    if os.path.exists(MAPPING_FILE):
        try:
            with open(MAPPING_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            app.logger.error(f"Error loading mapping file: {e}")
            return {}
    return {}

# Function to save the TMDb ID to directory mapping to disk
def save_directory_mapping(mapping):
    """Save the mapping file to remember which TMDb IDs go to which directories"""
    try:
        with open(MAPPING_FILE, 'w') as f:
            json.dump(mapping, f, indent=2)
        app.logger.info(f"Saved directory mapping to {MAPPING_FILE}")
    except Exception as e:
        app.logger.error(f"Error saving mapping file: {e}")

# Function to get directory from mapping for a given TMDb ID and media type
def get_mapped_directory(tmdb_id, media_type):
    """Check if we already know which directory this TMDb ID belongs to"""
    mapping = load_directory_mapping()
    key = f"{media_type}_{tmdb_id}"
    mapped_dir = mapping.get(key)
    if mapped_dir and os.path.exists(mapped_dir):
        app.logger.info(f"Found existing mapping: {key} -> {mapped_dir}")
        return mapped_dir
    elif mapped_dir:
        app.logger.warning(f"Mapped directory no longer exists: {mapped_dir}, removing mapping")
        # Clean up invalid mapping
        del mapping[key]
        save_directory_mapping(mapping)
    return None

# Function to save a new TMDb ID to directory mapping
def save_mapped_directory(tmdb_id, media_type, directory_path):
    """Remember which directory this TMDb ID belongs to for next time"""
    mapping = load_directory_mapping()
    key = f"{media_type}_{tmdb_id}"
    mapping[key] = directory_path
    save_directory_mapping(mapping)
    app.logger.info(f"Saved new mapping: {key} -> {directory_path}")

# Function to calculate backdrop resolution for sorting
def backdrop_resolution(backdrop):
    return backdrop['width'] * backdrop['height']  # Calculate the area of the backdrop

# Function to retrieve media directories and their associated backdrop thumbnails
# ============================================================================
# GENERALIZED ARTWORK SCANNING
# ============================================================================

def scan_artwork_type(media_path, artwork_type, config, media_dir):
    """
    Scan for a specific artwork type in a media directory.
    Returns dictionary with artwork paths, dimensions, last_modified, has_artwork status.
    """
    base_filename = config['base_filename']
    extensions = config['extensions']

    result = {
        f'{artwork_type}': None,
        f'{artwork_type}_thumb': None,
        f'{artwork_type}_dimensions': None,
        f'{artwork_type}_last_modified': None,
        f'has_{artwork_type}': False
    }

    # Search for artwork files in order of preference
    for ext in extensions:
        thumb_path = os.path.join(media_path, f"{base_filename}-thumb.{ext}")
        full_path = os.path.join(media_path, f"{base_filename}.{ext}")

        # Check for thumbnail
        if os.path.exists(thumb_path):
            result[f'{artwork_type}_thumb'] = f"/artwork/{urllib.parse.quote(media_dir)}/{base_filename}-thumb.{ext}"

        # Check for full artwork
        if os.path.exists(full_path):
            result[f'{artwork_type}'] = f"/artwork/{urllib.parse.quote(media_dir)}/{base_filename}.{ext}"
            result[f'has_{artwork_type}'] = True

            # Get dimensions
            try:
                with Image.open(full_path) as img:
                    result[f'{artwork_type}_dimensions'] = f"{img.width}x{img.height}"
            except Exception:
                result[f'{artwork_type}_dimensions'] = "Unknown"

            # Get last modified timestamp
            try:
                timestamp = os.path.getmtime(full_path)
                result[f'{artwork_type}_last_modified'] = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
            except Exception:
                result[f'{artwork_type}_last_modified'] = None

            break  # Found artwork, stop checking other extensions

    return result

def scan_media_for_artwork(base_folders, media_type='movie'):
    """
    Scan directories for all artwork types simultaneously (posters, logos, backdrops).
    Returns list of media items with artwork status for all types.
    """
    if base_folders is None:
        base_folders = movie_folders if media_type == 'movie' else tv_folders

    media_list = []
    unavailable_data = load_unavailable_artwork()

    # Iterate through all base folders
    for base_folder in base_folders:
        for media_dir in sorted(safe_listdir(base_folder)):
            # Skip Synology NAS system folders
            if media_dir.lower() in ["@eadir", "#recycle"]:
                continue

            media_path = os.path.join(base_folder, media_dir)

            if not os.path.isdir(media_path):
                continue

            # Extract TMDb ID from directory name (if present)
            tmdb_id = extract_tmdb_id(media_dir)

            # Strip TMDb ID pattern from title for display
            clean_title = re.sub(r'\{tmdb-\d+\}', '', media_dir).strip()

            # Create base media item
            media_item = {
                'title': clean_title,
                'directory_name': media_dir,
                'base_folder': base_folder,
                'clean_id': generate_clean_id(media_dir),
                'tmdb_id': tmdb_id
            }

            # Scan for each artwork type
            for artwork_type, config in ARTWORK_TYPES.items():
                artwork_data = scan_artwork_type(media_path, artwork_type, config, media_dir)
                media_item.update(artwork_data)

                # Check if this artwork type is marked as unavailable
                if tmdb_id:
                    unavailable_key = f"{media_type}_{tmdb_id}"
                    if unavailable_key in unavailable_data:
                        media_item[f'{artwork_type}_unavailable'] = \
                            unavailable_data[unavailable_key].get(artwork_type, False)
                    else:
                        media_item[f'{artwork_type}_unavailable'] = False
                else:
                    media_item[f'{artwork_type}_unavailable'] = False

            media_list.append(media_item)

    # Sort by title, ignoring leading "The"
    media_list = sorted(media_list, key=lambda x: strip_leading_the(x['title'].lower()))
    return media_list, len(media_list)

# ============================================================================
# LEGACY FUNCTION (kept for backward compatibility during migration)
# ============================================================================
def get_backdrop_thumbnails(base_folders=None):
    # Default to movie folders if no folders specified
    if base_folders is None:
        base_folders = movie_folders
    media_list = []

    # Iterate through specified base folders to find media with backdrops
    for base_folder in base_folders:
        for media_dir in sorted(safe_listdir(base_folder)):
            if media_dir.lower() in ["@eadir", "#recycle"]:  # Skip Synology NAS system folders (case-insensitive)
                continue

            media_path = os.path.join(base_folder, media_dir)

            if os.path.isdir(media_path):
                backdrop = None
                backdrop_thumb = None
                backdrop_dimensions = None
                backdrop_last_modified = None

                # Search for backdrop files in various image formats
                for ext in ['jpg', 'jpeg', 'png']:
                    thumb_path = os.path.join(media_path, f"backdrop-thumb.{ext}")
                    backdrop_path = os.path.join(media_path, f"backdrop.{ext}")

                    # Store thumbnail and full backdrop paths for web serving
                    if os.path.exists(thumb_path):
                        backdrop_thumb = f"/backdrop/{urllib.parse.quote(media_dir)}/backdrop-thumb.{ext}"

                    if os.path.exists(backdrop_path):
                        backdrop = f"/backdrop/{urllib.parse.quote(media_dir)}/backdrop.{ext}"

                        # Get backdrop image dimensions
                        try:
                            with Image.open(backdrop_path) as img:
                                backdrop_dimensions = f"{img.width}x{img.height}"
                        except Exception:
                            backdrop_dimensions = "Unknown"

                        # Get last modified timestamp of the backdrop
                        timestamp = os.path.getmtime(backdrop_path)
                        backdrop_last_modified = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                        break

                # Generate a clean ID for HTML anchor and URL purposes
                clean_id = generate_clean_id(media_dir)
                media_list.append({
                    'title': re.sub(r'\{tmdb\d+\}', '', media_dir).strip(),  # Strip {tmdb-xxxxx}
                    'backdrop': backdrop,
                    'backdrop_thumb': backdrop_thumb,
                    'backdrop_dimensions': backdrop_dimensions,
                    'backdrop_last_modified': backdrop_last_modified,
                    'clean_id': clean_id,
                    'has_backdrop': bool(backdrop_thumb)
                })

    # Sort media list, ignoring leading "The" for more natural sorting
    media_list = sorted(media_list, key=lambda x: strip_leading_the(x['title'].lower()))
    return media_list, len(media_list)

# Route for the main index page showing movie collection with all artwork types
@app.route('/')
def index():
    movies, total_movies = scan_media_for_artwork(movie_folders, 'movie')

    # Pass artwork types configuration to template
    return render_template('collection.html',
                         media=movies,
                         total_media=total_movies,
                         media_type='movie',
                         artwork_types=ARTWORK_TYPES)

# Route for TV shows page
@app.route('/tv')
def tv_shows():
    tv_shows, total_tv_shows = scan_media_for_artwork(tv_folders, 'tv')

    # Pass artwork types configuration to template
    return render_template('collection.html',
                         media=tv_shows,
                         total_media=total_tv_shows,
                         media_type='tv',
                         artwork_types=ARTWORK_TYPES)

# Route to trigger a manual refresh of media directories
@app.route('/refresh')
def refresh():
    get_backdrop_thumbnails()  # Re-scan the directories
    return redirect(url_for('index'))

# ============================================================================
# API ROUTES FOR AJAX INTERACTIONS
# ============================================================================

@app.route('/api/toggle_unavailable', methods=['POST'])
def toggle_unavailable():
    """
    Toggle artwork unavailability status for a specific media item.
    Expects JSON: {tmdb_id, media_type, artwork_type}
    Returns: {success, new_status}
    """
    try:
        data = request.get_json()
        tmdb_id = data.get('tmdb_id')
        media_type = data.get('media_type')
        artwork_type = data.get('artwork_type')

        if not all([tmdb_id, media_type, artwork_type]):
            return {'success': False, 'error': 'Missing required fields'}, 400

        # Load current unavailability data
        unavailable_data = load_unavailable_artwork()
        key = f"{media_type}_{tmdb_id}"

        # Initialize if doesn't exist
        if key not in unavailable_data:
            unavailable_data[key] = {}

        # Toggle the status
        current_status = unavailable_data[key].get(artwork_type, False)
        new_status = not current_status
        unavailable_data[key][artwork_type] = new_status

        # Save back to file
        save_unavailable_artwork(unavailable_data)

        return {
            'success': True,
            'new_status': new_status
        }
    except Exception as e:
        app.logger.error(f"Error toggling unavailability: {e}")
        return {'success': False, 'error': str(e)}, 500

@app.route('/api/stats')
def get_stats():
    """
    Get collection statistics for progress bars.
    Returns: {total, poster_count, logo_count, backdrop_count, percentages}
    """
    try:
        media_type = request.args.get('media_type', 'movie')
        folders = movie_folders if media_type == 'movie' else tv_folders

        media_list, total = scan_media_for_artwork(folders, media_type)

        # Count artwork by type
        stats = {
            'total': total,
            'poster_count': sum(1 for m in media_list if m.get('has_poster')),
            'logo_count': sum(1 for m in media_list if m.get('has_logo')),
            'backdrop_count': sum(1 for m in media_list if m.get('has_backdrop')),
        }

        # Calculate percentages
        if total > 0:
            stats['poster_percent'] = round((stats['poster_count'] / total) * 100)
            stats['logo_percent'] = round((stats['logo_count'] / total) * 100)
            stats['backdrop_percent'] = round((stats['backdrop_count'] / total) * 100)
        else:
            stats['poster_percent'] = 0
            stats['logo_percent'] = 0
            stats['backdrop_percent'] = 0

        return stats
    except Exception as e:
        app.logger.error(f"Error getting stats: {e}")
        return {'error': str(e)}, 500

# ============================================================================
# SEARCH AND SELECTION ROUTES
# ============================================================================

@app.route('/search_movie', methods=['GET'])
def search_movie():
    # Get search query, directory name, and artwork type from URL parameters
    query = request.args.get('query', '')
    directory = request.args.get('directory', '')  # Get the directory name from the original movie card click
    artwork_type = request.args.get('artwork_type', 'poster')  # Default to poster if not specified

    # Search movies on TMDb using the API
    response = requests.get(f"{BASE_URL}/search/movie", params={"api_key": TMDB_API_KEY, "query": query})
    results = response.json().get('results', [])

    # Generate clean IDs for each movie result
    for result in results:
        result['clean_id'] = generate_clean_id(result['title'])
        result['backdrop_url'] = f"{BACKDROP_BASE_URL}{result.get('backdrop_path')}" if result.get('backdrop_path') else None

    # Render search results template with directory name and artwork type
    return render_template('search_results.html', query=query, results=results, directory=directory, artwork_type=artwork_type, media_type='movie')

# Route for searching TV shows using TMDb API
@app.route('/search_tv', methods=['GET'])
def search_tv():
    # Decode the URL-encoded query parameter to handle special characters
    query = unquote(request.args.get('query', ''))
    directory = request.args.get('directory', '')  # Get the directory name from the original TV show card click
    artwork_type = request.args.get('artwork_type', 'poster')  # Default to poster if not specified

    # Log the received search query for debugging purposes
    app.logger.info(f"Search TV query received: {query}, Directory: {directory}, Artwork Type: {artwork_type}")

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
        result['backdrop_url'] = f"{BACKDROP_BASE_URL}{result.get('backdrop_path')}" if result.get('backdrop_path') else None
        app.logger.info(f"Result processed: {result['name']} -> Clean ID: {result['clean_id']}")

    # Render search results template with TV show results, directory name, and artwork type
    return render_template('search_results.html', query=query, results=results, content_type="tv", directory=directory, artwork_type=artwork_type, media_type='tv')
    
# Generalized route for selecting artwork (poster, logo, or backdrop) for a movie
@app.route('/select_artwork/movie/<int:movie_id>/<artwork_type>', methods=['GET'])
def select_movie_artwork(movie_id, artwork_type):
    # Get the directory name passed from the search results
    directory = request.args.get('directory', '')

    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        return "Invalid artwork type", 400

    # Fetch detailed information about the selected movie from TMDb API
    movie_details = requests.get(f"{BASE_URL}/movie/{movie_id}", params={"api_key": TMDB_API_KEY}).json()

    # Extract movie title and generate a clean ID for URL/anchor purposes
    movie_title = movie_details.get('title', '')
    clean_id = generate_clean_id(movie_title)

    app.logger.info(f"Selected movie: {movie_title}, Artwork type: {artwork_type}, Directory from click: {directory}")

    # Get the configuration for this artwork type
    artwork_config = ARTWORK_TYPES[artwork_type]

    # Request available artwork for the selected movie from TMDb API
    images_response = requests.get(f"{BASE_URL}/movie/{movie_id}/images", params={"api_key": TMDB_API_KEY}).json()
    artworks = images_response.get(artwork_config['tmdb_key'], [])

    # Sort by vote average (popularity) by default
    artworks_sorted = sorted(artworks, key=lambda x: x.get('vote_average', 0), reverse=True)

    # Add full URL to each artwork
    for artwork in artworks_sorted:
        artwork['url'] = f"{BACKDROP_BASE_URL}{artwork['file_path']}"

    # Render artwork selection template
    return render_template('artwork_selection.html',
                         artworks=artworks_sorted,
                         media_title=movie_title,
                         media_type='movie',
                         artwork_type=artwork_type,
                         artwork_config=artwork_config,
                         artwork_base_url=BACKDROP_BASE_URL,
                         tmdb_id=movie_id,
                         directory=directory)

# Generalized route for selecting artwork (poster, logo, or backdrop) for a TV show
@app.route('/select_artwork/tv/<int:tv_id>/<artwork_type>', methods=['GET'])
def select_tv_artwork(tv_id, artwork_type):
    # Get the directory name passed from the search results
    directory = request.args.get('directory', '')

    # Validate artwork type
    if artwork_type not in ARTWORK_TYPES:
        return "Invalid artwork type", 400

    # Fetch detailed information about the selected TV show from TMDb API
    tv_details = requests.get(f"{BASE_URL}/tv/{tv_id}", params={"api_key": TMDB_API_KEY}).json()

    # Extract TV show title and generate a clean ID for URL/anchor purposes
    tv_title = tv_details.get('name', '')
    clean_id = generate_clean_id(tv_title)

    app.logger.info(f"Selected TV show: {tv_title}, Artwork type: {artwork_type}, Directory from click: {directory}")

    # Get the configuration for this artwork type
    artwork_config = ARTWORK_TYPES[artwork_type]

    # Request available artwork for the selected TV show from TMDb API
    images_response = requests.get(f"{BASE_URL}/tv/{tv_id}/images", params={"api_key": TMDB_API_KEY}).json()
    artworks = images_response.get(artwork_config['tmdb_key'], [])

    # Sort by vote average (popularity) by default
    artworks_sorted = sorted(artworks, key=lambda x: x.get('vote_average', 0), reverse=True)

    # Add full URL to each artwork
    for artwork in artworks_sorted:
        artwork['url'] = f"{BACKDROP_BASE_URL}{artwork['file_path']}"

    # Render artwork selection template
    return render_template('artwork_selection.html',
                         artworks=artworks_sorted,
                         media_title=tv_title,
                         media_type='tv',
                         artwork_type=artwork_type,
                         artwork_config=artwork_config,
                         artwork_base_url=BACKDROP_BASE_URL,
                         tmdb_id=tv_id,
                         directory=directory)

# Generalized function to handle artwork download and thumbnail creation
def save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type):
    """Download artwork and generate thumbnail for any artwork type (poster/logo/backdrop)."""
    config = ARTWORK_TYPES[artwork_type]
    base_filename = config['base_filename']
    extensions = config['extensions']
    thumbnail_size = config['thumbnail_size']
    aspect_ratio = config['aspect_ratio']

    # Determine preferred extension for saving (PNG for logos, JPG for others)
    preferred_ext = config.get('preferred_extension', 'jpg')

    # Define full paths for the artwork and thumbnail
    full_artwork_path = os.path.join(save_dir, f'{base_filename}.{preferred_ext}')
    thumb_artwork_path = os.path.join(save_dir, f'{base_filename}-thumb.{preferred_ext}')

    try:
        # Remove any existing artwork files in the directory
        for ext in extensions:
            existing_artwork = os.path.join(save_dir, f'{base_filename}.{ext}')
            existing_thumb = os.path.join(save_dir, f'{base_filename}-thumb.{ext}')
            if os.path.exists(existing_artwork):
                os.remove(existing_artwork)
            if os.path.exists(existing_thumb):
                os.remove(existing_thumb)

        # Download the full-resolution artwork from the URL
        response = requests.get(artwork_url)
        if response.status_code == 200:
            # Save the downloaded artwork image
            with open(full_artwork_path, 'wb') as file:
                file.write(response.content)

            # Create a thumbnail using Pillow image processing library
            with Image.open(full_artwork_path) as img:
                # Calculate aspect ratio to maintain consistent thumbnail dimensions
                img_aspect_ratio = img.width / img.height
                target_ratio = aspect_ratio[0] / aspect_ratio[1]

                # Crop the image to match the target aspect ratio
                if img_aspect_ratio > target_ratio:
                    # Image is wider than desired ratio, crop the sides
                    new_width = int(img.height * target_ratio)
                    left = (img.width - new_width) // 2
                    img = img.crop((left, 0, left + new_width, img.height))
                else:
                    # Image is taller than desired ratio, crop the top and bottom
                    new_height = int(img.width / target_ratio)
                    top = (img.height - new_height) // 2
                    img = img.crop((0, top, img.width, top + new_height))

                # Resize the image to thumbnail size with high-quality Lanczos resampling
                img = img.resize(thumbnail_size, Image.LANCZOS)

                # Save the thumbnail image with appropriate format and quality
                if preferred_ext == 'png':
                    img.save(thumb_artwork_path, "PNG", optimize=True)
                else:
                    img.save(thumb_artwork_path, "JPEG", quality=90)

            app.logger.info(f"{config['name']} and thumbnail saved successfully for '{media_title}'")
            return full_artwork_path  # Return the local path where the artwork was saved
        else:
            app.logger.error(f"Failed to download {artwork_type} for '{media_title}'. Status code: {response.status_code}")
            return None

    except Exception as e:
        app.logger.error(f"Error saving {artwork_type} and generating thumbnail for '{media_title}': {e}")
        return None
    
    # Route for serving artwork files (posters, logos, backdrops) from the file system
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

# Route for handling backdrop selection and downloading
@app.route('/save_artwork', methods=['POST'])
def save_artwork():
    # Log the received form data for debugging and tracking
    app.logger.info("Received form data: %s", request.form)

    # Validate that all required form data is present
    if 'artwork_path' not in request.form or 'media_title' not in request.form or 'media_type' not in request.form or 'artwork_type' not in request.form:
        app.logger.error("Missing form data: %s", request.form)
        return "Bad Request: Missing form data", 400

    try:
        # Extract form data for artwork download
        artwork_url = request.form['artwork_path']
        media_title = request.form['media_title']
        media_type = request.form['media_type']  # Should be either 'movie' or 'tv'
        artwork_type = request.form['artwork_type']  # Should be 'poster', 'logo', or 'backdrop'
        tmdb_id = request.form.get('tmdb_id')  # Get TMDb ID if available
        directory = request.form.get('directory', '')  # Get the directory name from the original card click!

        # Log detailed information about the artwork selection
        app.logger.info(f"Artwork Path: {artwork_url}, Media Title: {media_title}, Media Type: {media_type}, Artwork Type: {artwork_type}, TMDb ID: {tmdb_id}, Directory: {directory}")

        # Select base folders based on media type (movies or TV shows)
        base_folders = movie_folders if media_type == 'movie' else tv_folders

        # Initialize variables for directory matching
        save_dir = None
        possible_dirs = []
        best_similarity = 0
        best_match_dir = None

        # FIRST: If we have the directory name from the original click, use it directly!
        if directory:
            # Find the exact directory in the base folders
            for base_folder in base_folders:
                potential_path = os.path.join(base_folder, directory)
                if os.path.exists(potential_path) and os.path.isdir(potential_path):
                    save_dir = potential_path
                    app.logger.info(f"Using directory from original click: {save_dir}")
                    # Save the TMDb ID mapping for future use
                    if tmdb_id:
                        save_mapped_directory(tmdb_id, media_type, save_dir)
                    # Save the artwork
                    local_artwork_path = save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type)
                    if local_artwork_path:
                        artwork_name = ARTWORK_TYPES[artwork_type]['name']
                        message = f"{artwork_name} for '{media_title}' has been downloaded!"
                        send_slack_notification(message, local_artwork_path, artwork_url)
                    return redirect(url_for('tv_shows' if media_type == 'tv' else 'index') + f"#{generate_clean_id(media_title)}")

        # SECOND: Check if we have a saved mapping for this TMDb ID
        if tmdb_id:
            mapped_dir = get_mapped_directory(tmdb_id, media_type)
            if mapped_dir:
                app.logger.info(f"Using previously saved directory mapping for {media_type}_{tmdb_id}: {mapped_dir}")
                save_dir = mapped_dir
                # Skip the fuzzy matching logic and go straight to saving
                local_artwork_path = save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type)
                if local_artwork_path:
                    artwork_name = ARTWORK_TYPES[artwork_type]['name']
                    message = f"{artwork_name} for '{media_title}' has been downloaded!"
                    send_slack_notification(message, local_artwork_path, artwork_url)
                return redirect(url_for('tv_shows' if media_type == 'tv' else 'index') + f"#{generate_clean_id(media_title)}")

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

                # Log the comparison for debugging
                app.logger.info(f"Comparing '{media_title}' (normalized: '{normalized_media_title}') with directory '{directory}' (normalized: '{normalized_dir_name}'). Similarity: {similarity:.3f}")

                # Update best match if current similarity is higher
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match_dir = os.path.join(base_folder, directory)
                    app.logger.info(f"New best match: '{directory}' with similarity {similarity:.3f}")

                # Check for exact match (case-insensitive and normalized)
                if normalized_media_title == normalized_dir_name:
                    save_dir = os.path.join(base_folder, directory)
                    app.logger.info(f"Exact match found: '{directory}'")
                    break

            if save_dir:
                break

        # Log final matching result
        app.logger.info(f"Best similarity: {best_similarity:.3f}, Best match dir: {best_match_dir}, Exact match dir: {save_dir}")

        # If an exact match is found, proceed with downloading
        if save_dir:
            # Save the TMDb ID mapping for future use
            if tmdb_id:
                save_mapped_directory(tmdb_id, media_type, save_dir)

            local_artwork_path = save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type)
            if local_artwork_path:
                # Send Slack notification about successful artwork download
                artwork_name = ARTWORK_TYPES[artwork_type]['name']
                message = f"{artwork_name} for '{media_title}' has been downloaded!"
                send_slack_notification(message, local_artwork_path, artwork_url)
            return redirect(url_for('tv_shows' if media_type == 'tv' else 'index') + f"#{generate_clean_id(media_title)}")

        # If no exact match, use best similarity match above a threshold
        # Increased threshold to 0.9 to prevent false matches between similar titles
        similarity_threshold = 0.9
        if best_similarity >= similarity_threshold:
            app.logger.info(f"Using best match '{best_match_dir}' (similarity: {best_similarity:.3f})")
            save_dir = best_match_dir

            # Save the TMDb ID mapping for future use
            if tmdb_id:
                save_mapped_directory(tmdb_id, media_type, save_dir)

            local_artwork_path = save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type)
            if local_artwork_path:
                # Send Slack notification about successful artwork download
                artwork_name = ARTWORK_TYPES[artwork_type]['name']
                message = f"{artwork_name} for '{media_title}' has been downloaded!"
                send_slack_notification(message, local_artwork_path, artwork_url)
            return redirect(url_for('tv_shows' if media_type == 'tv' else 'index') + f"#{generate_clean_id(media_title)}")

        # If no suitable directory found, present user with directory selection options
        similar_dirs = get_close_matches(media_title, possible_dirs, n=5, cutoff=0.5)
        return render_template('select_directory.html', similar_dirs=similar_dirs, media_title=media_title, artwork_path=artwork_url, media_type=media_type, tmdb_id=tmdb_id, artwork_type=artwork_type)

    except FileNotFoundError as fnf_error:
        # Log and handle file not found errors
        app.logger.error("File not found: %s", fnf_error)
        return "Directory not found", 404
    except Exception as e:
        # Log and handle any unexpected errors
        app.logger.exception("Unexpected error in save_artwork route: %s", e)
        return "Internal Server Error", 500
    
## Route for manually confirming the directory and saving artwork
@app.route('/confirm_artwork_directory', methods=['POST'])
def confirm_artwork_directory():
    # Extract form data for manual artwork directory selection
    selected_directory = request.form.get('selected_directory')
    media_title = request.form.get('media_title')
    artwork_url = request.form.get('artwork_path')
    content_type = request.form.get('media_type', 'movie')  # Use 'media_type' to match the form field
    artwork_type = request.form.get('artwork_type', 'poster')  # Get artwork type
    tmdb_id = request.form.get('tmdb_id')  # Get TMDb ID if available

    # Log all received form data for debugging
    app.logger.info(f"Received data: selected_directory={selected_directory}, media_title={media_title}, artwork_url={artwork_url}, content_type={content_type}, artwork_type={artwork_type}, tmdb_id={tmdb_id}")

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

    # Save the TMDb ID mapping for future use (this is the key part - remember this selection!)
    if tmdb_id:
        save_mapped_directory(tmdb_id, content_type, save_dir)
        app.logger.info(f"Saved mapping for future: {content_type}_{tmdb_id} -> {save_dir}")

    # Save the artwork and get the local path
    local_artwork_path = save_artwork_and_thumbnail(artwork_url, media_title, save_dir, artwork_type)
    if local_artwork_path:
        # Send Slack notification about successful download
        artwork_name = ARTWORK_TYPES[artwork_type]['name']
        message = f"{artwork_name} for '{media_title}' has been downloaded!"
        send_slack_notification(message, local_artwork_path, artwork_url)
        app.logger.info(f"{artwork_name} successfully saved to {local_artwork_path}")
    else:
        app.logger.error(f"Failed to save {artwork_type} for '{media_title}'")
        return f"Failed to save {artwork_type}", 500

    # Generate clean ID for navigation anchor
    anchor = generate_clean_id(media_title)

    # Determine redirect URL based on content type
    redirect_url = url_for('index') if content_type == 'movie' else url_for('tv_shows')

    # Log the redirect URL for verification
    app.logger.info(f"Redirect URL: {redirect_url}#{anchor}")

    return redirect(f"{redirect_url}#{anchor}")

# Function to send Slack notifications about backdrop downloads
def send_slack_notification(message, local_backdrop_path, backdrop_url):
    # Retrieve Slack webhook URL from environment variables
    slack_webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if slack_webhook_url:
        # Prepare Slack payload with message and backdrop details
        payload = {
            "text": message,
            "attachments": [
                {
                    "text": f"Backdrop saved to: {local_backdrop_path}",
                    "image_url": backdrop_url  # Display original TMDb backdrop in Slack
                }
            ]
        }
        try:
            # Send notification to Slack
            response = requests.post(slack_webhook_url, json=payload)
            if response.status_code == 200:
                print(f"Slack notification sent successfully for '{local_backdrop_path}'")
            else:
                print(f"Failed to send Slack notification. Status code: {response.status_code}")
        except Exception as e:
            print(f"Error sending Slack notification: {e}")
    else:
        print("Slack webhook URL not set.")

# Main entry point for running the Flask application
if __name__ == '__main__':
    # Start the app, listening on all network interfaces at port 5000
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
    )