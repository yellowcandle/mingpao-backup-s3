import os
import time
import logging
import requests
import re
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

def archive_article(url: str, ia_client: IAS3Client, bucket: str, db: ArchiveDB):
    """Fetch article and upload to IA."""
    if db.is_archived(url):
        # logger.debug(f"Skipping already archived: {url}")
        return True

    # Generate a safe key for IA
    # Example: https://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa1_r.htm
    # Key: 20250112/HK-gaa1_r.htm
    match = re.search(r'News/(\d{8}/HK-[^/]+_r\.htm)', url)
    if match:
        key = match.group(1)
    else:
        # Fallback to last parts of URL
        key = "/".join(url.split("/")[-2:])

    try:
        response = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        if response.status_code != 200:
            logger.error(f"Failed to fetch {url}: {response.status_code}")
            return False
        
        content = response.content
        
        # IA Metadata
        metadata = {
            "mediatype": "texts",
            "originalurl": url,
            "subject": "Ming Pao Canada; Archive; News",
            "date": key.split('/')[0] if '/' in key else datetime.now().strftime("%Y%m%d")
        }
        
        success = ia_client.upload_file(bucket, key, content, metadata=metadata)
        if success:
            db.record_upload(url, bucket, key)
            return True
    except Exception as e:
        logger.error(f"Error archiving {url}: {e}")
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
