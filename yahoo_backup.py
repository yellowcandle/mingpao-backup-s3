import os
import time
import json
import logging
import requests
import re
import random
import queue
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from bs4 import BeautifulSoup
from ia_s3_client import IAS3Client
from yahoo_url_generator import YahooNewsUrlGenerator
from database import ArchiveDB

# Rich console for pretty output
console = Console()
logger = logging.getLogger("yahoo_news_backup")


def extract_yahoo_article_title(content: bytes) -> Optional[str]:
    """Extract article title from Yahoo News HTML using JSON-LD or og:title."""
    try:
        soup = BeautifulSoup(content, "html.parser")

        # Try JSON-LD first (most reliable)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and "headline" in data:
                    return data["headline"].strip()
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "headline" in item:
                            return item["headline"].strip()
            except (json.JSONDecodeError, AttributeError):
                continue

        # Fallback to og:title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

        # Fallback to <title> tag
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            return title_tag.string.strip()

        return None
    except Exception as e:
        logger.warning(f"Failed to extract title from Yahoo content: {e}")
        return None


def extract_yahoo_article_date(content: bytes) -> Optional[str]:
    """Extract article publish date from Yahoo News HTML (YYYYMMDD format)."""
    try:
        soup = BeautifulSoup(content, "html.parser")

        # Try JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and "datePublished" in data:
                    dt = datetime.fromisoformat(
                        data["datePublished"].replace("Z", "+00:00")
                    )
                    return dt.strftime("%Y%m%d")
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "datePublished" in item:
                            dt = datetime.fromisoformat(
                                item["datePublished"].replace("Z", "+00:00")
                            )
                            return dt.strftime("%Y%m%d")
            except (json.JSONDecodeError, AttributeError, ValueError):
                continue

        # Fallback to article:published_time meta tag
        pub_meta = soup.find("meta", property="article:published_time")
        if pub_meta and pub_meta.get("content"):
            dt = datetime.fromisoformat(
                pub_meta["content"].replace("Z", "+00:00")
            )
            return dt.strftime("%Y%m%d")

        return None
    except Exception as e:
        logger.warning(f"Failed to extract date from Yahoo content: {e}")
        return None


def extract_article_id(url: str) -> Optional[str]:
    """Extract the numeric article ID from a Yahoo News URL."""
    # URL format: https://hk.news.yahoo.com/{slug}-{numeric_id}.html
    match = re.search(r"-(\d{9,})\.html$", url)
    if match:
        return match.group(1)
    # Fallback: use the full filename
    match = re.search(r"/([^/]+)\.html$", url)
    if match:
        return match.group(1)
    return None


def archive_yahoo_article(
    url: str,
    ia_client: IAS3Client,
    bucket: str,
    db: ArchiveDB,
    max_retries: int = 3,
    verify_upload: bool = False,
    metadata_queue: Optional[queue.Queue] = None,
):
    """Fetch Yahoo News article and upload to IA."""
    if db.is_archived(url):
        return True

    article_id = extract_article_id(url)
    if not article_id:
        logger.warning(f"Could not extract article ID from URL: {url}")
        return False

    content = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(
                url,
                timeout=30,
                allow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                },
            )
            if response.status_code == 200:
                content = response.content
                break
            elif response.status_code == 404:
                return False
            else:
                logger.warning(
                    f"Attempt {attempt+1} failed for {url}: "
                    f"HTTP {response.status_code}"
                )
        except (requests.exceptions.RequestException, Exception) as e:
            if attempt < max_retries:
                wait_time = (2**attempt) + random.random()
                logger.warning(
                    f"Attempt {attempt+1} failed for {url}: {e}. "
                    f"Retrying in {wait_time:.2f}s..."
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    f"Failed to fetch {url} after {max_retries+1} attempts: {e}"
                )
                return False

    if not content:
        return False

    try:
        title = extract_yahoo_article_title(content)
        date_str = extract_yahoo_article_date(content)

        if not date_str:
            date_str = datetime.now().strftime("%Y%m%d")

        # Organize by date: YYYYMMDD/article_id.html
        key = f"{date_str}/{article_id}.html"

        metadata = {
            "mediatype": "texts",
            "originalurl": url,
            "subject": "Yahoo News; Hong Kong; Archive; News",
            "date": date_str,
            "title": title if title else f"Article {article_id}",
        }

        success = ia_client.upload_file(bucket, key, content, metadata=metadata)
        if success:
            if verify_upload:
                if not ia_client.verify_file_uploaded(bucket, key):
                    logger.warning(
                        f"Upload succeeded but verification failed for {key}"
                    )
                    return False

            if title and metadata_queue:
                try:
                    metadata_queue.put(
                        (bucket, key, title), block=True, timeout=1.0
                    )
                except queue.Full:
                    logger.warning(
                        f"Metadata queue full, dropping update for {key}"
                    )

            db.record_upload(url, bucket, key, title)
            return True
    except Exception as e:
        logger.error(f"Error uploading {url} to IA: {e}")
        return False


