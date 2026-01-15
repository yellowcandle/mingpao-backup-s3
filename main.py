import os
import time
import logging
import requests
import re
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

from ia_s3_client import IAS3Client
from url_generator import MingPaoUrlGenerator
from database import ArchiveDB

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("data/archive.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("mingpao_ia_backup")

import random

def archive_article(url: str, ia_client: IAS3Client, bucket: str, db: ArchiveDB, max_retries: int = 3):
    """Fetch article and upload to IA with retry logic."""
    if db.is_archived(url):
        return True

    # Generate a safe key for IA
    match = re.search(r'News/(\d{8}/HK-[^/]+_r\.htm)', url)
    if match:
        key = match.group(1)
    else:
        key = "/".join(url.split("/")[-2:])

    content = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            if response.status_code == 200:
                content = response.content
                break
            elif response.status_code == 404:
                # logger.debug(f"Article not found (404): {url}")
                return False
            else:
                logger.warning(f"Attempt {attempt+1} failed for {url}: HTTP {response.status_code}")
        except (requests.exceptions.RequestException, Exception) as e:
            if attempt < max_retries:
                wait_time = (2 ** attempt) + random.random()
                logger.warning(f"Attempt {attempt+1} failed for {url}: {e}. Retrying in {wait_time:.2f}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed to fetch {url} after {max_retries+1} attempts: {e}")
                return False

    if not content:
        return False

    try:
        # IA Metadata
        metadata = {
            "mediatype": "texts",
            "originalurl": url,
            "subject": "Ming Pao Canada; Archive; News; Hong Kong",
            "date": key.split('/')[0] if '/' in key else datetime.now().strftime("%Y%m%d")
        }
        
        success = ia_client.upload_file(bucket, key, content, metadata=metadata)
        if success:
            db.record_upload(url, bucket, key)
            return True
    except Exception as e:
        logger.error(f"Error uploading {url} to IA: {e}")
        return False

def main():
    load_dotenv()
    
    access_key = os.getenv("IA_ACCESS_KEY")
    secret_key = os.getenv("IA_SECRET_KEY")
    prefix = os.getenv("IA_IDENTIFIER_PREFIX", "mingpao-canada-hk-news")
    max_workers = int(os.getenv("MAX_WORKERS", "5"))
    
    if not access_key or not secret_key:
        logger.error("IA_ACCESS_KEY and IA_SECRET_KEY must be set in .env file")
        return

    ia_client = IAS3Client(access_key, secret_key)
    url_gen = MingPaoUrlGenerator()
    db = ArchiveDB()
    
    # Range of dates to archive
    start_date_str = os.getenv("START_DATE", "20250101")
    end_date_str = os.getenv("END_DATE", "20250115")
    
    start_date = datetime.strptime(start_date_str, "%Y%m%d")
    end_date = datetime.strptime(end_date_str, "%Y%m%d")
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y%m%d")
        # Calculate monthly bucket ID
        bucket_id = f"{prefix}-{current_date.year}-{current_date.month:02d}"
        
        logger.info(f"Processing date: {date_str} -> Bucket: {bucket_id}")
        
        urls = url_gen.get_article_urls(current_date)
        # Filter out already archived to avoid overhead
        archived_urls = db.get_archived_urls()
        urls_to_process = [u for u in urls if u not in archived_urls]
        
        logger.info(f"Found {len(urls)} possible articles for {date_str} ({len(urls_to_process)} to process)")
        
        count = 0
        if urls_to_process:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(archive_article, url, ia_client, bucket_id, db): url for url in urls_to_process}
                
                for future in tqdm(as_completed(futures), total=len(futures), desc=f"Archiving {date_str}"):
                    if future.result():
                        count += 1
            
        logger.info(f"Finished {date_str}: {count} articles processed.")
        current_date += timedelta(days=1)

if __name__ == "__main__":
    main()
