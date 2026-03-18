"""
Version Detection — detect versions of vendored
libraries and project root packages from source code.

Supports C/C++, JavaScript/Node.js, Python, Rust, Go,
and Java ecosystems with 13 ordered strategies from
most-reliable to broadest-fallback.

Usage:
    from app.version_detection import (
        VendoredVersionDetector,
    )
    detector = VendoredVersionDetector()
    version = detector.detect("openssl", file_paths)
"""

from app.version_detection.detector import (
    VendoredVersionDetector,
)

__all__ = ["VendoredVersionDetector"]