def generate_yahoo_index_html(
    bucket_id: str,
    articles: Dict[str, list],
    titles: Optional[Dict[str, str]] = None,
) -> str:
    """Generate an HTML index file for archived Yahoo News articles."""
    if titles is None:
        titles = {}
    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-HK">',
        "<head>",
        '    <meta charset="UTF-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"    <title>Yahoo News HK Archive - {bucket_id}</title>",
        "    <style>",
        "        body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }",
        "        h1 { color: #333; }",
        "        .date-section { margin-bottom: 30px; }",
        "        .date-section h2 { background: #f0f0f0; padding: 10px; border-left: 4px solid #7b1fa2; }",
        "        .article-list { list-style: none; padding-left: 0; }",
        "        .article-list li { padding: 8px 0; border-bottom: 1px solid #eee; }",
        '        .article-list a { color: #0066cc; text-decoration: none; }',
        "        .article-list a:hover { text-decoration: underline; }",
        '        .article-date { color: #666; font-size: 0.9em; }',
        "    </style>",
        "</head>",
        "<body>",
        f"    <h1>Yahoo News HK Archive: {bucket_id}</h1>",
        "    <p>Hong Kong news archived from Yahoo News Hong Kong</p>",
    ]

    for date in sorted(articles.keys()):
        html_parts.append('    <div class="date-section">')
        html_parts.append(f"        <h2>{date}</h2>")
        html_parts.append('        <ul class="article-list">')

        for filename in sorted(articles[date]):
            article_title = titles.get(filename, "")
            article_id = filename.split("/")[-1].replace(".html", "")
            display_name = article_title if article_title else article_id
            html_parts.append(
                f'            <li><a href="{filename}" target="_blank">{display_name}</a> '
                f'<span class="article-date">({article_id})</span></li>'
            )

        html_parts.append("        </ul>")
        html_parts.append("    </div>")

    html_parts.extend(
        [
            "    <hr>",
            "    <footer>",
            "        <p>Archive Date: "
            + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            + "</p>",
            "        <p>Archived by Yahoo News Backup Tool | "
            'Source: <a href="https://hk.news.yahoo.com">Yahoo News HK</a></p>',
            "    </footer>",
            "</body>",
            "</html>",
        ]
    )

    return "\n".join(html_parts)


def yahoo_health_check(ia_client: IAS3Client) -> bool:
    """Perform health checks for Yahoo News backup."""
    console.print("⏳ Running health checks...", style="bold cyan")

    # Check IA connectivity
    try:
        if not ia_client.bucket_exists("test-mingpao-backup"):
            console.print(
                "  ⚠️ Warning: Could not verify existing bucket, "
                "but IA S3 endpoint is reachable",
                style="yellow",
            )
        console.print("  ✅ Internet Archive S3 connection OK", style="green")
    except Exception as e:
        console.print(
            f"  ❌ Internet Archive connection failed: {e}", style="red"
        )
        return False

    # Check Yahoo News HK connectivity
    try:
        test_url = "https://hk.news.yahoo.com/"
        response = requests.head(test_url, timeout=10, allow_redirects=True)

        if response.status_code < 500:
            console.print(
                "  ✅ Yahoo News HK website is reachable", style="green"
            )
            return True
        else:
            console.print(
                f"  ⚠️ Yahoo News HK returned status {response.status_code}",
                style="yellow",
            )
            return False
    except Exception as e:
        console.print(
            f"  ❌ Yahoo News HK website unreachable: {e}", style="red"
        )
        return False


