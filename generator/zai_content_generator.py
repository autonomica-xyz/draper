#!/usr/bin/env python3
"""
ZAI-Powered Content Generator for Draper Marketing Pipeline
Uses ZAI's GLM-4.7 model (same as what powers this agent)
"""

import os
import json
import random
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional
from pathlib import Path


class ZAIContentGenerator:
    """Generates social media content using ZAI's GLM-4.7 model"""

    def __init__(self, strategies_path: str = None, project=None):
        if strategies_path is None:
            strategies_path = str(Path(__file__).resolve().parent.parent)
        self.strategies_path = Path(strategies_path)
        self.project = project

        # Global draper_* strategy docs are Draper-brand only.
        self.twitter_strategy = ""
        self.linkedin_strategy = ""
        self.marketing_plan = ""
        self._draper_strategies_loaded = False
        self._loaded_strategy_filenames: list[str] = []
        if self._is_draper_project():
            self._ensure_draper_strategies()

        # ZAI API configuration - Try multiple endpoints
        self.api_key = self._load_zai_key()
        if not self.api_key:
            raise ValueError("No ZAI API key found. Set ZAI_API_KEY environment variable.")

        # ZAI/GLM API endpoints in priority order
        self.api_endpoints = [
            "https://open.bigmodel.cn/api/paas/v4",  # GLM official (most reliable)
            "https://api.openai-sb.com/v1",
            "https://api.zai.ai/v1",
        ]

        self.model = "glm-4.7"  # GLM-4.7 model

        self.content_pillars = [
            "radical_transparency",
            "production_engineering",
            "educational",
            "behind_the_scenes",
            "industry_insights"
        ]

    def _load_learning_patterns(self) -> Dict:
        """Load learning patterns for the current project"""
        if not self.project:
            return {}

        try:
            project_dir = Path(self.project.settings.content_plan_path).parent
            patterns_file = project_dir / "learning_patterns.json"

            if patterns_file.exists():
                with open(patterns_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load learning patterns: {e}")

        return {}

    def _format_learning_patterns(self, patterns: Dict) -> str:
        """Format learning patterns for prompt injection"""
        if not patterns or not patterns.get("patterns"):
            return ""

        effective = [p for p in patterns["patterns"].values() if p.get("effectiveness_score", 0) > 0.7]
        avoid = [p for p in patterns["patterns"].values() if p.get("effectiveness_score", 0) < 0.3]

        output = []
        if effective:
            output.append("What Works:")
            for pattern in effective[:5]:
                output.append(f"  - {pattern.get('pattern', '')} (score: {pattern.get('effectiveness_score', 0):.0%})")

        if avoid:
            output.append("\nWhat to Avoid:")
            for pattern in avoid[:5]:
                output.append(f"  - {pattern.get('pattern', '')}")

        return "\n".join(output) if output else ""

    def _clean_content(self, content: str) -> str:
        """Strip prompt metadata lines echoed back by the LLM"""
        import re
        lines = content.strip().splitlines()
        cleaned = []
        started = False
        metadata_pattern = re.compile(
            r'^(Platform|Content Type|Content Pillar|Hook Type|'
            r'PLATFORM|CONTENT TYPE|CONTENT PILLAR|HOOK TYPE|'
            r'LEARNING PATTERNS|What Works|What to Avoid)\s*:', re.IGNORECASE
        )
        for line in lines:
            stripped = line.strip()
            if not started:
                if not stripped or metadata_pattern.match(stripped):
                    continue
                started = True
            cleaned.append(line)
        return '\n'.join(cleaned).strip()

    def _load_zai_key(self) -> str:
        """Load ZAI API key from environment or auth profiles"""
        # Check environment variable first
        env_key = os.getenv("ZAI_API_KEY", "")
        if env_key:
            return env_key

        # Fallback to auth profiles
        try:
            auth_file = Path.home() / ".clawdbot" / "agents" / "main" / "agent" / "auth-profiles.json"
            if auth_file.exists():
                with open(auth_file, 'r') as f:
                    data = json.load(f)
                    for profile_name, profile in data.get('profiles', {}).items():
                        if profile.get('provider') == 'zai':
                            return profile.get('key', '')
        except Exception as e:
            print(f"Warning: Could not load ZAI API key: {e}")

        return ""

    def _load_strategy_file(self, filename: str) -> str:
        """Load marketing strategy markdown file"""
        filepath = self.strategies_path / filename
        if filepath.exists():
            loaded = getattr(self, "_loaded_strategy_filenames", None)
            if loaded is None:
                self._loaded_strategy_filenames = []
                loaded = self._loaded_strategy_filenames
            if filename not in loaded:
                loaded.append(filename)
            with open(filepath, 'r') as f:
                return f.read()
        return ""

    def _is_draper_project(self) -> bool:
        """True only when the bound project is the Draper brand."""
        if not self.project:
            return False
        for obj in (
            self.project,
            getattr(self.project, "config", None),
            getattr(self.project, "settings", None),
        ):
            if obj is None:
                continue
            if isinstance(obj, dict):
                if "use_draper_strategy" in obj:
                    return bool(obj["use_draper_strategy"])
            else:
                flag = getattr(obj, "use_draper_strategy", None)
                if flag is not None:
                    return bool(flag)
        for attr in ("slug", "project_id", "name"):
            raw = str(getattr(self.project, attr, "") or "").strip().lower()
            if not raw:
                continue
            if raw == "draper" or raw.startswith("draper-") or raw.startswith("draper_"):
                return True
            if attr == "name" and (raw == "draper" or raw.startswith("draper ")):
                return True
        return False

    def _ensure_draper_strategies(self) -> None:
        if self._draper_strategies_loaded:
            return
        self.twitter_strategy = self._load_strategy_file("draper_twitter_strategy.md")
        self.linkedin_strategy = self._load_strategy_file("draper_linkedin_strategy.md")
        self.marketing_plan = self._load_strategy_file("draper_marketing_plan_enhanced.md")
        self._draper_strategies_loaded = True

    def _project_display_name(self) -> str:
        if not self.project:
            return "this brand"
        name = getattr(self.project, "name", None)
        if name:
            return str(name)
        slug = getattr(self.project, "slug", None)
        if slug:
            return str(slug)
        return "this brand"

    def _load_project_content_plan(self) -> str:
        if not self.project:
            return ""
        project_id = getattr(self.project, "project_id", None)
        if not project_id:
            return ""
        try:
            from projects.manager import ProjectManager
            pm = ProjectManager()
            content = pm.get_content_plan(project_id)
            if content and content.strip():
                return content.strip()
        except Exception:
            pass
        plan_path = self.strategies_path / "data" / "projects" / project_id / "content_plan.md"
        if plan_path.exists():
            try:
                return plan_path.read_text().strip()
            except Exception:
                pass
        return ""

    def _brand_context_block(self) -> str:
        """Project-scoped framing; never inject Draper product copy for other brands."""
        if self._is_draper_project():
            return (
                "You are a content creator for Draper, an AI-powered autonomous agent platform.\n\n"
                "CONTEXT ABOUT DRAPER:\n"
                "- We build autonomous AI agents that run businesses\n"
                "- Key focus: building in public, radical transparency, technical excellence\n"
                "- Target audience: AI researchers, founders, developers, tech enthusiasts\n"
                "- Tone: authentic, technical but accessible, not corporate"
            )
        name = self._project_display_name()
        return (
            f"You write social content for {name}.\n\n"
            "CONTEXT:\n"
            "- Follow the brand voice guidelines and content plan for this project.\n"
            "- Do not invent a different product, company, or audience.\n"
            "- Do not write about unrelated products (including generic AI-agent platforms) "
            "unless the brand voice says so."
        )

    def _default_topic(self) -> str:
        if self._is_draper_project():
            return "AI agents/autonomous systems"
        return "themes from the brand guidelines and content plan"

    def _call_zai(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call ZAI API with prompt"""

        if not self.api_key:
            raise ValueError("No ZAI API key found")

        # Try each endpoint until one works
        last_error = None
        for endpoint in self.api_endpoints:
            try:
                url = f"{endpoint}/chat/completions"
                print(f"Trying endpoint: {endpoint}")

                headers = {
                    "Content-Type": "application/json"
                }

                # Zhipu/ZAI uses different auth format
                if "open.bigmodel.cn" in endpoint:
                    # Zhipu format uses Bearer with API key
                    headers["Authorization"] = f"Bearer {self.api_key}"
                elif "api.openai-sb.com" in endpoint:
                    # OpenAI-SB format
                    headers["Authorization"] = f"Bearer {self.api_key}"
                else:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.7
                }

                print(f"  Sending request with model: {self.model}")

                response = requests.post(url, headers=headers, json=payload, timeout=60)
                print(f"  Response status: {response.status_code}")

                response.raise_for_status()

                result = response.json()
                print(f"  Response structure: {list(result.keys())}")

                # Handle different response formats
                if "choices" in result:
                    return result["choices"][0]["message"]["content"]
                elif "data" in result and "choices" in result["data"]:
                    return result["data"]["choices"][0]["message"]["content"]
                else:
                    return str(result)

            except requests.exceptions.RequestException as e:
                last_error = e
                print(f"  ❌ Failed: {e}")
                continue
            except Exception as e:
                last_error = e
                print(f"  ❌ Error: {e}")
                continue

        # All endpoints failed
        error_msg = "All ZAI endpoints failed. ZAI API may not be accessible from this environment.\n\n"
        error_msg += f"Last error: {last_error}\n\n"
        error_msg += "SOLUTION: Use Anthropic or OpenAI instead:\n"
        error_msg += "  export ANTHROPIC_API_KEY='your-anthropic-api-key'\n"
        error_msg += "  # or\n"
        error_msg += "  export OPENAI_API_KEY='your-openai-api-key'\n"
        error_msg += "Then the system will automatically use those instead."
        raise ValueError(error_msg)

    def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        """Generate arbitrary text through the configured ZAI provider."""
        return self._call_zai(prompt, max_tokens=max_tokens)

    def generate_twitter_post(
        self,
        pillar: Optional[str] = None,
        hook_type: Optional[str] = None,
        topic: Optional[str] = None
    ) -> Dict:
        """Generate a Twitter/X post using ZAI GLM-4.7

        Args:
            pillar: Content pillar (radical_transparency, production_engineering, etc.)
            hook_type: Type of hook (curiosity, story, value, contrarian)
            topic: Specific topic to focus on

        Returns:
            Dict with generated content and metadata
        """
        # Random selections if not specified
        if not pillar:
            pillar = random.choice(self.content_pillars)
        if not hook_type:
            hook_type = random.choice(["curiosity", "story", "value", "contrarian"])

        # Build prompt
        prompt = self._build_twitter_prompt(pillar, hook_type, topic)

        # Generate content
        content = self._call_zai(prompt, max_tokens=1500)

        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "twitter",
            "content_type": "thread",
            "pillar": pillar,
            "hook_type": hook_type,
            "topic": topic or self._extract_topic(content),
            "content": self._clean_content(content),
            "suggested_actions": [
                "Review content for accuracy and tone",
                "Add specific metrics or data points if applicable",
                "Check that hook matches the project brand voice",
                "Ensure thread flows logically between tweets"
            ],
            "generated_at": generated_at
        }

    def _build_twitter_prompt(
        self,
        pillar: str,
        hook_type: str,
        topic: Optional[str]
    ) -> str:
        """Build prompt for Twitter content generation"""

        strategy_context = self._extract_strategy_context(pillar, "twitter")

        # Load and format learning patterns
        learning_patterns = self._load_learning_patterns()
        learning_section = self._format_learning_patterns(learning_patterns)
        learning_block = f"\nLEARNING PATTERNS:\n{learning_section}\n" if learning_section else ""

        prompt = f"""{self._brand_context_block()}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}
{strategy_context}

HOOK TYPE: {hook_type.upper()}
{learning_block}
TASK: Generate a Twitter/X thread (6-8 tweets total) about {topic or self._default_topic()}.

REQUIREMENTS:
1. Start with a strong {hook_type} hook (first tweet)
2. Write 5-7 follow-up tweets that build narrative
3. Each tweet should be under 280 characters (on average)
4. End with a clear CTA (follow, save, share)
5. Make it specific and actionable - no vague statements
6. Include real examples or technical insights when possible
7. Use appropriate emoji sparingly
8. NO placeholders like "[X]" or fill-in-the-blank - write COMPLETE content
9. Each tweet should stand on its own but connect to the narrative

FORMAT: Return ONLY the thread content, tweet by tweet, with clear line breaks between tweets.

Examples of good hooks for {hook_type}:
"""

        # Add hook examples
        hook_examples = self._get_hook_examples(hook_type)
        prompt += "\n" + "\n".join(f"- {ex}" for ex in hook_examples)

        return prompt

    def generate_linkedin_post(
        self,
        pillar: Optional[str] = None,
        content_type: str = "story_post",
        topic: Optional[str] = None
    ) -> Dict:
        """Generate a LinkedIn post using ZAI GLM-4.7

        Args:
            pillar: Content pillar
            content_type: story_post, how_to, contrarian_take
            topic: Specific topic to focus on

        Returns:
            Dict with generated content and metadata
        """
        # Random selections if not specified
        if not pillar:
            pillar = random.choice(self.content_pillars)

        # Build prompt
        prompt = self._build_linkedin_prompt(pillar, content_type, topic)

        # Generate content
        content = self._call_zai(prompt, max_tokens=2000)

        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "linkedin",
            "content_type": content_type,
            "pillar": pillar,
            "hook_type": "story",
            "topic": topic or self._extract_topic(content),
            "content": self._clean_content(content),
            "suggested_actions": [
                "Ensure professional yet conversational tone",
                "Add line breaks for readability (under 300 chars per line)",
                "Include specific examples or data points",
                "Add relevant hashtag(s) at end"
            ],
            "generated_at": generated_at
        }

    def _build_linkedin_prompt(
        self,
        pillar: str,
        content_type: str,
        topic: Optional[str]
    ) -> str:
        """Build prompt for LinkedIn content generation"""

        strategy_context = self._extract_strategy_context(pillar, "linkedin")

        # Load and format learning patterns
        learning_patterns = self._load_learning_patterns()
        learning_section = self._format_learning_patterns(learning_patterns)
        learning_block = f"\nLEARNING PATTERNS:\n{learning_section}\n" if learning_section else ""

        prompt = f"""{self._brand_context_block()}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}
{strategy_context}

