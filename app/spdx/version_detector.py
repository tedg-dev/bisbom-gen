"""
Backward-compatibility shim — delegates to
app.version_detection.detector.

All new code should import from
app.version_detection directly.
"""

from app.version_detection.detector import (
    VendoredVersionDetector,
)

__all__ = ["VendoredVersionDetector"]
