## Backgroundarr

**Backgroundarr** is a Flask application designed to organize, manage, and download high-quality **backdrops** for movies and TV shows. It is tailored for users who maintain local media libraries, providing an intuitive interface to search for backdrops, select them, and integrate them seamlessly with your media collection.

This was built to help manage library local media assets in advance of [Plex releasing their next version of their app](https://www.plex.tv/blog/new-year-same-mission/) which from my testing highlights backdrop images **A LOT** more when viewing specific movie details vs the current version that showed more of the poster. Please see examples below. 

**Examples of Old versus New App views**

21 Jump Street
![Old 21 Jump Street View](https://github.com/user-attachments/assets/fc2e8638-5460-40dc-97ea-853db293f554)

![New 21 Jump Street View](https://github.com/user-attachments/assets/4d399008-5053-4146-a2b2-459a27eb7aa1)

13th Warrior
![Old 13th Warrior](https://github.com/user-attachments/assets/b624c792-f9b8-42b5-a345-851a221cd347)

![New 13th Warrior](https://github.com/user-attachments/assets/1cd9e827-4dc8-454f-991d-2968b38b801d)

**_PROTIP_**

When selecting artwork, I HIGHLY recommend choosing one that moves the characters or main focus to the right side of the image AND that has no text. See Good and Bad Examples below: 

**Good**
No Text, character is clearly visible
![No Text, character is clearly visible](https://github.com/user-attachments/assets/5cb0279a-6f84-4b74-9a4d-3fd785c0c267)

**Bad (IMO)**
Text is obscured by movie details rendered in app, making it hard to read.
![Text is obscured by movie details rendered in app, making it hard to read.](https://github.com/user-attachments/assets/0b20dd02-7e6b-4843-8be6-241c08f5599a)

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
      - /path/to/your/movies:/movies
      - /path/to/your/tv:/tv
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
```

## Screenshots

This is the main view
![Main View](https://github.com/user-attachments/assets/2a547a36-6dd1-4398-8807-852fa62d7bbb)

This is the movie search results. Make sure to reference the year under each movie to ensure you are selecting the right one
![image](https://github.com/user-attachments/assets/5132d236-fb05-40ec-9153-d3ed19595f9a)

Here is what the search results will display. 
![image](https://github.com/user-attachments/assets/a54b40d3-23ab-4b09-9c0b-a792ebfd24e5)

This is what the Slack Notification will look like
![image](https://github.com/user-attachments/assets/ec7ae342-ddb4-4eb2-9c71-ae25117bd319)

Here you can see how it shows up in thre File Structure. (The backdrop-thumb.ext is designed to reduce loadtime of the WebUI) 
![image](https://github.com/user-attachments/assets/df6fbad9-7cf6-4fdf-b25a-290e575602e9)


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
