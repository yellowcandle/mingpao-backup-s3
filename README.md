# Ming Pao Internet Archive Backup (S3 API)

This tool archives articles from Ming Pao Canada (Toronto) directly to the Internet Archive using their S3-compatible API (IAS3).

## Features
- **Automatic Discovery:** Discovers article URLs via daily index pages and brute-force generation
- **Direct Uploads:** Uploads full HTML content to IA using S3-compatible API
- **Monthly Organization:** Automatically creates monthly IA items (e.g., `mingpao-canada-hk-news-2025-01`)
- **Health Checks:** Verifies connectivity to IA and Ming Pao before starting
- **Post-Upload Verification:** Optional verification that files exist on IA after upload
- **Auto-Generated Index:** Creates navigable HTML index for each monthly archive
- **Progress Tracking:** SQLite database prevents duplicate uploads
- **Parallel Processing:** Configurable concurrent uploads for faster archival

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

Edit the `.env` file and fill in your configuration:
```env
# Internet Archive S3 Keys (required)
IA_ACCESS_KEY=your_access_key_here
IA_SECRET_KEY=your_secret_key_here

# IA Item Identifier Prefix (items will be named prefix-YYYY-MM)
IA_IDENTIFIER_PREFIX=mingpao-canada-hk-news

# Archive date range (YYYYMMDD format)
START_DATE=20250101
END_DATE=20250228

# Number of parallel upload threads
MAX_WORKERS=5

# Enable post-upload verification (true/false)
VERIFY_UPLOADS=false
```

**Key Configuration Options:**
- `START_DATE` / `END_DATE`: Control which dates to archive
- `MAX_WORKERS`: Increase for faster uploads (5 is conservative, 10-20 is typical)
- `VERIFY_UPLOADS`: Enable to verify each file exists on IA after upload (slower but safer)

### How it Works

**Workflow:**
1. **Health Check:** Verifies connectivity to Internet Archive S3 and Ming Pao Canada website
2. **URL Discovery:** Finds article URLs for each date via index scraping or brute-force generation
3. **Article Fetch:** Downloads HTML content from Ming Pao Canada using HTTP (SSL issues with HTTPS)
4. **Upload to IA:** Uploads to monthly IA items using S3 API with automatic bucket creation
5. **Verification (Optional):** Checks that files exist on IA using public metadata API
6. **Index Generation:** Creates navigable HTML index for each monthly archive
7. **Tracking:** Logs all uploads in SQLite to prevent duplicates

**Item Organization:**
Articles are automatically organized into monthly "items" on the Internet Archive. For example:
- `mingpao-canada-hk-news-2025-01` contains all January 2025 articles
- `mingpao-canada-hk-news-2025-02` contains all February 2025 articles

**Item Contents:**
Each monthly item includes:
- Full HTML content of each article
- Organized in date-based subdirectories (`YYYYMMDD/filename.htm`)
- Metadata: original URL, creator, language, publication date
- Auto-generated `index.html` for easy browsing
- Public assignment to `opensource` collection for discovery

**Item Limits:**
- Max 10,000 files per item (monthly items stay well under this)
- Max 100GB per item (typical HTML articles are ~90KB each)
- Monthly split prevents hitting limits

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

## Technical Details

### IA S3 API Reference
The implementation follows the [Internet Archive S3 API documentation](https://archive.org/developers/ias3.html).

- **Endpoint:** `https://s3.us.archive.org`
- **Authentication:** `LOW <access_key>:<secret_key>` header
- **Auto-bucket creation:** Enabled via `x-archive-auto-make-bucket: 1` header
- **Metadata:** Custom `x-archive-meta-*` headers for IA metadata

### URLs and Permalinks
Always use these permanent archival URLs to access items:
- **Item Details Page:** `https://archive.org/details/<identifier>`
- **Download Directory:** `https://archive.org/download/<identifier>`
- **Specific File:** `https://archive.org/download/<identifier>/<filename>`

Example:
- Item: `https://archive.org/details/mingpao-canada-hk-news-2025-01`
- Index: `https://archive.org/download/mingpao-canada-hk-news-2025-01/index.html`
- Article: `https://archive.org/download/mingpao-canada-hk-news-2025-01/20250101/HK-gaa1_r.htm`

⚠️ **DO NOT link to numbered machine URLs** (e.g., `https://ia601704.us.archive.org/...`). These are temporary server references that break over time.

### HTTP vs HTTPS
Ming Pao Canada's HTTPS configuration has SSL certificate issues, so the tool uses HTTP (`http://www.mingpaocanada.com`) for fetching articles. This is safe for publicly available news content.

## Accessing the Archives

Once articles are uploaded, they're publicly available on Internet Archive:

**Browse the Archive:**
- Visit: https://archive.org/details/mingpao-canada-hk-news-2025-01
- Browse by date and article code
- Click any article to download the HTML

**Search Across All Collections:**
- Search for "Ming Pao Canada" on https://archive.org/search.php?query=Ming+Pao+Canada
- Filter by dates, languages, and more

**Use the Auto-Generated Index:**
- Each monthly item has an `index.html` file with clickable links to all articles
- View at: https://archive.org/download/mingpao-canada-hk-news-2025-01/index.html

## Data Persistence

The `data/` directory persists:
- **`archive_progress.db`:** SQLite database tracking all uploaded URLs (prevents duplicates)
- **`archive.log`:** Detailed execution logs with timestamps and status messages

Delete these to reset progress (useful for re-archiving the same dates).
