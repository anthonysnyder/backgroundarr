## Backgroundarr

**Backgroundarr** is a Flask application designed to organize, manage, and download high-quality **backdrops** for movies and TV shows. It is tailored for users who maintain local media libraries, providing an intuitive interface to search for backdrops, select them, and integrate them seamlessly with your media collection.

### Key Features

- **Effortless Media Management**: Displays movies and TV shows from user-specified directories, showing available backdrops or placeholders for missing ones.
- **High-Quality Backdrops**: Fetches backdrops directly from TMDb (The Movie Database) for movies and TV shows.
- **Advanced Search**: Search for media titles using TMDb's API and filter results.
- **Thumbnail Previews**: Generates optimized thumbnail previews for faster loading.
- **Slack Notifications**: Sends notifications to a configured Slack channel upon successful backdrop downloads.
- **Customizable Directories**: Supports multiple directories for movies and TV shows, making it flexible for various setups.
- **Anchor Navigation**: Automatically scrolls back to the selected media after a backdrop is downloaded.

### Requirements

To run Backgroundarr, ensure you have the following:

- Python 3.12+
- Flask
- TMDb API Key
- Docker (optional, for containerized deployment)

### Installation

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/anthonysnyder/backgroundarr.git
   cd backgroundarr
   ```

## 2. Setup Docker Compose:
Create a docker-compose.yml file in the root directory of the project:
Note: Make sure to replace placeholders with your actual data/paths to files.

```
services:
  postarr:
    image: swguru2004/backgroundarr:latest
    container_name: backgroundarr
    ports:
      - "1596:5000"
    environment:
      - TMDB_API_KEY=your_tmdb_api_key_here
      - PUID=your_puid_here
      - PGID=your_pgid_here
      - SLACK_WEBHOOK_URL=your_slack_webhook_url_here
    volumes:
      - /path/to/movies:/movies
      - /path/to/kids-movies:/kids-movies
      - /path/to/tv:/tv
      - /path/to/kids-tv:/kids-tv
    networks:
      - bridge_network

networks:
  bridge_network:
    driver: bridge
```
## 3.	Start the Application:
```
docker-compose up -d
```
##	4.	Access the Application:
Open your browser and go to http://localhost:5000 or your NAS IP to start using Postarr.

## Slack Integration (Optional)

To enable Slack notifications, add your Slack Webhook URL in the SLACK_WEBHOOK_URL environment variable in the docker-compose.yml file.
```
environment:
  - SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX
### Screenshots
*Screenshots will be added here.*

### File Structure

```plaintext
backgroundarr/
├── app.py                  # Main Flask application
├── templates/              # HTML templates
├── static/                 # Static files (CSS, JS, etc.)
├── requirements.txt        # Python dependencies
├── Dockerfile              # Docker configuration
└── README.md               # Documentation
```


### Contributions

Contributions are welcome! Please submit pull requests or create issues to report bugs and suggest features.

### License

This project is licensed under the MIT License. See the `LICENSE` file for details.
