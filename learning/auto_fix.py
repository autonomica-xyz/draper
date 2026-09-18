#!/usr/bin/env python3
"""
Auto-fix engine for improving content based on feedback
"""
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import re
from typing import Dict


_METADATA_PATTERN = re.compile(
    r'^(Platform|Content Type|Content Pillar|Hook Type|'
    r'PLATFORM|CONTENT TYPE|CONTENT PILLAR|HOOK TYPE|'
    r'LEARNING PATTERNS|What Works|What to Avoid)\s*:',
    re.IGNORECASE
)


def _clean_content(text: str) -> str:
    """Strip prompt metadata lines echoed back by the LLM"""
    lines = text.strip().splitlines()
    cleaned = []
    started = False
    for line in lines:
        stripped = line.strip()
        if not started:
            if not stripped or _METADATA_PATTERN.match(stripped):
                continue
            started = True
        cleaned.append(line)
    return '\n'.join(cleaned).strip()


class AutoFixEngine:
    """Automatically fix content based on feedback using AI"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(Path(__file__).resolve().parent.parent)
        self.base_dir = Path(base_dir)

        # Try to import LLM generators
        try:
            from generator.zai_content_generator import ZAIContentGenerator
            self.llm_generator = ZAIContentGenerator()
            self.llm_available = True
        except:
            try:
                from generator.llm_content_generator import LLMContentGenerator
                self.llm_generator = LLMContentGenerator()
                self.llm_available = True
            except:
                self.llm_available = False
                print("⚠️  No LLM generator available for auto-fix")

    async def fix_content(
        self,
        post_data: Dict,
        feedback: str,
        project_id: str
    ) -> Dict:
        """
        Fix content based on feedback

        Args:
            post_data: Original content data
            feedback: User feedback on what needs fixing
            project_id: Project ID (for loading brand voice)

        Returns:
            Dict with:
            - content: Fixed content text
            - explanation: What was changed
        """
        original_content = post_data.get("content", "")
        platform = post_data.get("platform", "twitter")
        content_type = post_data.get("content_type", "post")

        # Load brand voice
        from projects.manager import ProjectManager
        pm = ProjectManager()
        project = pm.get_project(project_id)

        brand_voice = ""
        if project:
            try:
                brand_voice = pm.get_brand_voice(project_id)
            except:
                pass

        # Build fix prompt
        prompt = self._build_fix_prompt(
            original_content,
            feedback,
            platform,
            content_type,
            brand_voice
        )

        # Generate fixed content
        if self.llm_available:
            fixed_content = await self._generate_fix(prompt)
        else:
            fixed_content = self._apply_rule_based_fix(original_content, feedback)

        # Generate explanation
        explanation = self._generate_explanation(original_content, fixed_content, feedback)

        return {
            "content": _clean_content(fixed_content),
            "explanation": explanation
        }

    def _build_fix_prompt(
        self,
        content: str,
        feedback: str,
        platform: str,
        content_type: str,
        brand_voice: str
    ) -> str:
        """Build prompt for LLM to fix content"""
        return f"""You are an expert content editor. Fix the following {content_type} for {platform} based on feedback.

# ORIGINAL CONTENT
{content}

# FEEDBACK
{feedback}

# BRAND VOICE GUIDELINES
{brand_voice[:1000] if brand_voice else "Professional but conversational"}

# INSTRUCTIONS
1. Address the feedback directly
2. Maintain the brand voice
3. Keep the core message intact
4. Make specific, actionable improvements
5. Don't change the format/type (thread stays a thread, etc.)
6. For hooks: Make them more compelling, specific, or curiosity-driven
7. For length: Cut fluff while keeping substance
8. For generic content: Add specific examples, data, or details
9. For tone: Make it more natural and human-sounding

Output ONLY the fixed content text. Do not include labels like "Platform:" or "Content Type:".
"""

    async def _generate_fix(self, prompt: str) -> str:
        """Generate fixed content using LLM"""
        try:
            if hasattr(self.llm_generator, "generate_text"):
                return self.llm_generator.generate_text(prompt, max_tokens=1200)
            if hasattr(self.llm_generator, "_call_llm"):
                return self.llm_generator._call_llm(prompt, max_tokens=1200)
            if hasattr(self.llm_generator, "_call_zai"):
                return self.llm_generator._call_zai(prompt, max_tokens=1200)
            raise AttributeError("Generator does not expose a text-generation method")
        except Exception as e:
            print(f"LLM fix failed: {e}")
            # Fallback to rule-based
            return prompt.split("ORIGINAL CONTENT")[-1].split("# FEEDBACK")[0].strip()

    def _apply_rule_based_fix(self, content: str, feedback: str) -> str:
        """Apply rule-based fixes when LLM not available"""
        lines = content.split('\n')
        feedback_lower = feedback.lower()

        # Rule: Weak hook
        if "hook" in feedback_lower or "opening" in feedback_lower:
            if lines and len(lines[0]) < 100:
                # Try to make the hook more engaging
                first_line = lines[0]
                if '?' not in first_line:
                    lines[0] = first_line + "?"

        # Rule: Too long
        if "too long" in feedback_lower or "verbose" in feedback_lower:
            # Remove empty lines and shorten
            lines = [line for line in lines if line.strip()]
            if len(lines) > 10:
                lines = lines[:8]  # Keep first 8 lines

        # Rule: Generic
        if "generic" in feedback_lower or "specific" in feedback_lower:
            # Add specific details (placeholder)
            for i, line in enumerate(lines):
                if "example" in line.lower() or "thing" in line.lower():
                    lines[i] = line.replace("thing", "specific example").replace("things", "specific examples")

        return '\n'.join(lines)

    def _generate_explanation(self, original: str, fixed: str, feedback: str) -> str:
        """Generate explanation of what was fixed"""
        changes = []

        # Check for hook changes
        orig_first = original.split('\n')[0] if original else ""
        fixed_first = fixed.split('\n')[0] if fixed else ""
        if orig_first != fixed_first:
            changes.append("Improved hook/opening for better engagement")

        # Check for length changes
        if len(original) > len(fixed) * 1.2:
            changes.append("Shortened content for conciseness")
        elif len(fixed) > len(original) * 1.2:
            changes.append("Expanded content with more details")

        # Check based on feedback
        if "hook" in feedback.lower():
            changes.append("Strengthened hook based on feedback")
        if "generic" in feedback.lower():
            changes.append("Added specific details and examples")
        if "tone" in feedback.lower():
            changes.append("Adjusted tone to match brand voice")

        if not changes:
            changes.append("Applied refinements based on feedback")

        return " | ".join(changes)
