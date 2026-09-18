#!/usr/bin/env python3
"""
Automated content generation using brand voice, strategies, content plans, and learning patterns
"""
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from typing import Dict, List
import random

from data.models import ContentItem, ContentData, ContentMetadata, ContentReasoning
from services.project_service import ProjectService
from generator.strategy_loader import StrategyLoader
from generator.content_plan_parser import ContentPlanParser


class AutomatedContentGenerator:
    """Generate content automatically based on project configuration"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(Path(__file__).resolve().parent.parent)
        self.base_dir = Path(base_dir)
        self.project_service = ProjectService(data_dir=f"{base_dir}/data")
        self.project_manager = self.project_service
        self.strategy_loader = StrategyLoader(base_dir=base_dir)
        self.plan_parser = ContentPlanParser(base_dir=base_dir)

        # Import LLM generators (try ZAI first, then Anthropic/OpenAI)
        try:
            from generator.zai_content_generator import ZAIContentGenerator
            self.llm_generator = ZAIContentGenerator()
            print("✅ AutomatedGenerator using ZAI GLM-4.7")
        except:
            try:
                from generator.llm_content_generator import LLMContentGenerator
                self.llm_generator = LLMContentGenerator()
                print("✅ AutomatedGenerator using Anthropic/OpenAI")
            except:
                print("⚠️  No LLM generator available, will use template-based approach")
                self.llm_generator = None

    def generate_batch_for_project(
        self,
        project_id: str,
        platform: str,
        count: int = 5
    ) -> List[ContentItem]:
        """
        Generate a batch of content for a specific project and platform

        Args:
            project_id: Project to generate content for
            platform: 'linkedin' or 'twitter'
            count: Number of content items to generate

        Returns:
            List of ContentItem objects
        """
        # Load project
        project = self.project_manager.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Load brand voice and content plan
        brand_voice = self.project_manager.load_brand_voice(project_id)
        content_plan_dict = self.project_manager.load_content_plan(project_id)
        content_plan = self.plan_parser.parse_content_plan(project.settings.content_plan_path)

        # Load platform strategy
        strategy = self.strategy_loader.load_strategy(platform)

        # Get current week's theme
        weekly_theme = self.plan_parser.get_current_week_theme(content_plan)

        # Load learning patterns (if any exist)
        learning_patterns = self._load_learning_patterns(project_id)

        # Generate content items
        items = []
        for i in range(count):
            item = self._generate_single_item(
                project=project,
                platform=platform,
                brand_voice=brand_voice,
                content_plan=content_plan,
                strategy=strategy,
                weekly_theme=weekly_theme,
                learning_patterns=learning_patterns,
                index=i
            )
            items.append(item)

        return items

    def _generate_single_item(
        self,
        project,
        platform: str,
        brand_voice: str,
        content_plan: Dict,
        strategy: Dict,
        weekly_theme: Dict,
        learning_patterns: Dict,
        index: int
    ) -> ContentItem:
        """Generate a single content item"""

        # Select content type based on platform and weekly plan
        content_type, hook_type = self._select_content_type(platform, weekly_theme, index)

        # Build generation prompt
        prompt = self._build_generation_prompt(
            project=project,
            platform=platform,
            content_type=content_type,
            hook_type=hook_type,
            brand_voice=brand_voice,
            strategy=strategy,
            weekly_theme=weekly_theme,
            learning_patterns=learning_patterns
        )

        # Generate content using LLM
        if self.llm_generator:
            generated_content = self._generate_with_llm(prompt, content_type, platform)
        else:
            generated_content = self._generate_template_based(content_type, platform, project)

        # Create content item
        item = ContentItem(
            project_id=project.project_id,
            platform=platform,
            content_type=content_type,
            status="pending_review",
            content=ContentData(
                text=generated_content["text"],
                metadata=ContentMetadata(
                    hook_type=hook_type,
                    pillar=random.choice(content_plan.get("content_pillars", ["General"])),
                    target_audience=self._select_target_audience(content_plan)
                )
            ),
            reasoning=ContentReasoning(
                strategy=f"Based on {platform} strategy and weekly theme: {weekly_theme.get('theme', '')}",
                target_audience=self._select_target_audience(content_plan),
                key_points=generated_content.get("key_points", [])
            )
        )

        return item

    def _select_content_type(self, platform: str, weekly_theme: Dict, index: int) -> tuple:
        """Select content type and hook type based on platform and weekly plan"""
        if platform == "twitter":
            content_types = ["thread", "post", "diagram"]
            hook_types = ["curiosity", "value", "story", "contrarian", "hot_take"]
        else:  # linkedin
            content_types = ["long_form", "carousel", "field_note"]
            hook_types = ["curiosity", "value", "story", "contrarian", "behind_scenes"]

        # Use weekly theme deliverables if available
        if platform == "twitter" and weekly_theme.get("twitter_deliverables"):
            deliverables = weekly_theme["twitter_deliverables"]
            if index < len(deliverables):
                deliverable = deliverables[index]
                if "thread" in deliverable.lower():
                    return "thread", "curiosity"
                elif "diagram" in deliverable.lower():
                    return "diagram", "value"
        elif platform == "linkedin" and weekly_theme.get("linkedin_deliverables"):
            deliverables = weekly_theme["linkedin_deliverables"]
            if index < len(deliverables):
                deliverable = deliverables[index]
                if "carousel" in deliverable.lower():
                    return "carousel", "educational"
                elif "long-form" in deliverable.lower():
                    return "long_form", "story"

        # Fallback to random selection
        return random.choice(content_types), random.choice(hook_types)

    def _build_generation_prompt(
        self,
        project,
        platform: str,
        content_type: str,
        hook_type: str,
        brand_voice: str,
        strategy: Dict,
        weekly_theme: Dict,
        learning_patterns: Dict
    ) -> str:
        """Build comprehensive prompt for LLM content generation"""

        prompt = f"""Generate a {content_type} for {platform}.

