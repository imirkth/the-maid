"""
The Maid — File Scanner
Recursive directory walk with metadata extraction.
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from .sandbox import validate_path, MAX_FILES, FILE_TIMEOUT


class FileScanner:
    """Scans directories and extracts file metadata."""
    
    def __init__(self, max_files: int = MAX_FILES):
        self.max_files = max_files
        self.scanned_count = 0
        self.errors: List[str] = []
    
    def scan_directory(self, directory: str) -> List[Dict[str, Any]]:
        """
        Recursively scan a directory and return file metadata.
        Respects sandbox boundaries.
        """
        root = validate_path(directory)
        results = []
        
        for dirpath, dirnames, filenames in os.walk(root):
            # Validate we're still in sandbox
            validate_path(dirpath)
            
            for filename in filenames:
                if self.scanned_count >= self.max_files:
                    self.errors.append(f"Reached max file limit ({self.max_files})")
                    break
                
                file_path = Path(dirpath) / filename
                
                try:
                    metadata = self._extract_metadata(file_path)
                    results.append(metadata)
                    self.scanned_count += 1
                except Exception as e:
                    self.errors.append(f"Error scanning {file_path}: {e}")
            
            if self.scanned_count >= self.max_files:
                break
        
        return results
    
    def _extract_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Extract basic metadata from a file."""
        stat = file_path.stat()
        
        metadata = {
            "file_id": self._generate_id(),
            "filename": file_path.name,
            "path": str(file_path),
            "size_bytes": stat.st_size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "extension": file_path.suffix.lower(),
            "mime_type": self._guess_mime(file_path),
        }
        
        # TODO: Add EXIF extraction for images
        # TODO: Add text extraction for PDFs/docx
        # TODO: Add first-page OCR for PDFs
        
        return metadata
    
    def _generate_id(self) -> str:
        """Generate unique file ID."""
        import hashlib
        return hashlib.sha256(
            f"{self.scanned_count}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:8]
    
    def _guess_mime(self, file_path: Path) -> str:
        """Guess MIME type from extension."""
        ext_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".mp4": "video/mp4",
            ".mp3": "audio/mpeg",
        }
        return ext_map.get(file_path.suffix.lower(), "application/octet-stream")
