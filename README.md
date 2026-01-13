# Mediarr

**Mediarr** is a unified Flask application designed to organize, manage, and download high-quality **posters**, **logos**, and **backdrops** for movies and TV shows. It provides an intuitive interface to manage all your media artwork in one place, with intelligent tracking of what's available, what's missing, and what's unavailable on TMDb.

Originally built as "Backgroundarr" for managing backdrops in advance of [Plex releasing their next version](https://www.plex.tv/blog/new-year-same-mission/) which highlights backdrop images more prominently, Mediarr has evolved into a comprehensive artwork management solution.

## 🎨 Key Features

- **Unified Artwork Management**: Handle posters, logos, and backdrops in a single interface
- **Three-State Status Tracking**:
  - 🟢 **Green**: Artwork found and saved
  - 🟡 **Yellow**: Artwork missing (click to mark as unavailable)
  - 🔴 **Red**: Artwork unavailable on TMDb
- **Smart Unavailability Tracking**: Persist artwork availability across sessions
- **Progress Bars**: Visual completion percentage for each artwork type
- **Advanced Filtering**: Filter by missing artwork and minimum dimensions
- **Click-to-Download**: Select artwork and download immediately without confirmation
- **Quality Indicators**: See at a glance if artwork is high, medium, or low quality
- **Language Filtering**: Filter posters by language when selecting
- **SMB/NAS Safe**: Optimized for network mounts with retry logic
- **Slack Notifications**: Get notified when artwork is downloaded
- **Auto-Generated Thumbnails**: Fast-loading preview images

## 📸 Screenshots

### Main Collection View
![Collection view showing all three artwork types per movie with color-coded status indicators]

### Artwork Selection
![Grid of artwork options with quality badges, language tags, and filtering options]

### Three-State Status System
- **Green indicators**: Artwork is already downloaded
- **Yellow indicators**: Artwork is missing - click to search or mark unavailable
- **Red indicators**: Artwork has been marked as unavailable on TMDb

## 🚀 Quick Start with Docker

### 1. Create docker-compose.yml

```yaml
version: '3.8'

services:
  mediarr:
    image: swguru2004/mediarr:latest
    container_name: mediarr
    ports:
      - "5000:5000"
    environment:
      - TMDB_API_KEY=your_tmdb_api_key_here
      - MOVIE_FOLDERS=/movies
      - TV_FOLDERS=/tv
      - SLACK_WEBHOOK_URL=  # Optional
    volumes:
      # Mount your media directories
      - /path/to/your/movies:/movies
      - /path/to/your/tv:/tv
      # Persistent storage for mappings and unavailability data
      - ./mediarr-data:/app
    restart: unless-stopped
```

### 2. Create .env file

```bash
TMDB_API_KEY=your_tmdb_api_key_here
MOVIE_FOLDERS=/movies,/movies2
TV_FOLDERS=/tv,/tv2
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### 3. Start the application

```bash
docker-compose up -d
```

### 4. Access the interface

Open your browser to `http://localhost:5000`

## 📋 Requirements

- **TMDb API Key**: [Get one here](https://www.themoviedb.org/settings/api) (free)
- **Media Library**: Movies/TV shows organized in directories
- **Docker** (recommended) or Python 3.12+

## 🎯 How It Works

### Artwork Status Indicators

Each media item shows three emoji indicators:
- 🎭 **Poster** status
- 🏷️ **Logo** status
- 🎬 **Backdrop** status

### Workflow

1. **Scan your library**: Mediarr automatically detects existing artwork
2. **See what's missing**: Yellow indicators show missing artwork
3. **Search and download**: Click search buttons to find and download artwork
4. **Mark unavailable**: Click yellow indicators to mark artwork as unavailable if TMDb doesn't have it
5. **Track progress**: Progress bars show completion percentage for each type

### File Structure in Your Media Folders

Mediarr creates the following files in each media directory:

```
Movie Name (2014) {tmdb-12345}/
├── poster.jpg          # Full poster image
├── poster-thumb.jpg    # Thumbnail (300x450)
├── logo.png            # Full logo (transparent PNG)
├── logo-thumb.png      # Logo thumbnail (300x150)
├── backdrop.jpg        # Full backdrop image
└── backdrop-thumb.jpg  # Backdrop thumbnail (300x169)
```

## 🔧 Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TMDB_API_KEY` | Yes | - | Your TMDb API key |
| `MOVIE_FOLDERS` | Yes | - | Comma-separated movie directory paths |
| `TV_FOLDERS` | Yes | - | Comma-separated TV directory paths |
| `SLACK_WEBHOOK_URL` | No | - | Slack webhook for notifications |

### Persistent Data Files

Mediarr creates these files in the app directory:
- `artwork_unavailable.json` - Tracks which artwork is unavailable on TMDb
- `directory_mapping.json` - Maps TMDb IDs to local directories

**Important**: Mount these files as volumes to persist data across container restarts.

## 💡 Pro Tips

### Selecting Good Artwork

When selecting artwork, especially backdrops for Plex:

**✅ Good Choices:**
- No text overlays (movie details will cover them)
- Main subject positioned on the right side
- High resolution (2000px+ width)
- No language-specific text for international compatibility

**❌ Avoid:**
- Text that will be obscured by UI elements
- Low resolution images (<1000px)
- Centered composition (gets covered by metadata)

### Using the Unavailability Feature

If TMDb doesn't have a particular artwork type:
1. Search for the artwork to confirm it's not available
2. Click the yellow indicator for that artwork type
3. It turns red and won't show in "Show Missing" filter anymore
4. The status persists across sessions

## 🛠️ Building from Source

```bash
# Clone the repository
git clone https://github.com/anthonysnyder/backgroundarr.git
cd backgroundarr

# Build the Docker image
docker build -t mediarr .

# Or run locally with Python
pip install -r requirements.txt
python app.py
```

## 📁 Project Structure

```
mediarr/
├── app.py                      # Main Flask application
├── templates/
│   ├── collection.html         # Main unified collection view
│   ├── artwork_selection.html  # Artwork selection grid
│   └── search_results.html     # TMDb search results
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker build configuration
├── docker-compose.yml          # Docker Compose setup
└── README.md                   # This file
```

## 🔄 Migration from Backgroundarr

If you're upgrading from Backgroundarr:

1. Your existing backdrop files are **fully compatible**
2. Mediarr will detect and display them automatically
3. You can now add posters and logos to the same folders
4. All your backdrop-thumb files will continue to work

No migration needed - it's a drop-in replacement!

## 🐛 Troubleshooting

### SMB/NAS Mount Issues

Mediarr includes retry logic for SMB mounts. If you see `BlockingIOError`, the app will automatically retry with exponential backoff.

### Artwork Not Showing

1. Check that TMDb ID is in directory name: `Movie (2014) {tmdb-12345}`
2. Verify artwork files exist: `poster.jpg`, `logo.png`, `backdrop.jpg`
3. Check file permissions (should be readable by container user)

### Progress Bars Not Updating

Progress bars update on page refresh. After downloading artwork, refresh the page to see updated statistics.

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## 🙏 Acknowledgments

- **TMDb** for providing the excellent free API
- **Plex** for inspiring this project
- All contributors and users who provide feedback

---

**Note**: This application requires a free TMDb API key. Mediarr is not affiliated with or endorsed by TMDb or Plex.
