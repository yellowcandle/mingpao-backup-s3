# Ming Pao Internet Archive Backup (S3 API)

This tool archives articles from Ming Pao Canada (Toronto) directly to the Internet Archive using their S3-compatible API.

## Features
- Discovers article URLs via daily index pages.
- Uploads full HTML content to specific IA items.
- Uses the Internet Archive S3 API (`s3.us.archive.org`) for direct uploads.
- Tracks progress in a local SQLite database to avoid duplicates.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables:
   Copy `.env.example` to `.env` and fill in your Internet Archive S3 keys.
   Get keys from: [https://archive.org/account/s3.php](https://archive.org/account/s3.php)

3. Run the archiver:
   ```bash
   python main.py
   ```

## Docker Usage

You can run the archiver using Docker to ensure a consistent environment:

1. Build and run with Docker Compose:
   ```bash
   docker-compose up --build
   ```

The `data/` directory is mounted to persist the SQLite database and logs between runs.
