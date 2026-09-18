"""Content reasoning tracker - tracks AI reasoning for content decisions"""

from typing import Dict, Optional


class ContentReasoningTracker:
    """Tracks reasoning behind content generation decisions.

    Stub implementation — methods are no-ops until the intelligence
    layer (M003) provides real reasoning capture.
    """

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir

    def record_reasoning(self, content_id: str, reasoning: Dict) -> None:
        """Record reasoning for a piece of content"""
        pass

    def get_reasoning(self, content_id: str) -> Optional[Dict]:
        """Get recorded reasoning for content"""
        return None

    def get_reasoning_by_id(self, reasoning_id: str) -> Optional[Dict]:
        """Get reasoning by its ID"""
        return None
