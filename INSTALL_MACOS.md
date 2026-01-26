# Mediarr - macOS Native Installation Guide

Mediarr is now a native macOS application that runs directly on your Mac without Docker!

## Prerequisites

1. **Python 3** (macOS 10.15+ includes Python 3 by default)
2. **SMB Mount** to your NAS at `/Volumes/UNAS_Data`

## Installation Steps

### 1. Clone or Download Mediarr

```bash
git clone https://github.com/yourusername/mediarr.git
cd mediarr
```

### 2. Install Python Dependencies

```bash
python3 -m pip install --user -r requirements.txt
```

### 3. Configure API Keys

Create a `.env` file with your API keys:

```bash
cp .env.example .env
```

Edit `.env` and add your keys:

```bash
# Get your TMDb API key from: https://www.themoviedb.org/settings/api
TMDB_API_KEY=your_tmdb_api_key_here

# Optional: Slack webhook for notifications
SLACK_WEBHOOK_URL=your_slack_webhook_url_here
```

### 4. Manual Start (for testing)

```bash
./start_mediarr.sh
```

This will:
- Start Mediarr on port 5000
- Open it in your default browser
- Show a notification when ready

### 5. Manual Stop

```bash
./stop_mediarr.sh
```

### 6. Auto-Start on Login (Optional)

To have Mediarr start automatically when you log in:

```bash
# Copy the LaunchAgent to your user's LaunchAgents folder
cp com.mediarr.app.plist ~/Library/LaunchAgents/

# Load it now (it will also load on login)
launchctl load ~/Library/LaunchAgents/com.mediarr.app.plist
```

To disable auto-start:

```bash
launchctl unload ~/Library/LaunchAgents/com.mediarr.app.plist
rm ~/Library/LaunchAgents/com.mediarr.app.plist
```

## Configuration

### Default Folder Paths

Mediarr uses these paths by default:
- Movies: `/Volumes/UNAS_Data/Media/Movies`
- Kids Movies: `/Volumes/UNAS_Data/Media/Kids Movies`
- TV Shows: `/Volumes/UNAS_Data/Media/TV Shows`
- Kids TV: `/Volumes/UNAS_Data/Media/Kids TV`
- Anime: `/Volumes/UNAS_Data/Media/Anime`

### Custom Folder Paths

To use different paths, set these environment variables before starting:

```bash
export MOVIE_FOLDERS="/Volumes/UNAS_Data/Media/Movies,/Volumes/UNAS_Data/Media/Kids Movies"
export TV_FOLDERS="/Volumes/UNAS_Data/Media/TV Shows,/Volumes/UNAS_Data/Media/Kids TV"
```

## Usage

1. Open your browser to http://localhost:5000
2. Select Movies or TV Shows
3. Choose the artwork type (Posters, Logos, or Backdrops)
4. Search for missing artwork using the search buttons
5. Select and download artwork from TMDb

## Troubleshooting

### Check if Mediarr is Running

```bash
ps aux | grep "python.*app.py"
```

### View Logs

```bash
tail -f /tmp/mediarr.log
```

### SMB Mount Not Working

Make sure your NAS is mounted:

```bash
ls /Volumes/UNAS_Data
```

If not mounted, connect via Finder:
1. Cmd+K (Go → Connect to Server)
2. Enter: `smb://your-nas-ip`
3. Authenticate and mount

### Port 5000 Already in Use

Find what's using port 5000:

```bash
lsof -i :5000
```

Kill the process or change Mediarr's port in `app.py`:

```python
app.run(host="0.0.0.0", port=5001, debug=False)
```

## Advantages Over Docker

- ✅ **Direct SMB Access** - No Docker VM layer, uses macOS native SMB
- ✅ **Faster** - No virtualization overhead
- ✅ **More Reliable** - macOS handles SMB reconnects automatically
- ✅ **Simpler** - No container restarts or mount issues
- ✅ **Native Notifications** - macOS notification center integration

## Uninstall

```bash
# Stop if running
./stop_mediarr.sh

# Remove auto-start
launchctl unload ~/Library/LaunchAgents/com.mediarr.app.plist 2>/dev/null
rm ~/Library/LaunchAgents/com.mediarr.app.plist 2>/dev/null

# Remove the application folder
cd ..
rm -rf intelligent-rosalind
```

## Support

For issues or questions, check the logs at `/tmp/mediarr.log`
