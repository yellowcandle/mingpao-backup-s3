import requests
import logging
import hashlib
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

class IAS3Client:
    """
    Client for Internet Archive S3 API (IAS3)
    Reference: https://archive.org/developers/ias3.html
    """
    
    BASE_ENDPOINT = "https://s3.us.archive.org"
    
    def __init__(self, access_key: str, secret_key: str):
        self.access_key = access_key
        self.secret_key = secret_key
        self.auth_header = f"LOW {access_key}:{secret_key}"
        
    def upload_file(self, 
                    bucket: str, 
                    key: str, 
                    content: bytes, 
                    content_type: str = "text/html",
                    metadata: Optional[Dict[str, str]] = None) -> bool:
        """
        Upload content to IA using S3 PUT.
        
        Args:
            bucket: The IA item identifier
            key: The filename within the item
            content: Raw bytes to upload
            content_type: MIME type
            metadata: Optional IA metadata headers (x-archive-meta-*)
        """
        url = f"{self.BASE_ENDPOINT}/{bucket}/{key}"
        
        headers = {
            "Authorization": self.auth_header,
            "Content-Type": content_type,
            "x-archive-auto-make-bucket": "1",
        }
        
        if metadata:
            for k, v in metadata.items():
                if not k.startswith("x-archive-meta-"):
                    headers[f"x-archive-meta-{k}"] = v
                else:
                    headers[k] = v
        
        try:
            # IA S3 requires MD5 for integrity sometimes, but it's optional for basic PUT
            # Let's just do a simple PUT first.
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
