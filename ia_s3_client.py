import requests
import logging
import re
from typing import Dict, Optional, Any

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
                    metadata: Optional[Dict[str, str]] = None) -> bool:
        """
        Upload content to IA using S3 PUT.
        
        Args:
            bucket: The IA item identifier (will be sanitized)
            key: The filename within the item
            content: Raw bytes to upload
            content_type: MIME type
            metadata: Optional IA metadata headers (x-archive-meta-*)
        """
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
            if not k.startswith("x-archive-meta-"):
                headers[f"x-archive-meta-{k}"] = v
            else:
                headers[k] = v
        
        try:
            response = requests.put(url, data=content, headers=headers, timeout=60)
            
            if response.status_code == 200:
                logger.info(f"Successfully uploaded {key} to {bucket}")
                return True
            else:
                logger.error(f"Failed to upload {key} to {bucket}. Status: {response.status_code}, Body: {response.text}")
                return False
                
        except Exception as e:
            logger.exception(f"Exception during upload of {key} to {bucket}: {e}")
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
    
    def verify_file_uploaded(self, bucket: str, key: str, max_retries: int = 3) -> bool:
        """
        Verify that a file was successfully uploaded to IA.
        Uses the public metadata API to check file presence.
        Retries with backoff in case of eventual consistency delays.
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
                        wait_time = 2 ** attempt  # Exponential backoff
                        logger.warning(f"File {key} not found in metadata yet. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                else:
                    logger.warning(f"Failed to fetch metadata for {bucket}: HTTP {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Error verifying {key}: {e}")
        
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
