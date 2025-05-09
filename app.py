import os
import requests
import re
import urllib.parse
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from difflib import get_close_matches, SequenceMatcher  # For string similarity
from PIL import Image  # For image processing
from datetime import datetime  # For handling dates and times
from urllib.parse import unquote

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

# Define base folders for organizing movies and TV shows from environment variables
movie_folders = os.getenv("MOVIE_FOLDERS").split(',')
tv_folders = os.getenv("TV_FOLDERS").split(',')

# Raise an error if these variables are not set
if not movie_folders or not tv_folders:
    raise ValueError("MOVIE_FOLDERS and TV_FOLDERS must be set in the environment variables.")

# Function to strip out everything after the title
def normalize_title(title):
    # Remove patterns like "(year)" or "{tmdb-xxxxx}" from the title
    return re.sub(r'\s*\(.*?\)|\s*\{.*?\}', '', title).strip()

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

# Function to calculate backdrop resolution for sorting
def backdrop_resolution(backdrop):
    return backdrop['width'] * backdrop['height']  # Calculate the area of the backdrop

# Function to handle backdrop download and thumbnail creation
def save_backdrop_and_thumbnail(backdrop_url, media_title, save_dir):
    # Define full paths for the backdrop and thumbnail
    full_backdrop_path = os.path.join(save_dir, 'backdrop.jpg')
    thumb_backdrop_path = os.path.join(save_dir, 'backdrop-thumb.jpg')

    try:
        # Remove any existing backdrop files in the directory
        for ext in ['jpg', 'jpeg', 'png']:
            existing_backdrop = os.path.join(save_dir, f'backdrop.{ext}')
            existing_thumb = os.path.join(save_dir, f'backdrop-thumb.{ext}')
            if os.path.exists(existing_backdrop):
                os.remove(existing_backdrop)
            if os.path.exists(existing_thumb):
                os.remove(existing_thumb)

        # Download the full-resolution backdrop from the URL
        response = requests.get(backdrop_url)
        if response.status_code == 200:
            # Save the downloaded backdrop image
            with open(full_backdrop_path, 'wb') as file:
                file.write(response.content)

            # Create a thumbnail using Pillow image processing library
            with Image.open(full_backdrop_path) as img:
                # Calculate aspect ratio to maintain consistent thumbnail dimensions
                aspect_ratio = img.width / img.height
                target_ratio = 16 / 9  # Desired backdrop ratio

                # Crop the image to match the target aspect ratio
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

                # Resize the image to 300x169 pixels with high-quality Lanczos resampling
                img = img.resize((300, 169), Image.LANCZOS)

                # Save the thumbnail image with high JPEG quality
                img.save(thumb_backdrop_path, "JPEG", quality=90)

            print(f"Backdrop and thumbnail saved successfully for '{media_title}'")
            return full_backdrop_path  # Return the local path where the backdrop was saved
        else:
            print(f"Failed to download backdrop for '{media_title}'. Status code: {response.status_code}")
            return None

    except Exception as e:
        print(f"Error saving backdrop and generating thumbnail for '{media_title}': {e}")
        return None

# Function to retrieve media directories and their associated backdrop thumbnails
def get_backdrop_thumbnails(base_folders=None):
    # Default to movie folders if no folders specified
    if base_folders is None:
        base_folders = movie_folders
    media_list = []

    # Iterate through specified base folders to find media with backdrops
    for base_folder in base_folders:
        for media_dir in sorted(os.listdir(base_folder)):
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

# Route for the main index page showing movie backdrops
@app.route('/')
def index():
    movies, total_movies = get_backdrop_thumbnails(movie_folders)
    
    # Render the index page with movie thumbnails and total count
    return render_template('index.html', movies=movies, total_movies=total_movies)

# Route for TV shows page
@app.route('/tv')
def tv_shows():
    tv_shows, total_tv_shows = get_backdrop_thumbnails(tv_folders)

    # Log TV shows data for debugging
    app.logger.info(f"Fetched TV shows: {tv_shows}")

    return render_template('tv.html', tv_shows=tv_shows, total_tv_shows=total_tv_shows)

# Route to trigger a manual refresh of media directories
@app.route('/refresh')
def refresh():
    get_backdrop_thumbnails()  # Re-scan the directories
    return redirect(url_for('index'))

@app.route('/search_movie', methods=['GET'])
def search_movie():
    query = request.args.get('query', '')
    folder_name = request.args.get('folder_name', query)  # Preserve original folder name
    
    # Use clean query for TMDb search but keep original folder name
    clean_query = normalize_title(query)
    
    response = requests.get(f"{BASE_URL}/search/movie", 
                          params={"api_key": TMDB_API_KEY, "query": clean_query})
    
    if response.status_code == 200:
        results = response.json().get('results', [])
    else:
        app.logger.error(f"TMDb API error: {response.status_code}")
        results = []

    for result in results:
        result['clean_id'] = generate_clean_id(result['title'])
        result['backdrop_url'] = f"{BACKDROP_BASE_URL}{result.get('backdrop_path')}" if result.get('backdrop_path') else None

    return render_template('search_results.html', 
                         query=clean_query,
                         folder_name=folder_name,  # Pass folder_name to template
                         results=results)