def run_yahoo_backup():
    """Main entry point for Yahoo News HK backup."""
    from dotenv import load_dotenv

    # Clear env vars set by Dockerfile so .env can override them
    for key in ["START_DATE", "END_DATE"]:
        os.environ.pop(key, None)
    load_dotenv()

    access_key = os.getenv("IA_ACCESS_KEY")
    secret_key = os.getenv("IA_SECRET_KEY")
    prefix = os.getenv("IA_IDENTIFIER_PREFIX", "yahoo-news-hk")

    if not access_key or not secret_key:
        logger.error("IA_ACCESS_KEY and IA_SECRET_KEY must be set in .env file")
        return

    ia_client = IAS3Client(access_key, secret_key)

    # Run health checks
    if not yahoo_health_check(ia_client):
        logger.error("Health checks failed. Aborting backup.")
        return

    url_gen = YahooNewsUrlGenerator()
    db = ArchiveDB()

    # Range of dates to archive
    start_date_str = os.getenv("START_DATE", datetime.now().strftime("%Y%m%d"))
    end_date_str = os.getenv("END_DATE", datetime.now().strftime("%Y%m%d"))

    start_date = datetime.strptime(start_date_str, "%Y%m%d")
    end_date = datetime.strptime(end_date_str, "%Y%m%d")

    # Performance settings
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
    MAX_RETRIES_PER_ARTICLE = int(os.getenv("MAX_RETRIES_PER_ARTICLE", "3"))
    VERIFY_UPLOADS = os.getenv("VERIFY_UPLOADS", "false").lower() == "true"
    METADATA_QUEUE_SIZE = int(os.getenv("METADATA_QUEUE_SIZE", "200"))

    # Metadata worker
    def metadata_worker(q, ia_client):
        while True:
            item = q.get()
            if item is None:
                q.task_done()
                break
            bucket, key, title = item
            try:
                ia_client.update_file_metadata(bucket, key, title)
            except Exception as e:
                logger.error(f"Metadata worker error for {key}: {e}")
            finally:
                q.task_done()

    metadata_queue = queue.Queue(maxsize=METADATA_QUEUE_SIZE)
    metadata_thread = threading.Thread(
        target=metadata_worker,
        args=(metadata_queue, ia_client),
        daemon=False,
        name="MetadataWorker",
    )
    metadata_thread.start()
    logger.info(
        f"✓ Started background metadata worker thread "
        f"(queue size: {METADATA_QUEUE_SIZE})"
    )

    # Smart resume
    last_processed = db.get_last_processed_date()
    if last_processed:
        try:
            last_date = datetime.strptime(last_processed, "%Y%m%d")
            if last_date >= start_date and last_date < end_date:
                logger.info(
                    f"🚀 Smart resume: Last processed was {last_processed}, "
                    "resuming from next day..."
                )
                start_date = last_date + timedelta(days=1)
        except ValueError:
            logger.warning(f"Invalid last_processed_date: {last_processed}")

    total_days = (end_date - start_date).days + 1
    logger.info("📋 Configuration:")
    logger.info(f"  • Mode: Yahoo News HK")
    logger.info(f"  • Prefix: {prefix}")
    logger.info(
        f"  • Date range: {start_date_str} → {end_date_str} ({total_days} days)"
    )
    logger.info(f"  • Parallelism: {MAX_WORKERS} workers")
    logger.info(f"  • Verification: {'enabled' if VERIFY_UPLOADS else 'disabled'}")

    current_date = start_date
    articles_by_month = {}

    total_dates_processed = 0
    total_articles_uploaded = 0
    total_articles_found = 0

    while current_date <= end_date:
        date_str = current_date.strftime("%Y%m%d")
        bucket_id = f"{prefix}-{current_date.year}-{current_date.month:02d}"

        console.print(
            f"📅 Processing date: {date_str} → Bucket: {bucket_id}",
            style="blue",
        )

        urls = url_gen.get_article_urls(current_date)
        archived_urls = db.get_archived_urls()
        urls_to_process = [u for u in urls if u not in archived_urls]

        total_articles_found += len(urls)
        total_dates_processed += 1
        console.print(
            f"📊 Found {len(urls)} articles for {date_str} "
            f"({len(urls_to_process)} new)",
            style="cyan",
        )

        count = 0
        if urls_to_process:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(
                        archive_yahoo_article,
                        url,
                        ia_client,
                        bucket_id,
                        db,
                        max_retries=MAX_RETRIES_PER_ARTICLE,
                        verify_upload=VERIFY_UPLOADS,
                        metadata_queue=metadata_queue,
                    )
                    for url in urls_to_process
                }

                for future in tqdm(
                    as_completed(futures),
                    total=len(futures),
                    desc=f"Archiving {date_str}",
                ):
                    if future.result():
                        count += 1

        total_articles_uploaded += count

        # Track articles for index generation
        if bucket_id not in articles_by_month:
            articles_by_month[bucket_id] = {}
        if date_str not in articles_by_month[bucket_id]:
            articles_by_month[bucket_id][date_str] = []

        for url in urls_to_process:
            article_id = extract_article_id(url)
            if article_id:
                key = f"{date_str}/{article_id}.html"
                articles_by_month[bucket_id][date_str].append(key)

        now = datetime.now()
        success_rate = (
            (count / len(urls_to_process) * 100) if urls_to_process else 0
        )
        console.print(
            f"  ✅ Completed {date_str}: {count}/{len(urls_to_process)} "
            f"articles uploaded ({success_rate:.0f}%) "
            f"at {now.strftime('%H:%M:%S')}",
            style="green",
        )

        db.set_last_processed_date(date_str)
        current_date += timedelta(days=1)

    # Final summary
    logger.info("✨ Yahoo News archive pass complete!")
    logger.info("📊 Summary:")
    logger.info(f"  • Dates processed: {total_dates_processed}")
    logger.info(f"  • Articles found: {total_articles_found}")
    logger.info(f"  • Articles uploaded: {total_articles_uploaded}")
    if total_articles_found > 0:
        upload_rate = total_articles_uploaded / total_articles_found * 100
        logger.info(f"  • Upload success rate: {upload_rate:.1f}%")

    # Shutdown metadata worker
    logger.info("🔄 Waiting for pending metadata updates to complete...")
    metadata_queue.put(None)
    metadata_queue.join()
    metadata_thread.join(timeout=60)

    if metadata_thread.is_alive():
        logger.warning("⚠️  Metadata worker thread did not exit cleanly")
    else:
        logger.info("✓ All metadata updates completed")

    console.print(
        "[bold green]🎉 Yahoo News archive complete![/bold green]",
        justify="center",
    )
    console.print(
        f"[dim]Processed {total_dates_processed} dates, "
        f"uploaded {total_articles_uploaded} articles[/dim]",
        justify="center",
    )

    # Generate and upload index.html for each month
    for bucket_id, articles_by_date in articles_by_month.items():
        if articles_by_date:
            all_keys = []
            for date_articles in articles_by_date.values():
                all_keys.extend(date_articles)
            titles = db.get_titles_by_keys(all_keys) if all_keys else {}

            index_html = generate_yahoo_index_html(
                bucket_id, articles_by_date, titles
            )
            index_content = index_html.encode("utf-8")
            logger.info(f"Uploading index.html to {bucket_id}")
            ia_client.upload_file(
                bucket_id, "index.html", index_content, content_type="text/html"
            )