# PROJECT CONTEXT
Name: {project.name}
Description: {project.description}
Positioning: {project.settings.brand_voice_path}

# BRAND VOICE
{brand_voice[:2000]}  # First 2000 chars to avoid token limits

# PLATFORM STRATEGY
Platform: {platform}
Tone Guidelines: {strategy.get('tone_guidelines', 'Professional and engaging')}

Anti-Patterns (What to Avoid):
{chr(10).join(f"- {pattern}" for pattern in strategy.get('anti_patterns', [])[:5])}

Proven Formats:
{chr(10).join(f"- {fmt.get('title', '')}" for fmt in strategy.get('proven_formats', [])[:3])}

# WEEKLY THEME
Week {weekly_theme.get('week', 1)}: {weekly_theme.get('theme', 'General content')}

# LEARNING PATTERNS
{self._format_learning_patterns(learning_patterns)}

# REQUIREMENTS
Content Type: {content_type}
Hook Type: {hook_type}
Platform: {platform}

# INSTRUCTIONS
1. Write in the brand voice specified above
2. Follow the platform strategy (tone, format, style)
3. Address the weekly theme
4. Incorporate lessons from learning patterns (what works and what to avoid)
5. Make it specific and actionable, not generic
6. Include concrete examples or data points where relevant
7. {self._get_content_type_instructions(content_type)}

Output the content in a clear, ready-to-post format.
"""

        return prompt

    def _format_learning_patterns(self, patterns: Dict) -> str:
        """Format learning patterns for prompt"""
        if not patterns or not patterns.get("patterns"):
            return "No learning patterns available yet."

        effective = [p for p in patterns["patterns"].values() if p.get("effectiveness_score", 0) > 0.7]
        avoid = [p for p in patterns["patterns"].values() if p.get("effectiveness_score", 0) < 0.3]

        output = []
        if effective:
            output.append("What Works:")
            for pattern in effective[:3]:
                output.append(f"  ✓ {pattern.get('pattern', '')} (score: {pattern.get('effectiveness_score', 0):.0%})")

        if avoid:
            output.append("\nWhat to Avoid:")
            for pattern in avoid[:3]:
                output.append(f"  ✗ {pattern.get('pattern', '')}")

        return "\n".join(output) if output else "No learning patterns available yet."

    def _get_content_type_instructions(self, content_type: str) -> str:
        """Get specific instructions for content type"""
        instructions = {
            "thread": "Write a 6-10 tweet thread. Each tweet should be self-contained but build on previous ones. End with a summary or CTA.",
            "post": "Write a single, impactful post. Keep it under 280 characters for Twitter.",
            "diagram": "Write a post that describes a simple diagram or architecture sketch. Include the diagram description in the content.",
            "long_form": "Write a 400-900 word post. Use clear structure with headers. Tell a story or share a framework.",
            "carousel": "Write content for an 8-12 slide carousel. Each slide should have one clear idea. Include slide descriptions.",
            "field_note": "Write a short, direct field note (200-300 words). Share a specific lesson or observation."
        }
        return instructions.get(content_type, "Write engaging content.")

    def _generate_with_llm(self, prompt: str, content_type: str, platform: str) -> Dict:
        """Generate content using LLM"""
        # This would call the LLM generator
        # For now, return placeholder
        return {
            "text": f"[Generated {content_type} for {platform} based on prompt]",
            "key_points": ["Point 1", "Point 2", "Point 3"]
        }

    def _generate_template_based(self, content_type: str, platform: str, project) -> Dict:
        """Fallback template-based generation"""
        templates = {
            "thread": f"🧵 Thread about {project.name}\n\n1/ Starting point...\n\n2/ Key insight...\n\n3/ Takeaway...",
            "post": f"Quick update on {project.name}...",
            "long_form": f"# {project.name} Update\n\n## Context\n\n## What We Learned\n\n## What's Next"
        }

        return {
            "text": templates.get(content_type, f"Content for {project.name}"),
            "key_points": []
        }

    def _select_target_audience(self, content_plan: Dict) -> str:
        """Select target audience from content plan"""
        segments = content_plan.get("audience_segments", [])
        if segments:
            return random.choice(segments).get("segment", "General")
        return "General"

    def _load_learning_patterns(self, project_id: str) -> Dict:
        """Load learning patterns for a project via ProjectService (KV-first)."""
        return self.project_service.get_learning_patterns(project_id)