# Route for searching TV shows using TMDb API
@app.route('/search_tv', methods=['GET'])
def search_tv():
    # Get query and folder_name from the request
    query = request.args.get('query', '')
    folder_name = request.args.get('folder_name', query)  # Preserve folder name if passed

    # Normalize the query for TMDb search
    clean_query = normalize_title(query)

    app.logger.info(f"Searching TV with query: {clean_query}, folder_name: {folder_name}")

    # Perform the TMDb API search
    response = requests.get(f"{BASE_URL}/search/tv", params={"api_key": TMDB_API_KEY, "query": clean_query})
    results = response.json().get('results', []) if response.status_code == 200 else []

    # Format results for rendering
    for result in results:
        result['clean_id'] = generate_clean_id(result['name'])
        result['backdrop_url'] = f"{BACKDROP_BASE_URL}{result.get('backdrop_path')}" if result.get('backdrop_path') else None

    return render_template(
        'search_results.html',
        query=clean_query,
        folder_name=folder_name,  # Pass folder name for downstream processing
        results=results,
        content_type="tv"
    )
    
# Route for selecting a movie and displaying available backdrops
@app.route('/select_movie/<int:movie_id>', methods=['GET'])
def select_movie(movie_id):
    folder_name = request.args.get('folder_name')  # Get original folder name
    app.logger.info(f"Select movie received folder_name: {folder_name}")
    
    movie_details = requests.get(f"{BASE_URL}/movie/{movie_id}", 
                               params={"api_key": TMDB_API_KEY}).json()
    
    backdrops = requests.get(f"{BASE_URL}/movie/{movie_id}/images", 
                           params={"api_key": TMDB_API_KEY}).json().get('backdrops', [])
    backdrops_sorted = sorted(backdrops, key=backdrop_resolution, reverse=True)

    formatted_backdrops = [{
        'url': f"{BACKDROP_BASE_URL}{backdrop['file_path']}",
        'size': f"{backdrop['width']}x{backdrop['height']}"
    } for backdrop in backdrops_sorted]

    return render_template(
        'backdrop_selection.html',
        media_title=movie_details.get('title'),
        content_type='movie',
        backdrops=formatted_backdrops,
        folder_name=folder_name  # Pass original folder name
    )

# Route for selecting a TV show and displaying available backdrops
@app.route('/select_tv/<int:tv_id>', methods=['GET'])
def select_tv(tv_id):
    # Fetch detailed information about the selected TV show from TMDb API
    tv_details = requests.get(f"{BASE_URL}/tv/{tv_id}", params={"api_key": TMDB_API_KEY}).json()

    # Extract TV show title
    tv_title = tv_details.get('name', '')
    folder_name = request.args.get('folder_name', tv_title)  # Use provided folder_name or default to title

    # Log folder name for debugging
    app.logger.info(f"Select TV received folder_name: {folder_name}")

    # Request available backdrops for the selected TV show
    backdrops = requests.get(f"{BASE_URL}/tv/{tv_id}/images", params={"api_key": TMDB_API_KEY}).json().get('backdrops', [])
    backdrops_sorted = sorted(backdrops, key=backdrop_resolution, reverse=True)

    formatted_backdrops = [{
        'url': f"{BACKDROP_BASE_URL}{backdrop['file_path']}",
        'size': f"{backdrop['width']}x{backdrop['height']}"
    } for backdrop in backdrops_sorted]

    return render_template(
        'backdrop_selection.html',
        media_title=tv_title,
        content_type='tv',
        backdrops=formatted_backdrops,
        folder_name=folder_name  # Pass original folder name for downstream processing
    )

