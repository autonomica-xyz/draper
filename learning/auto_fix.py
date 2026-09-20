#!/usr/bin/env python3
"""
Auto-fix engine for improving content based on feedback

The user's FEEDBACK is the source of truth: when it asks for a rewrite,
report-grounded facts, slide-level corrections, or forbids specific claims,
those are hard constraints. The engine must never silently substitute a
generic engagement/hook rewrite for them, and must never fake success when
no LLM is available to honor them (it raises ``AutoFixSkipped`` instead).
"""
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import re
from typing import Dict, List


_METADATA_PATTERN = re.compile(
    r'^(Platform|Content Type|Content Pillar|Hook Type|'
    r'PLATFORM|CONTENT TYPE|CONTENT PILLAR|HOOK TYPE|'
    r'LEARNING PATTERNS|What Works|What to Avoid)\s*:',
    re.IGNORECASE
)

# Feedback matching any of these patterns is "concrete": it imposes explicit,
# enforceable constraints (rewrites, slide/report-level fact fixes, DO NOT
# claims) that the rule-based fallback cannot honor.
_CONCRETE_FEEDBACK_PATTERN = re.compile(
    r"("
    r"\brewrit(e|es|en|ing)\b|\bredraft\b|\brestructur\w*"
    r"|\bslides?\b|\bcarousels?\b"
    r"|\bfacts?\b|\bfactual(ly)?\b|\binaccura\w*|\bincorrect(ly)?\b"
    r"|\bwrong\b|\bfalse\b|\bmisleading\b|\bhallucinat\w*"
    r"|\breport\b|\bground(ed|ing)?\b|\bunverified\b"
    r"|\bdo\s+not\b|\bdon'?t\b|\bmust\s+not\b|\bshould\s+not\b|\bshouldn'?t\b"
    r"|\bnever\s+(claim|say|mention)\b|\b(cannot|can't)\s+claim\b"
    r"|\bmade?\s*up\b|\bmake\s+up\b"
    r")",
    re.IGNORECASE,
)

# Detailed feedback (this many sentences / characters) counts as concrete even
# without a keyword match: long instructions imply specific constraints.
_CONCRETE_MIN_SENTENCES = 3
_CONCRETE_MIN_CHARS = 240

# Feedback about the hook/opening. Only then may the explanation talk about
# hook changes.
_HOOK_FEEDBACK_KEYWORDS = ("hook", "opening", "opener", "first line", "lede")


class AutoFixSkipped(Exception):
    """Raised when auto-fix must not produce content for the feedback.

    Carries a machine-stable ``reason`` (e.g.
    ``llm_unavailable_concrete_feedback``) so callers (the job runner) can
    log and record the skip on the review without inventing a fake success.
    """

    def __init__(self, reason: str, message: str = None):
        self.reason = reason
        self.message = message or f"Auto-fix skipped: {reason}"
        super().__init__(self.message)


def is_concrete_feedback(feedback: str) -> bool:
    """Return True when feedback carries explicit, enforceable constraints.

    Concrete feedback means: long/detailed instructions, or mentions of
    rewrites, slides/carousels, facts/reports/grounding, or explicit
    DO NOT / MUST NOT claims. Such feedback requires the LLM path — the
    rule-based fallback cannot honor it and must not be allowed to
    silently substitute a generic hook tweak.
    """
    if not feedback or not feedback.strip():
        return False
    text = feedback.strip()
    if _CONCRETE_FEEDBACK_PATTERN.search(text):
        return True
    sentences = [s for s in re.split(r"[.!?]+\s", text) if s.strip()]
    return len(sentences) >= _CONCRETE_MIN_SENTENCES or len(text) >= _CONCRETE_MIN_CHARS


