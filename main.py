def archive_article(url: str, ia_client: IAS3Client, bucket: str, db: ArchiveDB, max_retries: int = 3, verify_upload: bool = False):
    """Fetch article and upload to IA with retry logic."""
    if db.is_archived(url):
        return True

    # Generate a safe key for IA
    match = re.search(r'News/(\d{8})/HK-[^/]+_r\.htm)', url)
    if match:
        key = match.group(1)
    else:
        key = "/".join(url.split("/")[-2:])

    # Convert HTTPS to HTTP to avoid SSL issues
    http_url = url.replace("https://", "http://")
    
    # Fetch content with retry logic
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

def extract_article_title(content: str) -> str:
    """Extract article title from HTML content."""
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(content, 'html.parser')
        title_tag = soup.find('h3', class_='article-title')
        if title_tag:
            return title_tag.get_text().strip()
        return f"Article from {datetime.now().strftime('%Y%m%d')}"
    except Exception as e:
        return f"Article from {datetime.now().strftime('%Y%m%d')} (Error: {e})"