# Function to handle backdrop download and thumbnail creation
def save_backdrop_and_thumbnail(backdrop_url, media_title, save_dir):
    # Define full paths for the backdrop and thumbnail
    full_backdrop_path = os.path.join(save_dir, 'backdrop.jpg')
    thumb_backdrop_path = os.path.join(save_dir, 'backdrop-thumb.jpg')

    try:
        # Remove any existing backdrop files in the directory
        for ext in ['jpg', 'jpeg', 'png']:
            existing_backdrop = os.path.join(save_dir, f'backdrop.{ext}')
            existing_thumb = os.path.join(save_dir, f'backdrop-thumb.{ext}')
            if os.path.exists(existing_backdrop):
                os.remove(existing_backdrop)
            if os.path.exists(existing_thumb):
                os.remove(existing_thumb)

        # Download the full-resolution backdrop from the URL
        response = requests.get(backdrop_url)
        if response.status_code == 200:
            # Save the downloaded backdrop image
            with open(full_backdrop_path, 'wb') as file:
                file.write(response.content)

            # Create a thumbnail using Pillow image processing library
            with Image.open(full_backdrop_path) as img:
                # Calculate aspect ratio to maintain consistent thumbnail dimensions
                aspect_ratio = img.width / img.height
                target_ratio = 16 / 9  # Desired backdrop ratio

                # Crop the image to match the target aspect ratio
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

                # Resize the image to 300x169 pixels with high-quality Lanczos resampling
                img = img.resize((300, 169), Image.LANCZOS)

                # Save the thumbnail image with high JPEG quality
                img.save(thumb_backdrop_path, "JPEG", quality=90)

            print(f"Backdrop and thumbnail saved successfully for '{media_title}'")
            return full_backdrop_path  # Return the local path where the backdrop was saved
        else:
            print(f"Failed to download backdrop for '{media_title}'. Status code: {response.status_code}")
            return None

    except Exception as e:
        print(f"Error saving backdrop and generating thumbnail for '{media_title}': {e}")
        return None
    
    # Route for serving backdrops from the file system
@app.route('/backdrop/<path:filename>')
def serve_backdrop(filename):
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
            # Serve the file from the appropriate directory
            response = send_from_directory(base_folder, filename)
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
@app.route('/select_backdrop', methods=['POST'])
def select_backdrop():
    try:
        # Extract form data
        backdrop_url = request.form['backdrop_path']
        media_title = request.form['media_title']
        media_type = request.form['media_type']
        folder_name = request.form.get('folder_name', media_title)  # Use provided folder name

        app.logger.info(f"Select backdrop received folder_name: {folder_name}")

        # Determine base folders based on media type
        base_folders = movie_folders if media_type == 'movie' else tv_folders

        # Locate the exact directory based on folder_name
        save_dir = None
        for base_folder in base_folders:
            possible_dir = os.path.join(base_folder, folder_name)
            if os.path.exists(possible_dir):
                save_dir = possible_dir
                break

        if not save_dir:
            app.logger.error(f"Directory not found for folder name: {folder_name}")
            return f"Directory not found: {folder_name}", 404

        # Save the backdrop and create a thumbnail
        local_backdrop_path = save_backdrop_and_thumbnail(backdrop_url, folder_name, save_dir)
        if local_backdrop_path:
            message = f"Backdrop for '{folder_name}' has been downloaded!"
            send_slack_notification(message, local_backdrop_path, backdrop_url)

        # Redirect back to the appropriate page with the anchor for the folder
        return redirect(url_for('tv_shows' if media_type == 'tv' else 'index') + f"#{generate_clean_id(folder_name)}")

    except Exception as e:
        app.logger.exception(f"Error in select_backdrop: {e}")
        return f"Error: {str(e)}", 500
    
## Route for manually confirming the directory and saving the backdrop
@app.route('/confirm_backdrop_directory', methods=['POST'])
def confirm_backdrop_directory():
    # Extract form data for manual backdrop directory selection
    selected_directory = request.form.get('selected_directory')
    media_title = request.form.get('media_title')
    backdrop_url = request.form.get('backdrop_path')
    content_type = request.form.get('content_type', 'movie')  # Default to 'movie'

    # Log all received form data for debugging
    app.logger.info(f"Received data: selected_directory={selected_directory}, media_title={media_title}, backdrop_url={backdrop_url}, content_type={content_type}")

    # Validate form data
    if not selected_directory or not media_title or not backdrop_url:
        app.logger.error("Missing form data: selected_directory=%s, media_title=%s, backdrop_url=%s",
                         selected_directory, media_title, backdrop_url)
        return "Bad Request: Missing form data", 400

    # Find the correct base folder for the selected directory
    save_dir = None
    base_folders = movie_folders if content_type == 'movie' else tv_folders

    for base_folder in base_folders:
        if selected_directory in os.listdir(base_folder):
            save_dir = os.path.join(base_folder, selected_directory)
            break

    if not save_dir:
        # Log an error if directory not found
        app.logger.error(f"Selected directory '{selected_directory}' not found in base folders.")
        return "Directory not found", 404

    # Save the backdrop and get the local path
    local_backdrop_path = save_backdrop_and_thumbnail(backdrop_url, media_title, save_dir)
    if local_backdrop_path:
        # Send Slack notification about successful download
        message = f"Backdrop for '{media_title}' has been downloaded!"
        send_slack_notification(message, local_backdrop_path, backdrop_url)
        app.logger.info(f"Backdrop successfully saved to {local_backdrop_path}")
    else:
        app.logger.error(f"Failed to save backdrop for '{media_title}'")
        return "Failed to save backdrop", 500

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
    app.run(host='0.0.0.0', port=5000)