CONTENT TYPE: {content_type}
{learning_block}
TASK: Generate a LinkedIn post about {topic or self._default_topic()}.

REQUIREMENTS:
1. Start with a compelling hook or story (first 2-3 lines are critical)
2. Use short paragraphs (1-3 sentences max per paragraph)
3. Include at least 2-3 line breaks for readability
4. End with a clear CTA or question to drive engagement
5. Be specific and actionable - no vague statements
6. Include real examples, metrics, or technical insights
7. Professional tone but avoid corporate buzzwords
8. Length: 500-1500 characters (optimal for LinkedIn)
9. NO placeholders like "[X]" - write COMPLETE content

FORMAT: Return ONLY the LinkedIn post content."""

        return prompt

    def _extract_strategy_context(self, pillar: str, platform: str) -> str:
        """Extract strategy context; draper_* files only for Draper brand."""
        if self._is_draper_project():
            self._ensure_draper_strategies()
            strategy_doc = self.twitter_strategy if platform == "twitter" else self.linkedin_strategy
        else:
            strategy_doc = self._load_project_content_plan()

        if not strategy_doc:
            if self._is_draper_project():
                return "No specific strategy context available."
            return "Use the project's brand voice and content plan. Do not invent unrelated products."

        # Extract sections relevant to pillar
        pillar_mentions = []
        lines = strategy_doc.split('\n')

        for i, line in enumerate(lines):
            if pillar.lower() in line.lower():
                # Include this line and next 3-5 lines for context
                context_lines = lines[i:min(i + 200, len(lines))]
                context_text = '\n'.join(context_lines[:400])
                pillar_mentions.append(context_text)
                break  # Just get one relevant section

        if pillar_mentions:
            return f"\nStrategy Context:\n{pillar_mentions[0][:800]}\n"

        return "Use general best practices for this pillar."

    def _get_hook_examples(self, hook_type: str) -> List[str]:
        """Get example hooks; Draper/AI-agent phrasing only for Draper brand."""
        if not self._is_draper_project():
            generic = {
                "curiosity": [
                    "I've been wrong about our content process for 2 years.",
                    "The real reason campaigns fail isn't the channel.",
                    "We cut our review cycle in half last month.",
                    "Nobody talks about message consistency enough.",
                ],
                "story": [
                    "Last week a draft almost went out with the wrong brand voice.",
                    "I almost killed our best-performing series 3 months ago.",
                    "Two years ago I thought more posts meant more pipeline.",
                    "A customer reply changed how we talk about the product.",
                ],
                "value": [
                    "How to tighten your content review loop (5 steps):",
                    "3 patterns that make publishing reliable:",
                    "The simplest way to catch off-brand drafts:",
                    "Stop optimizing for volume. Use this instead:",
                ],
                "contrarian": [
                    "Unpopular opinion: more content is not a strategy.",
                    "Channel expansion is wrong for most early teams.",
                    "I stopped chasing virality and got better results.",
                    "Most teams don't need another tool — they need clearer messaging.",
                ],
            }
            return generic.get(hook_type, [])

        examples = {
            "curiosity": [
                "I've been wrong about AI agents for 2 years.",
                "The real reason agents fail isn't hallucinations.",
                "We cut our token costs by 97% yesterday.",
                "Nobody talks about agent memory leaks."
            ],
            "story": [
                "Last week our agent deleted our production database.",
                "I almost shut down Draper 3 months ago.",
                "Two years ago I thought AI was a buzzword.",
                "Our first user found a critical bug that changed everything."
            ],
            "value": [
                "How to build your first autonomous agent (5 steps):",
                "3 patterns that make agents reliable:",
                "The simplest way to debug AI agent failures:",
                "Stop using chains of thought. Use this instead:"
            ],
            "contrarian": [
                "Unpopular opinion: AI agents are overhyped.",
                "RAG is wrong for most use cases.",
                "I stopped using GPT-4 and got better results.",
                "Most companies don't need AI agents yet."
            ]
        }
        return examples.get(hook_type, [])

    def _extract_topic(self, content: str) -> str:
        """Extract a topic from generated content"""
        first_line = content.split('\n')[0]
        # Remove emoji and special chars
        topic = first_line[:50].strip()
        return topic

    def generate_batch(
        self,
        count: int = 10,
        platforms: Optional[List[str]] = None,
        pillars: Optional[List[str]] = None
    ) -> List[Dict]:
        """Generate a batch of content

        Args:
            count: Number of posts to generate
            platforms: List of platforms (twitter, linkedin)
            pillars: List of pillars to focus on

        Returns:
            List of generated posts
        """
        if not platforms:
            platforms = ["twitter", "linkedin"]

        batch = []
        for i in range(count):
            platform = random.choice(platforms)

            if platform == "twitter":
                pillar = random.choice(pillars) if pillars else None
                post = self.generate_twitter_post(pillar=pillar)
            else:  # linkedin
                pillar = random.choice(pillars) if pillars else None
                post = self.generate_linkedin_post(pillar=pillar)

            batch.append(post)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(batch),
            "posts": batch
        }


def main():
    """CLI for ZAI content generation"""
    import argparse

    parser = argparse.ArgumentParser(description="Generate social media content using ZAI GLM-4.7")
    parser.add_argument("--platform", choices=["twitter", "linkedin", "both"], help="Platform to generate for")
    parser.add_argument("--count", type=int, default=1, help="Number of posts to generate")
    parser.add_argument("--pillar", choices=[
        "radical_transparency", "production_engineering", "educational",
        "behind_the_scenes", "industry_insights"
    ], help="Content pillar")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()

    try:
        generator = ZAIContentGenerator()
        print("🚀 Generating content using ZAI GLM-4.7...")
        print("   (Same model that powers this agent)\n")

        # Generate posts
        if args.platform == "linkedin" or (args.platform == "both" and random.choice([True, False])):
            post = generator.generate_linkedin_post(pillar=args.pillar)
            results = {"posts": [post]}
        else:
            post = generator.generate_twitter_post(pillar=args.pillar)
            results = {"posts": [post]}

        # If count > 1, generate batch
        if args.count > 1:
            platforms = None if args.platform == "both" else [args.platform]
            batch = generator.generate_batch(
                count=args.count,
                platforms=platforms,
                pillars=[args.pillar] if args.pillar else None
            )
            results = batch

        # Output
        print(json.dumps(results, indent=2))

        # Save to file if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\n✅ Saved to {args.output}")

    except ValueError as e:
        print(f"❌ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
