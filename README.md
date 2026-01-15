# Ming Pao Internet Archive Backup (S3 API)

This tool archives articles from Ming Pao Canada (Toronto) directly to the Internet Archive using their S3-compatible API.

## Features
- Discovers article URLs via daily index pages.
- Uploads full HTML content to specific IA items.
- Uses the Internet Archive S3 API (`s3.us.archive.org`) for direct uploads.
- Tracks progress in a local SQLite database to avoid duplicates.

## Getting Started

Follow these steps to set up and run the archiver:

### 1. Register for an Archive.org Account
If you don't have one, create a free account at [archive.org](https://archive.org/account/signup.php).

### 2. Obtain Your IA S3 Keys
Once logged in, generate your S3-compatible access keys at:
[https://archive.org/account/s3.php](https://archive.org/account/s3.php)

Keep your **Access Key** and **Secret Key** safe.

### 3. Setup and Configure the Repository
Clone the repository and create your configuration file:

```bash
cp .env.example .env
```

Edit the `.env` file and fill in your keys:
```env
IA_ACCESS_KEY=your_access_key_here
IA_SECRET_KEY=your_secret_key_here
IA_BUCKET=your-unique-item-identifier
```

### 4. Run the Archiver

#### Option A: Using Docker (Recommended)
The easiest way to run the tool with all dependencies managed:

```bash
docker compose up --build
```

#### Option B: Using uv (Local Development)
If you have [uv](https://docs.astral.sh/uv/) installed:

```bash
uv run main.py
```

## IA S3 API Reference
The implementation follows the [Internet Archive S3 API documentation](https://archive.org/developers/ias3.html).

- Endpoint: `https://s3.us.archive.org`
- Auth: `LOW <access_key>:<secret_key>`
- Auto-bucket creation enabled via `x-archive-auto-make-bucket: 1`.

## Persistence
The `data/` directory is used to persist:
- `archive_progress.db`: SQLite database tracking uploaded URLs.
- `archive.log`: Detailed execution logs.
