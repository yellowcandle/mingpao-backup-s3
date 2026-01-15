import requests
import logging
import re
import json
from typing import Dict, Optional, Any
from urllib.parse import quote, urlencode

logger = logging.getLogger(__name__)

class IAS3Client:
    """
    Client for Internet Archive S3 API (IAS3)
    Reference: https://archive.org/developers/ias3.html
    """
    
    BASE_ENDPOINT = "https://s3.us.archive.org"
    
    DEFAULT_METADATA = {
        "collection": "opensource",
        "creator": "Ming Pao Canada",
        "language": "chi",
        "mediatype": "texts",
        "subject": "Ming Pao Canada; Archive; News; Hong Kong",
        "licenseurl": "https://creativecommons.org/licenses/by-sa/4.0/",
        "scanner": "Ming Pao Backup Tool",
        "ppi": "96"
    }
    
    def __init__(self, access_key: str, secret_key: str):
        self.access_key = access_key
        self.secret_key = secret_key
        self.auth_header = f"LOW {access_key}:{secret_key}"

    @staticmethod
    def sanitize_id(identifier: str) -> str:
        """
        Sanitize an identifier for Internet Archive.
        Rules: 
        - Lowercase alphanumeric, dashes, and dots only.
        - Must start with alphanumeric.
        """
        # Lowercase
        identifier = identifier.lower()
        # Remove non-compliant characters
        identifier = re.sub(r'[^a-z0-9\-\.]', '-', identifier)
        # Ensure it starts with alphanumeric
        identifier = re.sub(r'^[^a-z0-9]+', '', identifier)
        return identifier
        
    def upload_file(self, 
                    bucket: str, 
                    key: str, 
                    content: bytes, 
                    content_type: str = "text/html",
                    metadata: Optional[Dict[str, str]] = None,
                    max_retries: int = 3) -> bool:
        """
        Upload content to IA using S3 PUT with retry logic.
        
        Args:
            bucket: The IA item identifier (will be sanitized)
            key: The filename within the item
            content: Raw bytes to upload
            content_type: MIME type
            metadata: Optional IA metadata headers (x-archive-meta-*)
            max_retries: Number of retries for transient failures (500 errors)
        """
        import time
        import random
        
        bucket = self.sanitize_id(bucket)
        url = f"{self.BASE_ENDPOINT}/{bucket}/{key}"
        
        headers = {
            "Authorization": self.auth_header,
            "Content-Type": content_type,
            "x-archive-auto-make-bucket": "1",
        }
        
        # Merge with default metadata
        final_metadata = self.DEFAULT_METADATA.copy()
        if metadata:
            final_metadata.update(metadata)

        for k, v in final_metadata.items():
            # URI-encode non-ASCII characters for HTTP headers
            # Internet Archive supports URI-encoded UTF-8 in metadata headers
            encoded_v = quote(str(v), safe='')
            if not k.startswith("x-archive-meta-"):
                headers[f"x-archive-meta-{k}"] = f"uri({encoded_v})"
            else:
                headers[k] = f"uri({encoded_v})"
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.put(url, data=content, headers=headers, timeout=60)
                
                if response.status_code == 200:
                    logger.info(f"Successfully uploaded {key} to {bucket}")
                    return True
                elif response.status_code == 500 and attempt < max_retries:
                    # IA returns 500 for lock contention - retry with backoff
                    wait_time = (2 ** attempt) + random.random() * 2
                    logger.warning(f"IA returned 500 for {key}, retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to upload {key} to {bucket}. Status: {response.status_code}, Body: {response.text[:500]}")
                    return False
                    
            except Exception as e:
                if attempt < max_retries:
                    wait_time = (2 ** attempt) + random.random()
                    logger.warning(f"Exception uploading {key}, retrying in {wait_time:.1f}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.exception(f"Exception during upload of {key} to {bucket}: {e}")
                    return False
        
        return False

    def bucket_exists(self, bucket: str) -> bool:
        """Check if an item exists by sending a HEAD request."""
        url = f"{self.BASE_ENDPOINT}/{bucket}"
        headers = {"Authorization": self.auth_header}
        try:
            response = requests.head(url, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception:
            return False
    
    def verify_file_uploaded(self, bucket: str, key: str, max_retries: int = 5) -> bool:
        """
        Verify that a file was successfully uploaded to IA.
        Uses the public metadata API to check file presence.
        Retries with backoff in case of eventual consistency delays.
        
        Note: IA has eventual consistency - files may take 10-30+ seconds to appear.
        """
        import time
        bucket = self.sanitize_id(bucket)
        
        for attempt in range(max_retries):
            try:
                # Use the public metadata API
                url = f"https://archive.org/metadata/{bucket}"
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    metadata = response.json()
                    if 'files' in metadata:
                        # Check if our file is in the files list
                        for file_obj in metadata['files']:
                            if file_obj.get('name') == key:
                                logger.info(f"✓ Verified: {key} exists on IA")
                                return True
                    
                    # File not found yet, might be eventual consistency
                    if attempt < max_retries - 1:
                        wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s, 20s
                        logger.warning(f"File {key} not found in metadata yet. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                else:
                    logger.warning(f"Failed to fetch metadata for {bucket}: HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                    
            except Exception as e:
                logger.error(f"Error verifying {key}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
        
        logger.error(f"✗ Failed to verify {key} on IA after {max_retries} attempts")
        return False
    
    def upload_metadata_file(self, bucket: str, metadata_dict: Dict[str, str]) -> bool:
        """
        Upload a metadata.txt file for IA item configuration.
        This helps IA understand the item structure and enables better rendering.
        """
        bucket = self.sanitize_id(bucket)
        
        # Create metadata.txt content in key=value format
        metadata_lines = []
        for key, value in metadata_dict.items():
            # IA metadata format: key = value
            metadata_lines.append(f"{key} = {value}")
        
        content = "\n".join(metadata_lines).encode('utf-8')
        return self.upload_file(bucket, "metadata.txt", content, content_type="text/plain")

    def update_file_metadata(self, bucket: str, filename: str, title: str, max_retries: int = 2) -> bool:
        """
        Update per-file metadata using the IA Metadata Write API.
        Sets the title field for a specific file in the item's _files.xml.
        
        This is best-effort only - failures don't affect the archived file itself.
        Files need time to be indexed in IA's metadata system before updates can apply.
        
        Reference: https://archive.org/developers/md-write.html
        
        Args:
            bucket: The IA item identifier
            filename: The filename within the item (e.g., "20190401/HK-gaa1_r.htm")
            title: The article title to set
            max_retries: Number of retries for transient failures (reduced to avoid slowdown)
        """
        import time
        import random
        
        if not title:
            return True  # Nothing to update
        
        bucket = self.sanitize_id(bucket)
        url = f"https://archive.org/metadata/{bucket}"
        
        # JSON Patch to add/replace the title field
        patch = {"op": "add", "path": "/title", "value": title}
        
        # URL-encoded form data
        # Note: -patch value is JSON, then the whole form is URL-encoded
        form_data = {
            "-target": f"files/{filename}",
            "-patch": json.dumps(patch),
            "access": self.access_key,
            "secret": self.secret_key,
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.post(url, data=form_data, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        logger.info(f"✓ Updated metadata for {filename}: {title[:30]}...")
                        return True
                    else:
                        error = result.get("error", "Unknown error")
                        # "No changes made" is not a fatal error
                        if "no changes" in error.lower():
                            logger.debug(f"No metadata changes needed for {filename}")
                            return True
                        logger.debug(f"Metadata update info for {filename}: {error}")
                        return True  # Don't fail - file is still archived
                elif response.status_code == 400:
                    # 400 means file not found in metadata yet (eventual consistency issue)
                    # This is temporary and will resolve later, so just log and continue
                    if attempt < max_retries:
                        wait_time = 10 + (5 * attempt)
                        logger.debug(f"File not indexed yet for {filename}, will retry later in background")
                        time.sleep(wait_time)
                    else:
                        logger.debug(f"File metadata will be available later: {filename}")
                    return True  # Don't fail - file is still archived
                elif response.status_code == 429:
                    # Rate limited - don't retry aggressively, just log and move on
                    logger.warning(f"Rate limited updating metadata for {filename} - will be available later")
                    return True  # Don't fail - file is still archived
                elif response.status_code >= 500:
                    logger.warning(f"Server error updating metadata for {filename} - will retry later")
                    return True  # Don't fail - file is still archived
                else:
                    logger.warning(f"Could not update metadata for {filename}: HTTP {response.status_code}")
                    return True  # Don't fail - file is still archived
                    
            except Exception as e:
                logger.debug(f"Exception updating metadata for {filename}: {e}")
                return True  # Don't fail - file is still archived
        
        return True