def _first_sentence(text: str, max_len: int = 140) -> str:
    """Return the first sentence of text with collapsed whitespace, truncated."""
    collapsed = " ".join(text.split())
    match = re.match(r"(.+?[.!?])(?:\s|$)", collapsed)
    sentence = match.group(1).strip() if match else collapsed
    if len(sentence) > max_len:
        sentence = sentence[: max_len - 3].rstrip() + "..."
    return sentence


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
        except Exception:
            try:
                from generator.llm_content_generator import LLMContentGenerator
                self.llm_generator = LLMContentGenerator()
                self.llm_available = True
            except Exception:
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
            feedback: User feedback on what needs fixing (the source of truth)
            project_id: Project ID (for loading brand voice)

        Returns:
            Dict with:
            - content: Fixed content text
            - explanation: What was changed (derived from the feedback)

        Raises:
            AutoFixSkipped: If the feedback is concrete (rewrite/fact/structure
                constraints) and no LLM fix could be produced. Callers must
                leave the review in needs_work rather than falling back to
                rule-based hook hacks — that would fake success.
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
            except Exception:
                pass

        # Build fix prompt
        prompt = self._build_fix_prompt(
            original_content,
            feedback,
            platform,
            content_type,
            brand_voice
        )

        fixed_content = None
        llm_error = None
        if self.llm_available:
            try:
                fixed_content = await self._generate_fix(prompt)
            except Exception as e:
                llm_error = str(e)
                print(f"LLM fix failed: {e}")

        if fixed_content is None:
            if is_concrete_feedback(feedback):
                # Concrete feedback (rewrites, slide-level fact fixes, DO NOT
                # claims) can only be honored by the LLM. A rule-based fallback
                # would silently substitute a generic hook tweak and pretend
                # the feedback was addressed.
                raise AutoFixSkipped(
                    reason="llm_unavailable_concrete_feedback",
                    message=(
                        "Auto-fix skipped: feedback is concrete "
                        "(rewrite/fact/structure constraints) and no LLM fix "
                        "was available"
                        + (f" (LLM error: {llm_error})" if llm_error else "")
                        + ". Review left in needs_work."
                    ),
                )
            fixed_content = self._apply_rule_based_fix(original_content, feedback)

        cleaned = _clean_content(fixed_content)
        explanation = self._generate_explanation(original_content, cleaned, feedback)

        return {
            "content": cleaned,
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
        """Build prompt for LLM to fix content.

        The FEEDBACK section is the source of truth: it is included verbatim
        and framed as hard constraints that outrank brand voice and generic
        engagement guidance. Structure (e.g. carousel slides) is preserved
        unless the feedback explicitly says otherwise.
        """
        return f"""You are an expert content editor. Fix the following {content_type} for {platform} based on feedback.

# FEEDBACK (SOURCE OF TRUTH — HARD CONSTRAINTS)
The feedback below is authoritative. Every instruction, restriction, and factual correction in it is a HARD CONSTRAINT that you MUST satisfy exactly:

{feedback}

# ORIGINAL CONTENT
{content}

# BRAND VOICE GUIDELINES (SECONDARY)
Brand voice is SECONDARY to the explicit fact/rewrite constraints in the feedback. Where they conflict, the feedback wins.
{brand_voice[:1000] if brand_voice else "Professional but conversational"}

# HARD RULES
1. OBEY THE FEEDBACK EXACTLY. It overrides every generic rule below.
   - If the feedback asks for a rewrite, actually rewrite the content as instructed — do NOT just polish the hook.
   - If the feedback requires grounding in a report or source, fix the claims at the requested level of detail (including slide-by-slide facts) and remove or qualify anything you cannot ground.
   - If the feedback says "do not" or "must not" claim something, that claim is FORBIDDEN — remove or rewrite it.
2. Do NOT substitute a generic engagement/hook rewrite when the feedback asks for something else.
3. Preserve the existing structure (same number of slides/sections/lines; keep each carousel slide as its own slide) unless the feedback explicitly asks to change the structure.
4. Keep the format/type intact (a thread stays a thread, a carousel stays a carousel).
5. Only where it does not conflict with the feedback: make hooks compelling, cut fluff, add specifics, and keep the tone natural and human-sounding.

Output ONLY the fixed content text. Do not include labels like "Platform:" or "Content Type:".
"""

    async def _generate_fix(self, prompt: str) -> str:
        """Generate fixed content using LLM. Raises on failure.

        Failures propagate to ``fix_content`` so the concrete-feedback skip
        path can trigger. (The previous fallback silently returned the
        original content on error, which faked a successful fix.)
        """
        if hasattr(self.llm_generator, "generate_text"):
            result = self.llm_generator.generate_text(prompt, max_tokens=1200)
        elif hasattr(self.llm_generator, "_call_llm"):
            result = self.llm_generator._call_llm(prompt, max_tokens=1200)
        elif hasattr(self.llm_generator, "_call_zai"):
            result = self.llm_generator._call_zai(prompt, max_tokens=1200)
        else:
            raise AttributeError("Generator does not expose a text-generation method")
        if not result or not str(result).strip():
            raise ValueError("LLM returned an empty fix")
        return str(result)

    def _apply_rule_based_fix(self, content: str, feedback: str) -> str:
        """Apply rule-based fixes when LLM not available.

        Only used for soft/vague feedback — concrete feedback never reaches
        this (``fix_content`` raises ``AutoFixSkipped`` instead).
        """
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
        """Build a short, feedback-anchored explanation of the fix.

        The primary clause is derived from the feedback itself (its first
        sentence), so the explanation reflects the constraints actually
        addressed. Hook observations appear ONLY when the feedback is about
        the hook/opening — never as an invented canned claim. Length
        observations are supplements only.
        """
        feedback = (feedback or "").strip()
        changes: List[str] = []
        feedback_lower = feedback.lower()

        if feedback:
            changes.append(f"Addressed feedback: {_first_sentence(feedback)}")
        else:
            changes.append("Applied refinements based on feedback")

        # Hook notes only when the feedback is actually about the hook.
        if any(keyword in feedback_lower for keyword in _HOOK_FEEDBACK_KEYWORDS):
            orig_first = original.split('\n')[0] if original else ""
            fixed_first = fixed.split('\n')[0] if fixed else ""
            if orig_first != fixed_first:
                changes.append("Hook/opening reworked as requested")

        # Length notes as supplements
        if len(original) > len(fixed) * 1.2:
            changes.append("Shortened content for conciseness")
        elif len(fixed) > len(original) * 1.2:
            changes.append("Expanded content with more details")

        return " | ".join(changes)
