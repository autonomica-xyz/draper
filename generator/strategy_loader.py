#!/usr/bin/env python3
"""
Load and parse platform-specific content strategies
"""
from pathlib import Path
from typing import Dict, List
import re


class StrategyLoader:
    """Load platform-specific content strategies"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(Path(__file__).resolve().parent.parent)
        self.base_dir = Path(base_dir)

    def load_strategy(self, platform: str) -> Dict:
        """
        Load strategy for a platform (linkedin, twitter/x)

        Returns dict with:
        - tone_guidelines: str
        - anti_patterns: List[str]
        - proven_formats: List[Dict]
        - posting_strategy: Dict
        """
        if platform == "twitter":
            platform = "x"  # Twitter strategy is in x_strategy.md

        strategy_file = self.base_dir / f"{platform}_strategy.md"

        if not strategy_file.exists():
            return self._get_default_strategy(platform)

        content = strategy_file.read_text()

        return {
            "platform": platform,
            "tone_guidelines": self._extract_tone_guidelines(content),
            "anti_patterns": self._extract_anti_patterns(content),
            "proven_formats": self._extract_proven_formats(content),
            "posting_strategy": self._extract_posting_strategy(content),
            "full_content": content  # Include full content for LLM context
        }

    def _extract_tone_guidelines(self, content: str) -> str:
        """Extract tone and voice guidelines from strategy"""
        # Look for sections like "Tone: The 'Smart Colleague' Voice" or similar
        patterns = [
            r'## Tone.*?\n(.*?)(?=##|\Z)',
            r'## Voice.*?\n(.*?)(?=##|\Z)',
            r'##.*?Tone.*?\n(.*?)(?=##|\Z)'
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "Professional but conversational"

    def _extract_anti_patterns(self, content: str) -> List[str]:
        """Extract anti-patterns (what to avoid) from strategy"""
        anti_patterns = []

        # Look for sections like "Anti-Patterns" or "What Makes LinkedIn Posts Look Like AI"
        patterns = [
            r'## Anti-Patterns.*?\n(.*?)(?=##|\Z)',
            r'##.*?Anti.*?\n(.*?)(?=##|\Z)',
            r'##.*?AI.*?Look.*?\n(.*?)(?=##|\Z)'
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                section = match.group(1)
                # Extract bullet points or numbered items
                items = re.findall(r'[-*•]\s*\*\*(.*?)\*\*\s*\n\s*(.*?)(?=\n[-*•]|\n\n|\Z)', section, re.DOTALL)
                for title, description in items:
                    anti_patterns.append(f"{title.strip()}: {description.strip()}")

        return anti_patterns

    def _extract_proven_formats(self, content: str) -> List[Dict]:
        """Extract proven content formats from strategy"""
        formats = []

        # Look for sections like "Content That Works" or "Proven Formats"
        patterns = [
            r'## Content That Works.*?\n(.*?)(?=##|\Z)',
            r'## Proven.*?Format.*?\n(.*?)(?=##|\Z)',
            r'##.*?Format.*?\n(.*?)(?=##|\Z)'
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                section = match.group(1)
                # Extract format sections (usually numbered or with bold headers)
                format_matches = re.findall(r'###?\s+(\d+\.\s+.*?|[A-Z][^#\n]+)\n\n(.*?)(?=###?\s+\d+\.|###?\s+[A-Z]|##|\Z)', section, re.DOTALL)

                for title, description in format_matches:
                    # Extract examples if present
                    example_match = re.search(r'\*\*Real example\*\*.*?```(.+?)```', description, re.DOTALL)
                    example = example_match.group(1).strip() if example_match else ""

                    formats.append({
                        "title": title.strip(),
                        "description": description.strip(),
                        "example": example
                    })

        return formats

    def _extract_posting_strategy(self, content: str) -> Dict:
        """Extract posting strategy (cadence, timing, engagement)"""
        strategy = {
            "cadence": "",
            "timing": [],
            "engagement": []
        }

        # Look for posting strategy sections
        patterns = [
            r'## Posting.*?Strategy.*?\n(.*?)(?=##|\Z)',
            r'##.*?Strategy.*?\n(.*?)(?=##|\Z)'
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                section = match.group(1)

                # Extract cadence
                cadence_match = re.search(r'(?:Cadence|Volume|Frequency).*?:.*?([^\n]+)', section, re.IGNORECASE)
                if cadence_match:
                    strategy["cadence"] = cadence_match.group(1).strip()

                # Extract timing
                timing_matches = re.findall(r'[-*•]\s*(\d{1,2}:\d{2}\s*(?:AM|PM)?)', section)
                strategy["timing"] = timing_matches

                # Extract engagement tips
                engagement_section = re.search(r'(?:Engagement|Commenting).*?:.*?\n(.*?)(?=\n\n|\Z)', section, re.DOTALL | re.IGNORECASE)
                if engagement_section:
                    tips = re.findall(r'[-*•]\s*(.*?)(?=\n[-*•]|\n\n|\Z)', engagement_section.group(1))
                    strategy["engagement"] = [tip.strip() for tip in tips]

        return strategy

    def _get_default_strategy(self, platform: str) -> Dict:
        """Return default strategy if file not found"""
        return {
            "platform": platform,
            "tone_guidelines": "Professional and engaging",
            "anti_patterns": [
                "Avoid excessive jargon",
                "Don't use generic motivational quotes",
                "Avoid engagement bait"
            ],
            "proven_formats": [
                {
                    "title": "Educational Post",
                    "description": "Teach something valuable to your audience"
                }
            ],
            "posting_strategy": {
                "cadence": "3-4 posts per week",
                "timing": ["9:00 AM", "12:00 PM", "5:00 PM"],
                "engagement": ["Reply to comments within 1 hour"]
            },
            "full_content": f"# Default {platform.title()} Strategy\n\nNo specific strategy found. Using defaults."
        }
