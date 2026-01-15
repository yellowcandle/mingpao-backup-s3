import os
import time
import logging
import requests
import re
import random
from datetime import datetime, timedelta
from typing import Dict, Optional
from dotenv import load_dotenv
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.logging import RichHandler
from bs4 import BeautifulSoup
from ia_s3_client import IAS3Client
from url_generator import MingPaoUrlGenerator
from database import ArchiveDB

# Rich console for pretty output
console = Console()

def extract_article_title(content: bytes) -> Optional[str]:
    """Extract the article title from HTML content."""
    try:
        soup = BeautifulSoup(content, 'html.parser')
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            # Clean up the title
            title = title_tag.string.strip()
            # Remove common prefixes like "Ming Pao - " if present
            if ' - ' in title:
                parts = title.split(' - ')
                # Return the main part, usually the article title
                return parts[0].strip() if parts else title
            return title
        return None
    except Exception as e:
        logger.warning(f"Failed to extract title from content: {e}")
        return None

# Configure root logger to use Rich
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[RichHandler(console=console, rich_tracebacks=True, show_time=False, show_path=False)],
    force=True,
)

# Get module logger
logger = logging.getLogger("mingpao_ia_backup")

def archive_article(url: str, ia_client: IAS3Client, bucket: str, db: ArchiveDB, 
                   max_retries: int = 3, verify_upload: bool = False):
    """Fetch article and upload to IA with retry logic and optional verification."""
    if db.is_archived(url):
        return True

    # Generate a safe key for IA
    match = re.search(r'News/(\d{8}/HK-[^/]+_r\.htm)', url)
    if match:
        key = match.group(1)
    else:
        key = "/".join(url.split("/")[-2:])

    # Convert HTTPS to HTTP to avoid SSL issues
    http_url = url.replace("https://", "http://")
    
    content = None
    for attempt in range(max_retries + 1):
        try:
            # Disable redirects - Ming Pao redirects missing articles to errorpage.html
            response = requests.get(http_url, timeout=30, allow_redirects=False, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            if response.status_code == 200:
                content = response.content
                break
            elif response.status_code == 404:
                return False
            elif response.status_code in (301, 302, 303, 307, 308):
                # Redirect likely means article doesn't exist
                return False
            else:
                logger.warning(f"Attempt {attempt+1} failed for {http_url}: HTTP {response.status_code}")
        except (requests.exceptions.RequestException, Exception) as e:
            if attempt < max_retries:
                wait_time = (2 ** attempt) + random.random()
                logger.warning(f"Attempt {attempt+1} failed for {http_url}: {e}. Retrying in {wait_time:.2f}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed to fetch {http_url} after {max_retries+1} attempts: {e}")
                return False

    if not content:
        return False

    try:
        # Extract title from content
        title = extract_article_title(content)
        
        # IA Metadata
        metadata = {
            "mediatype": "texts",
            "originalurl": url,
            "subject": "Ming Pao Canada; Archive; News; Hong Kong",
            "date": key.split('/')[0] if '/' in key else datetime.now().strftime("%Y%m%d"),
            "title": title if title else f"Article {key}"
        }
        
        success = ia_client.upload_file(bucket, key, content, metadata=metadata)
        if success:
            # Optionally verify the upload on IA
            if verify_upload:
                if not ia_client.verify_file_uploaded(bucket, key):
                    logger.warning(f"Upload succeeded but verification failed for {key}")
                    return False
            
            # Update per-file metadata with article title
            if title:
                ia_client.update_file_metadata(bucket, key, title)
            
            db.record_upload(url, bucket, key, title)
            return True
    except Exception as e:
        logger.error(f"Error uploading {url} to IA: {e}")
        return False

def generate_index_html(bucket_id: str, articles: Dict[str, list], titles: Optional[Dict[str, str]] = None) -> str:
    """
    Generate an HTML index file linking to all archived articles.
    
    Args:
        bucket_id: The IA item identifier (e.g., mingpao-canada-hk-news-2025-01)
        articles: Dict of date -> [filenames]
        titles: Dict of filename -> article title
    """
    if titles is None:
        titles = {}
    html_parts = [
        '<!DOCTYPE html>',
        '<html lang="zh-HK">',
        '<head>',
        '    <meta charset="UTF-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f'    <title>Ming Pao Canada Archive - {bucket_id}</title>',
        '    <style>',
        '        body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }',
        '        h1 { color: #333; }',
        '        .date-section { margin-bottom: 30px; }',
        '        .date-section h2 { background: #f0f0f0; padding: 10px; border-left: 4px solid #d32f2f; }',
        '        .article-list { list-style: none; padding-left: 0; }',
        '        .article-list li { padding: 8px 0; border-bottom: 1px solid #eee; }',
        '        .article-list a { color: #0066cc; text-decoration: none; }',
        '        .article-list a:hover { text-decoration: underline; }',
        '        .article-date { color: #666; font-size: 0.9em; }',
        '    </style>',
        '</head>',
        '<body>',
        f'    <h1>Ming Pao Canada Archive: {bucket_id}</h1>',
        '    <p>Hong Kong news and international news archived from Ming Pao Canada (Toronto Edition)</p>',
    ]
    
    for date in sorted(articles.keys()):
        html_parts.append('    <div class="date-section">')
        html_parts.append(f'        <h2>{date}</h2>')
        html_parts.append('        <ul class="article-list">')

        for filename in sorted(articles[date]):
            # Format: 20250101/HK-gaa1_r.htm
            article_title = titles.get(filename, "")
            safe_name = filename.split('/')[-1].replace('_r.htm', '').upper()
            display_name = article_title if article_title else safe_name
            html_parts.append(
                f'            <li><a href="{filename}" target="_blank">{display_name}</a> '
                f'<span class="article-date">({safe_name})</span></li>'
            )

        html_parts.append('        </ul>')
        html_parts.append('    </div>')
    
    html_parts.extend([
        '    <hr>',
        '    <footer>',
        '        <p>Archive Date: ' + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '</p>',
        '        <p>Archived by Ming Pao Backup Tool | Source: <a href="http://www.mingpaocanada.com">Ming Pao Canada</a></p>',
        '    </footer>',
        '</body>',
        '</html>'
    ])
    
    return '\n'.join(html_parts)

def health_check(ia_client: IAS3Client) -> bool:
    """
    Perform health checks before starting the backup:
    1. Test connectivity to Internet Archive
    2. Test Ming Pao Canada website
    3. Verify IA credentials
    """
    logger.info("Running health checks...")
    
    # Check IA connectivity and credentials
    try:
        if not ia_client.bucket_exists("test-mingpao-backup"):
            logger.warning("Could not verify existing bucket, but IA S3 endpoint is reachable")
        logger.info("✓ Internet Archive S3 connection OK")
    except Exception as e:
        logger.error(f"✗ Internet Archive connection failed: {e}")
        return False
    
    # Check Ming Pao website connectivity
    try:
        # Test a specific known recent article to avoid redirects
        test_url = "http://www.mingpaocanada.com/tor/htm/News/20250101/HK-gaa1_r.htm"
        response = requests.head(test_url, timeout=10, allow_redirects=False)
        
        # Ming Pao redirects missing articles to errorpage.html (HTTP 302)
        # This is expected behavior for some articles
        if response.status_code in [200, 302, 404]:
            logger.info("✓ Ming Pao Canada website is reachable")
            return True
        elif response.status_code < 500:
            logger.info("✓ Ming Pao Canada website is reachable")
            return True
        else:
            logger.warning(f"✗ Ming Pao Canada returned status {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"✗ Ming Pao Canada website unreachable: {e}")
        return False
    
    logger.info("All health checks passed!")
    return True

def main():
    # Clear env vars set by Dockerfile so .env can override them
    for key in ['START_DATE', 'END_DATE']:
        os.environ.pop(key, None)
    load_dotenv()  # Load from .env file
    
    access_key = os.getenv("IA_ACCESS_KEY")
    secret_key = os.getenv("IA_SECRET_KEY")
    prefix = os.getenv("IA_IDENTIFIER_PREFIX", "mingpao-canada-hk-news")

    if not access_key or not secret_key:
        logger.error("IA_ACCESS_KEY and IA_SECRET_KEY must be set in .env file")
        return

    ia_client = IAS3Client(access_key, secret_key)
    
    # Run health checks
    if not health_check(ia_client):
        logger.error("Health checks failed. Aborting backup.")
        return

    url_gen = MingPaoUrlGenerator()
    db = ArchiveDB()
    
    # Range of dates to archive
    start_date_str = os.getenv("START_DATE", "20250101")
    end_date_str = os.getenv("END_DATE", "20250115")
    
    start_date = datetime.strptime(start_date_str, "%Y%m%d")
    end_date = datetime.strptime(end_date_str, "%Y%m%d")
    
    # Performance and concurrency settings
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))  # Default: 2 workers for parallel processing
    MAX_RETRIES_PER_ARTICLE = int(os.getenv("MAX_RETRIES_PER_ARTICLE", "3"))  # Default: 3 retries per article
    VERIFY_UPLOADS = os.getenv("VERIFY_UPLOADS", "false").lower() == "true"  # Default: don't verify (faster)
    
    current_date = start_date
    articles_by_month = {}  # Track articles by month for index generation

    # Process dates in parallel for better performance
    # But limit concurrency to avoid overwhelming IA
    dates_to_process = []
    temp_date = start_date
    while temp_date <= end_date:
        dates_to_process.append(temp_date)
        temp_date += timedelta(days=1)
        # Break if we have accumulated too many dates
        if len(dates_to_process) >= 30:
            break
    
    logger.info(f"Processing {len(dates_to_process)} dates in parallel (max {MAX_WORKERS} concurrent)")
    
    for current_date in dates_to_process:
        date_str = current_date.strftime("%Y%m%d")
        # Calculate monthly bucket ID
        bucket_id = f"{prefix}-{current_date.year}-{current_date.month:02d}"
        
        console.print(f"📅 Processing date: {date_str} → Bucket: {bucket_id}", style="blue")
        
        urls = url_gen.get_article_urls(current_date)
        # Filter out already archived to avoid overhead
        archived_urls = db.get_archived_urls()
        urls_to_process = [u for u in urls if u not in archived_urls]
        
        console.print(f"📊 Found {len(urls)} articles for {date_str} ({len(urls_to_process)} new)", style="cyan")
        
        count = 0
        if urls_to_process:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(archive_article, url, ia_client, bucket_id, db,
                                        max_retries=MAX_RETRIES_PER_ARTICLE, verify_upload=VERIFY_UPLOADS)
                    for url in urls_to_process
                }

                for future in tqdm(as_completed(futures), total=len(futures), desc=f"Archiving {date_str}"):
                    if future.result():
                        count += 1

        # Track articles for this month
        if bucket_id not in articles_by_month:
            articles_by_month[bucket_id] = {}
        if date_str not in articles_by_month[bucket_id]:
            articles_by_month[bucket_id][date_str] = []

        # Add articles from this date to the tracking
        for url in urls_to_process:
            match = re.search(r'News/(\d{8}/HK-[^/]+_r\.htm)', url)
            if match:
                articles_by_month[bucket_id][date_str].append(match.group(1))

        now = datetime.now()
        console.print(f"  ✅ Completed {date_str}: {count} articles processed at {now.strftime('%H:%M:%S')}", style="green")
    
    # Generate and upload index.html for each month
    for bucket_id, articles_by_date in articles_by_month.items():
        if articles_by_date:
            # Collect all keys for this bucket to fetch titles
            all_keys = []
            for date_articles in articles_by_date.values():
                all_keys.extend(date_articles)
            titles = db.get_titles_by_keys(all_keys) if all_keys else {}
            
            index_html = generate_index_html(bucket_id, articles_by_date, titles)
            index_content = index_html.encode('utf-8')
            logger.info(f"Uploading index.html to {bucket_id}")
            ia_client.upload_file(bucket_id, "index.html", index_content, content_type="text/html")

if __name__ == "__main__":
    main()
