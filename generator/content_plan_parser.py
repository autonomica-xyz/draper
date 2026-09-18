#!/usr/bin/env python3
"""
Parse content plans and extract weekly themes, content pillars, deliverables
"""
from pathlib import Path
from typing import Dict, List
import re


class ContentPlanParser:
    """Parse content plans (e.g., acme.md) and extract structured information"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(Path(__file__).resolve().parent.parent)
        self.base_dir = Path(base_dir)

    def parse_content_plan(self, plan_path: str) -> Dict:
        """
        Parse a content plan file

        Returns dict with:
        - marketing_objective: str
        - positioning: str
        - audience_segments: List[Dict]
        - content_pillars: List[str]
        - weekly_themes: List[Dict] (week number, theme, deliverables per platform)
        """
        plan_file = Path(plan_path)

        if not plan_file.exists():
            return self._get_default_plan()

        content = plan_file.read_text()

        return {
            "marketing_objective": self._extract_marketing_objective(content),
            "positioning": self._extract_positioning(content),
            "audience_segments": self._extract_audience_segments(content),
            "content_pillars": self._extract_content_pillars(content),
            "weekly_themes": self._extract_weekly_themes(content),
            "channel_strategy": self._extract_channel_strategy(content),
            "full_content": content
        }

    def _extract_marketing_objective(self, content: str) -> str:
        """Extract primary marketing objective"""
        match = re.search(r'##.*?Marketing objective.*?\n(.*?)(?=##|\Z)', content, re.DOTALL | re.IGNORECASE)
        if match:
            # Extract the primary objective (first 90 days section)
            primary_match = re.search(r'###\s*Primary objective.*?\n(.*?)(?=###|\Z)', match.group(1), re.DOTALL | re.IGNORECASE)
            if primary_match:
                return primary_match.group(1).strip()
        return "Build audience and generate leads"

    def _extract_positioning(self, content: str) -> str:
        """Extract positioning statement"""
        match = re.search(r'###\s*Positioning.*?\n\*\*(.*?)\*\*', content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_audience_segments(self, content: str) -> List[Dict]:
        """Extract audience segments"""
        segments = []

        match = re.search(r'##\s*Audience segments.*?\n(.*?)(?=##|\Z)', content, re.DOTALL | re.IGNORECASE)
        if match:
            section = match.group(1)
            # Extract each segment (usually Segment A, B, C)
            segment_matches = re.findall(
                r'###\s*Segment\s+([A-C]).*?\n(.*?)(?=###\s*Segment|$)',
                section,
                re.DOTALL | re.IGNORECASE
            )

            for letter, segment_content in segment_matches:
                # Extract "Cares about" and "Teach" sections
                cares_match = re.search(r'Cares about:\s*(.*?)(?=\n\s*Teach:|\n\n|\Z)', segment_content, re.DOTALL)
                teach_match = re.search(r'Teach:\s*"(.*?)"', segment_content, re.DOTALL)

                segments.append({
                    "segment": f"Segment {letter}",
                    "cares_about": cares_match.group(1).strip() if cares_match else "",
                    "teach": teach_match.group(1).strip() if teach_match else ""
                })

        return segments

    def _extract_content_pillars(self, content: str) -> List[str]:
        """Extract content pillars"""
        pillars = []

        # Match "## 3) Content pillars" or similar
        match = re.search(r'##\s*\d*\)\s*Content pillars.*?\n(.*?)(?=##\s*\d+\)\s*|\Z)', content, re.DOTALL | re.IGNORECASE)
        if match:
            section = match.group(1)
            # Extract numbered list items: "1. **Pillar Name**\n    Description"
            # Match until next numbered item or end of section
            pillar_matches = re.findall(
                r'\d+\.\s+\*\*(.*?)\*\*\s*\n\s+(.*?)(?=\n\s*\n\s*\d+\.|\Z)',
                section,
                re.DOTALL
            )

            for title, description in pillar_matches:
                clean_desc = re.sub(r'\s+', ' ', description).strip()
                pillars.append(f"{title.strip()}: {clean_desc}")

        return pillars

    def _extract_weekly_themes(self, content: str) -> List[Dict]:
        """Extract 12-week content plan with weekly themes"""
        themes = []

        # Look for the 12-week content plan section (handle numbered headers like "## 6)")
        match = re.search(r'##\s*\d*\)\s*12-week content plan.*?\n(.*?)(?=##\s*\d+\)\s*|\Z)', content, re.DOTALL | re.IGNORECASE)
        if match:
            section = match.group(1)

            # Extract month sections
            months = re.findall(r'###\s*Month\s+(\d+).*?\n(.*?)(?=###\s*Month|$)', section, re.DOTALL)

            for month_num, month_content in months:
                # Extract weeks within each month
                weeks = re.findall(r'\*\*Week\s+(\d+):\s*(.*?)\*\*\n\n(.*?)(?=\*\*Week\s+\d+|$)', month_content, re.DOTALL)

                for week_num, theme, deliverables in weeks:
                    # Parse deliverables by platform
                    twitter_deliverables = self._parse_platform_deliverables(deliverables, "twitter")
                    linkedin_deliverables = self._parse_platform_deliverables(deliverables, "linkedin")

                    themes.append({
                        "month": int(month_num),
                        "week": int(week_num),
                        "theme": theme.strip(),
                        "twitter": twitter_deliverables,
                        "linkedin": linkedin_deliverables
                    })

        return themes

    def _parse_platform_deliverables(self, deliverables_text: str, platform: str) -> List[str]:
        """Parse deliverables for a specific platform"""
        deliverables = []

        # Look for platform-specific section (Twitter: or LinkedIn:)
        pattern = rf'{platform.title()}:.*?\n\s*[-\*•](.*?)(?=\n\s*[-\*•]|\n\n|\Z)'
        matches = re.findall(pattern, deliverables_text, re.DOTALL | re.IGNORECASE)

        for match in matches:
            # Clean up the deliverable text
            clean = re.sub(r'\s+', ' ', match).strip()
            if clean:
                deliverables.append(clean)

        return deliverables

    def _extract_channel_strategy(self, content: str) -> Dict:
        """Extract channel-specific strategies"""
        strategy = {
            "twitter": {"frequency": "", "best_formats": []},
            "linkedin": {"frequency": "", "best_formats": []}
        }

        match = re.search(r'##\s*Channel strategy.*?\n(.*?)(?=##\s*Operating|\Z)', content, re.DOTALL | re.IGNORECASE)
        if match:
            section = match.group(1)

            # Extract Twitter strategy
            twitter_match = re.search(r'###\s*Twitter.*?\n(.*?)(?=###\s*LinkedIn|$)', section, re.DOTALL | re.IGNORECASE)
            if twitter_match:
                twitter_section = twitter_match.group(1)

                # Extract frequency/cadence
                freq_match = re.search(r'(?:Cadence|frequency).*?:.*?([^\n]+)', twitter_section, re.IGNORECASE)
                if freq_match:
                    strategy["twitter"]["frequency"] = freq_match.group(1).strip()

                # Extract best formats
                formats = re.findall(r'[-\*•]\s+(.*?)(?=\n[-\*•]|\n\n|\Z)', twitter_section)
                strategy["twitter"]["best_formats"] = [f.strip() for f in formats if f.strip() and "Best formats" not in f]

            # Extract LinkedIn strategy
            linkedin_match = re.search(r'###\s*LinkedIn.*?\n(.*?)(?=###\s*|$)', section, re.DOTALL | re.IGNORECASE)
            if linkedin_match:
                linkedin_section = linkedin_match.group(1)

                # Extract frequency/cadence
                freq_match = re.search(r'(?:Cadence|frequency).*?:.*?([^\n]+)', linkedin_section, re.IGNORECASE)
                if freq_match:
                    strategy["linkedin"]["frequency"] = freq_match.group(1).strip()

                # Extract best formats
                formats = re.findall(r'[-\*•]\s+(.*?)(?=\n[-\*•]|\n\n|\Z)', linkedin_section)
                strategy["linkedin"]["best_formats"] = [f.strip() for f in formats if f.strip() and "Best formats" not in f]

        return strategy

    def _get_default_plan(self) -> Dict:
        """Return default plan if file not found"""
        return {
            "marketing_objective": "Build audience and generate leads",
            "positioning": "",
            "audience_segments": [],
            "content_pillars": [
                "Educational content",
                "Behind-the-scenes",
                "Industry insights"
            ],
            "weekly_themes": [
                {
                    "month": 1,
                    "week": 1,
                    "theme": "Introduction",
                    "twitter": ["Intro thread", "Announcement"],
                    "linkedin": ["Introduction post", "Company vision"]
                }
            ],
            "channel_strategy": {
                "twitter": {"frequency": "2-3 posts/day", "best_formats": ["Threads", "Short posts"]},
                "linkedin": {"frequency": "3-4 posts/week", "best_formats": ["Long-form", "Carousels"]}
            },
            "full_content": "# Default Content Plan\n\nNo specific plan found."
        }

    def get_current_week_theme(self, content_plan: Dict) -> Dict:
        """
        Get the current week's theme based on date

        Returns dict with theme info and suggested content types
        """
        # This is a simplified version - in production, you'd calculate
        # based on project start date and current date
        weekly_themes = content_plan.get("weekly_themes", [])

        if not weekly_themes:
            return {
                "theme": "General content",
                "week": 1,
                "suggested_content": []
            }

        # For now, just return the first week
        # In production: week_number = ((current_date - start_date).days // 7) + 1
        current_week = weekly_themes[0]

        return {
            "theme": current_week.get("theme", ""),
            "week": current_week.get("week", 1),
            "month": current_week.get("month", 1),
            "twitter_deliverables": current_week.get("twitter", []),
            "linkedin_deliverables": current_week.get("linkedin", [])
        }
