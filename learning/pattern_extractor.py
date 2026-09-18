#!/usr/bin/env python3
"""
Extract learning patterns from content feedback
"""
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from typing import Dict, List
import re

from data.models import LearningPattern


class PatternExtractor:
    """Extract learning patterns from content feedback"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(Path(__file__).resolve().parent.parent)
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"

    def extract_and_save_patterns(
        self,
        post_data: Dict,
        status: str,
        project_id: str,
        feedback: str = "",
        tags: List[str] = None
    ) -> List[LearningPattern]:
        """
        Extract patterns from content based on status

        Args:
            post_data: Content item data
            status: "approved", "needs_work", or "declined"
            project_id: Project ID
            feedback: Optional feedback text
            tags: Optional explicit tags from UI selection

        Returns:
            List of extracted patterns
        """
        content_text = post_data.get("content", "")
        content_type = post_data.get("content_type", "")
        platform = post_data.get("platform", "")
        tags = tags or []

        patterns = []

        if status == "approved":
            # Extract positive patterns
            patterns.extend(self._extract_positive_patterns(content_text, content_type, platform, tags))
        elif status in ["needs_work", "declined"]:
            # Extract negative patterns
            patterns.extend(self._extract_negative_patterns(content_text, content_type, platform, feedback, tags))

        # Save patterns to project
        if patterns and project_id:
            self._save_patterns(project_id, patterns)

        return patterns

    def _extract_positive_patterns(self, content: str, content_type: str, platform: str, tags: List[str] = None) -> List[LearningPattern]:
        """Extract patterns from approved content"""
        patterns = []
        tags = tags or []

        # Extract hook style
        hook_style = self._extract_hook_style(content)
        if hook_style:
            patterns.append(LearningPattern(
                pattern_type="hook_style",
                pattern=hook_style,
                effectiveness_score=1.0,
                sample_size=1,
                success_examples=[],
                failure_examples=[],
                confidence="high" if "great_hook" in tags else "medium"
            ))

        # Extract structure pattern
        structure = self._extract_structure(content, content_type)
        if structure:
            patterns.append(LearningPattern(
                pattern_type="structure",
                pattern=structure,
                effectiveness_score=1.0,
                sample_size=1,
                success_examples=[],
                failure_examples=[],
                confidence="high" if "well_structured" in tags else "medium"
            ))

        # Extract tone pattern
        tone = self._extract_tone(content)
        if tone:
            patterns.append(LearningPattern(
                pattern_type="tone",
                pattern=tone,
                effectiveness_score=1.0,
                sample_size=1,
                success_examples=[],
                failure_examples=[],
                confidence="high" if "on_brand" in tags else "low"
            ))

        # Tag-driven positive patterns
        tag_patterns = {
            "great_hook": "Strong hook that grabs attention",
            "good_length": f"Good length for {content_type} on {platform}",
            "on_brand": "Authentic brand voice alignment",
            "engaging": "Engaging and compelling content",
            "valuable": "Provides valuable insights to audience",
            "well_structured": "Well-structured content flow",
            "clear_cta": "Clear and effective call to action"
        }

        for tag in tags:
            if tag in tag_patterns:
                patterns.append(LearningPattern(
                    pattern_type="positive_pattern",
                    pattern=tag_patterns[tag],
                    effectiveness_score=1.0,
                    sample_size=1,
                    success_examples=[],
                    failure_examples=[],
                    confidence="high"
                ))

        return patterns

    def _extract_negative_patterns(
        self,
        content: str,
        content_type: str,
        platform: str,
        feedback: str,
        tags: List[str] = None
    ) -> List[LearningPattern]:
        """Extract negative patterns from needs_work or declined content"""
        patterns = []
        tags = tags or []

        # Tag-driven negative patterns (from UI selection)
        tag_patterns = {
            "weak_hook": "Weak hook: " + self._extract_hook_style(content),
            "too_generic": "Generic content without specifics",
            "too_long": f"Overly long {content_type}",
            "ai_sounding": "AI-sounding content",
            "no_value": "Content lacks clear value or insight",
            "formatting": f"Poor formatting/structure for {platform}",
            "tone_off": "Tone does not match brand voice",
            "unclear": "Unclear messaging or confusing content"
        }

        # Track which tags have been handled to avoid duplicates
        handled = set()

        # First, add patterns from explicit tags (high confidence)
        for tag in tags:
            if tag in tag_patterns:
                patterns.append(LearningPattern(
                    pattern_type="negative_pattern",
                    pattern=tag_patterns[tag],
                    effectiveness_score=0.0,
                    sample_size=1,
                    success_examples=[],
                    failure_examples=[],
                    confidence="high"
                ))
                handled.add(tag)

        # Then, extract from feedback text for any tags not already covered
        if feedback:
            feedback_lower = feedback.lower()

            feedback_tag_map = {
                "weak_hook": ["hook", "opening", "intro"],
                "too_generic": ["generic", "vague", "not specific"],
                "too_long": ["too long", "verbose", "wordy"],
                "ai_sounding": ["ai", "chatgpt", "robotic", "unnatural"],
                "no_value": ["no value", "pointless", "so what", "lacks insight"],
                "formatting": ["formatting", "hard to read", "layout"],
                "tone_off": ["tone", "voice", "doesn't sound like"],
                "unclear": ["unclear", "confusing", "clarify"]
            }

            for tag_id, keywords in feedback_tag_map.items():
                if tag_id not in handled and any(kw in feedback_lower for kw in keywords):
                    patterns.append(LearningPattern(
                        pattern_type="negative_pattern",
                        pattern=tag_patterns[tag_id],
                        effectiveness_score=0.0,
                        sample_size=1,
                        success_examples=[],
                        failure_examples=[],
                        confidence="medium"
                    ))

        return patterns

    def _extract_hook_style(self, content: str) -> str:
        """Extract the hook pattern from content"""
        if not content:
            return ""

        # Get first line or first sentence
        first_line = content.split('\n')[0].strip()
        first_sentence = content.split('.')[0].strip()

        hook_text = first_line if len(first_line) < 100 else first_sentence

        # Classify hook style
        if '?' in hook_text:
            if "how" in hook_text.lower() or "what" in hook_text.lower() or "why" in hook_text.lower():
                return "question_hook (curiosity-driven)"
            else:
                return "rhetorical_question"
        elif any(word in hook_text.lower() for word in ['unpopular', 'controversial', 'wrong', 'bad']):
            return "contrarian_hook"
        elif any(char.isdigit() for char in hook_text):
            return "numbered_list_hook"
        elif hook_text[0].isupper() and len(hook_text) < 50:
            return "bold_statement_hook"
        else:
            return "narrative_hook"

    def _extract_structure(self, content: str, content_type: str) -> str:
        """Extract content structure pattern"""
        if not content:
            return ""

        lines = [line.strip() for line in content.split('\n') if line.strip()]

        # Check for headers
        has_headers = any(line.startswith('#') for line in lines)

        # Check for bullet points
        has_bullets = any(line.startswith(('-', '•', '*')) for line in lines)

        # Check for numbered lists
        has_numbers = any(bool(re.match(r'^\d+\.', line)) for line in lines)

        # Determine structure
        if content_type == "thread":
            thread_count = len([line for line in lines if len(line) < 280])
            return f"thread_structure ({thread_count} tweets)"
        elif has_headers and has_bullets:
            return "structured_with_headers_bullets"
        elif has_numbers:
            return "numbered_list_structure"
        elif has_bullets:
            return "bullet_point_structure"
        else:
            return "narrative_flow"

    def _extract_tone(self, content: str) -> str:
        """Extract tone pattern from content"""
        if not content:
            return ""

        # Check for tone indicators
        words = content.lower().split()

        # First person usage
        first_person = len([w for w in words if w in ['i', 'i\'m', 'i\'ve', 'my', 'we', 'our']])
        total_words = len(words)

        if total_words > 0 and first_person / total_words > 0.05:
            return "personal_first_person"
        elif any(phrase in content.lower() for phrase in ['data shows', 'according to', 'research indicates']):
            return "analytical_evidence_based"
        elif any(phrase in content.lower() for phrase in ['i think', 'i believe', 'in my opinion']):
            return "opinionated"
        else:
            return "neutral_informational"

    def _save_patterns(self, project_id: str, patterns: List[LearningPattern]):
        """Save patterns to SQLite via ProjectManager"""
        from projects.manager import ProjectManager
        pm = ProjectManager()

        if not pm.get_project(project_id):
            return

        # Load existing patterns
        data = pm.get_learning_patterns(project_id)
        if not data:
            data = {"patterns": {}}

        # Merge new patterns with existing
        for pattern in patterns:
            pattern_key = f"{pattern.pattern_type}_{pattern.pattern[:50]}"
            pattern_dict = pattern.to_dict()

            if pattern_key in data.get("patterns", {}):
                # Update existing pattern
                existing = data["patterns"][pattern_key]
                existing["sample_size"] += 1
                existing["last_updated"] = pattern.last_updated

                # Update effectiveness score (moving average)
                if pattern.effectiveness_score > 0:
                    existing["effectiveness_score"] = (
                        (existing["effectiveness_score"] * (existing["sample_size"] - 1) +
                         pattern.effectiveness_score) / existing["sample_size"]
                    )

                # Add examples
                if pattern.success_examples:
                    existing["success_examples"].extend(pattern.success_examples)
                if pattern.failure_examples:
                    existing["failure_examples"].extend(pattern.failure_examples)
            else:
                # Add new pattern
                data.setdefault("patterns", {})[pattern_key] = pattern_dict

        pm.save_learning_patterns(project_id, data)

    def load_patterns_for_project(self, project_id: str) -> Dict:
        """Load all learning patterns for a project from SQLite"""
        from projects.manager import ProjectManager
        pm = ProjectManager()
        return pm.get_learning_patterns(project_id)
