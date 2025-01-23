# Base image with Python (multi-architecture support is native here)
FROM python:3.12-slim

# Install system dependencies required by Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements first to leverage Docker's caching mechanism for dependencies
COPY requirements.txt /app/

# Install the required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . /app

# Expose the port that Flask runs on
EXPOSE 5000

# Define the command to run the Flask app
CMD ["python", "app.py"]
