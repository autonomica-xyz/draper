#!/usr/bin/env python3
"""
LLM-Powered Content Generator for Draper Marketing Pipeline
Actually generates real content using OpenAI/Anthropic APIs
"""

import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path to import analytics
sys.path.insert(0, str(Path(__file__).parent.parent))

# Auto-load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        # print(f"Loaded environment from {env_path}")
except ImportError:
    pass  # python-dotenv not installed, will rely on system env vars

import litellm
from litellm import completion
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class LLMContentGenerator:
    """Generates real social media content using LLMs"""

    def __init__(self, strategies_path: str = None, project=None):
        if strategies_path is None:
            strategies_path = str(Path(__file__).resolve().parent.parent)
        self.strategies_path = Path(strategies_path)

        # Load marketing strategies
        self.twitter_strategy = self._load_strategy_file("draper_twitter_strategy.md")
        self.linkedin_strategy = self._load_strategy_file("draper_linkedin_strategy.md")
        self.marketing_plan = self._load_strategy_file("draper_marketing_plan_enhanced.md")

        # Load brand voice skill from knowledge-work-plugins
        self.brand_voice_skill = self._load_brand_voice_skill()

        # Store project reference for brand voice
        self.project = project

        # Per-project LLM override (set by scoped_generator_for_project);
        # None means use the env LLM_MODEL + fallbacks path.
        self.llm_override: Optional[Dict[str, str]] = None

        # Configure LiteLLM
        self._configure_litellm()

        # Track usage and costs
        self.total_tokens_used = 0
        self.total_cost = 0.0
        self.api_call_count = 0

        self.content_pillars = [
            "radical_transparency",
            "production_engineering",
            "educational",
            "behind_the_scenes",
            "industry_insights"
        ]

        # Load analytics-based preferences
        self.analytics_weights = self._load_analytics_weights()
        self.preferences = self._load_preferences()

    def _load_strategy_file(self, filename: str) -> str:
        """Load marketing strategy markdown file"""
        filepath = self.strategies_path / filename
        if filepath.exists():
            with open(filepath, 'r') as f:
                return f.read()
        return ""

    def _load_brand_voice_skill(self) -> str:
        """Load brand voice skill from knowledge-work-plugins"""
        brand_voice_path = self.strategies_path / "knowledge-work-plugins/marketing/skills/brand-voice/SKILL.md"
        if brand_voice_path.exists():
            with open(brand_voice_path, 'r') as f:
                return f.read()
        return ""

    def _load_brand_voice_markdown(self) -> Optional[str]:
        """Load brand voice from SQLite (project_kv), falling back to file.

        Returns:
            The full markdown content if available, None otherwise.
        """
        if not self.project:
            return None

        project_id = self.project.project_id

        # Try SQLite first via ProjectManager
        try:
            from projects.manager import ProjectManager
            pm = ProjectManager()
            content = pm.get_brand_voice(project_id)
            if content and content.strip():
                return content.strip()
        except Exception:
            pass

        # Legacy fallback: file at data/projects/{project_id}/brand_voice.md
        brand_voice_path = self.strategies_path / "data" / "projects" / project_id / "brand_voice.md"
        if brand_voice_path.exists():
            try:
                with open(brand_voice_path, 'r') as f:
                    content = f.read().strip()
                if content:
                    return content
            except Exception as e:
                print(f"Warning: Could not read brand voice markdown: {e}")

        return None

    def _get_brand_voice_context(self, platform: str) -> str:
        """Get brand voice context for LLM prompts

        Priority:
        1. Brand voice from SQLite (project_kv), migrated from markdown files
        2. BrandVoice dataclass from project config (structured fallback)
        3. Brand voice skill doc (generic fallback)

        Args:
            platform: twitter, linkedin, email, etc.

        Returns:
            Brand voice guidelines formatted for prompts
        """
        # First priority: try loading from markdown file
        markdown_content = self._load_brand_voice_markdown()
        if markdown_content:
            return f"\nBRAND VOICE GUIDELINES:\n{markdown_content}\n"

        # Second priority: use structured BrandVoice dataclass from project config
        if self.project and self.project.config.brand_voice:
            bv = self.project.config.brand_voice

            context = "\nBRAND VOICE GUIDELINES:\n"
            context += f"Personality: {', '.join(bv.personality)}\n"

            # Add tone for this platform
            tone = bv.tone_by_channel.get(platform, "")
            if tone:
                context += f"Tone for {platform}: {tone}\n"

            # Add messaging pillars
            if bv.messaging_pillars:
                context += f"Core themes: {', '.join(bv.messaging_pillars)}\n"

            # Add voice attributes if available
            if bv.voice_attributes:
                context += "\nVoice Attributes:\n"
                for attr, details in bv.voice_attributes.items():
                    context += f"- {attr}: {details.get('we_are', '')}\n"

            # Add terminology rules
            if bv.preferred_terms or bv.avoided_terms:
                context += "\nTerminology:\n"
                for preferred, avoid in bv.preferred_terms.items():
                    context += f"- Use '{preferred}' not '{avoid}'\n"
                if bv.avoided_terms:
                    context += f"- Avoid: {', '.join(bv.avoided_terms)}\n"

            # Add style rules
            if bv.style_rules:
                context += "\nStyle Rules:\n"
                for rule, value in bv.style_rules.items():
                    context += f"- {rule}: {value}\n"

            return context

        # Fallback: use brand voice skill doc if available
        if self.brand_voice_skill:
            return "\nBRAND VOICE: Apply consistent brand voice personality and tone across all content.\n"

        return ""

    def _load_learning_patterns(self) -> Dict:
        """Load learning patterns for the current project from SQLite"""
        if not self.project:
            return {}

        try:
            from projects.manager import ProjectManager
            pm = ProjectManager()
            patterns = pm.get_learning_patterns(self.project.project_id)
            return patterns if patterns else {}
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
        # Skip leading lines that look like echoed metadata
        started = False
        metadata_pattern = re.compile(
            r'^(Platform|Content Type|Content Pillar|Hook Type|Hook Pattern|'
            r'Carousel Archetype|PLATFORM|CONTENT TYPE|CONTENT PILLAR|HOOK TYPE|'
            r'HOOK PATTERN|CAROUSEL ARCHETYPE|'
            r'LEARNING PATTERNS|What Works|What to Avoid|'
            r'OUTPUT FORMAT|FORMAT)\s*:', re.IGNORECASE
        )
        for line in lines:
            stripped = line.strip()
            if not started:
                if not stripped or metadata_pattern.match(stripped):
                    continue
                started = True
            cleaned.append(line)
        return '\n'.join(cleaned).strip()

    def _load_analytics_weights(self) -> Dict:
        """Load preference weights from analytics recommendations

        Returns:
            Dict with analytics-based recommendations
        """
        try:
            from data.sqlite_store import SQLiteStore
            data_dir = Path(__file__).resolve().parent.parent / "data"
            store = SQLiteStore(data_dir)

            # Try SQLite first
            recommendations = store.get_project_value("_analytics", "content_recommendations")
            if recommendations:
                print("Loaded analytics recommendations from SQLite")
                return recommendations

            # Legacy fallback: load from file
            recommendations_file = data_dir / "content_recommendations.json"
            if recommendations_file.exists():
                with open(recommendations_file, 'r') as f:
                    recommendations = json.load(f)
                print(f"Loaded analytics recommendations from {recommendations_file}")
                # Migrate to SQLite
                store.set_project_value("_analytics", "content_recommendations", recommendations)
                return recommendations

            # If no saved recommendations, try to generate them
            print("No saved recommendations found, generating from analytics...")
            from analytics.unified_analytics import UnifiedAnalytics
            analytics = UnifiedAnalytics(data_dir=str(data_dir))
            return analytics.generate_content_recommendations()

        except Exception as e:
            print(f"Could not load analytics weights: {e}")
            print("   Using default equal weights for all pillars")
            return {}

    def _load_preferences(self) -> Dict:
        """Load content preferences from file

        Returns:
            Dict with content preferences
        """
        try:
            data_dir = Path(__file__).resolve().parent.parent / "data"
            preferences_file = data_dir / "content_preferences.json"

            if preferences_file.exists():
                with open(preferences_file, 'r') as f:
                    preferences = json.load(f)
                print(f"Loaded preferences from {preferences_file}")
                return preferences
            else:
                print("No preferences file found, using defaults")
                return {}

        except Exception as e:
            print(f"Could not load preferences: {e}")
            return {}

    def _configure_litellm(self):
        """Configure LiteLLM with fallbacks and settings"""
        # Configure fallback chain: Claude -> GPT-4 -> Gemini
        primary_model = os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022")
        fallback_models = os.getenv("LLM_FALLBACKS", "gpt-4o,gemini-2.0-flash-exp").split(",")

        # Note: litellm.set_fallbacks() is not available in all versions
        # Fallbacks will be handled in the _call_llm method instead
        # litellm.set_fallbacks(fallback_models)

        # Configure retry behavior
        litellm.set_verbose = False
        litellm.drop_params = True  # Drop unsupported params for specific providers
        litellm.telemetry = False
        litellm.callbacks = []
        litellm.success_callback = []
        litellm.failure_callback = []

        # Verify at least one API key is available
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        minimax_key = os.getenv("MINIMAX_API_KEY")

        if not any([anthropic_key, openai_key, gemini_key, minimax_key]):
            raise ValueError(
                "No LLM API key found. Please set at least one of:\n"
                "  - ANTHROPIC_API_KEY (for Claude - recommended)\n"
                "  - OPENAI_API_KEY (for GPT-4)\n"
                "  - GEMINI_API_KEY (for Gemini)\n"
                "  - MINIMAX_API_KEY (for MiniMax)\n\n"
                "Example: export ANTHROPIC_API_KEY='your-anthropic-api-key'"
            )

        # Log configuration
        print(f"LiteLLM configured with primary model: {primary_model}")
        print(f"   Fallback chain: {' -> '.join(fallback_models)}")

    def _track_llm_cost(self, response):
        """Track token usage and costs from LiteLLM response"""
        try:
            if hasattr(response, '_hidden_params'):
                usage = response._hidden_params.get('usage', None)
                if usage:
                    prompt_tokens = usage.prompt_tokens
                    completion_tokens = usage.completion_tokens
                    total_tokens = usage.total_tokens

                    self.total_tokens_used += total_tokens
                    self.api_call_count += 1

                    # Estimate cost (rough approximation)
                    # Claude: $3/1M input, $15/1M output
                    # GPT-4: $30/1M input, $60/1M output
                    cost_estimate = (prompt_tokens * 0.000003) + (completion_tokens * 0.000015)
                    self.total_cost += cost_estimate

                    print(f"   Tokens: {total_tokens} (in: {prompt_tokens}, out: {completion_tokens}), "
                          f"Est. cost: ${cost_estimate:.6f}")
        except Exception as e:
            # Cost tracking is non-critical, fail silently
            pass

    def _track_llm_error(self, error: Exception):
        """Track LLM API errors"""
        print(f"   LLM API Error: {type(error).__name__}: {error}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def _call_llm(self, prompt: str, max_tokens: int = 1000) -> str:
        """Unified LLM call via LiteLLM with automatic fallbacks and retries

        This method uses LiteLLM to provide:
        - Automatic fallback between providers (Claude -> GPT-4 -> Gemini)
        - Built-in retry logic with exponential backoff
        - Cost tracking and token usage monitoring
        - Unified interface for multiple LLM providers

        Args:
            prompt: The prompt to send to the LLM
            max_tokens: Maximum tokens in response

        Returns:
            Generated content as string

        Raises:
            ValueError: If no API keys are configured
            Exception: If all LLM providers fail after retries
        """
        try:
            override = getattr(self, "llm_override", None)
            if override:
                completion_kwargs = {
                    "model": override["model"],
                    "api_key": override["api_key"],
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "num_retries": 3,
                }
                if "api_base" in override:
                    completion_kwargs["api_base"] = override["api_base"]
                response = completion(**completion_kwargs)
            else:
                model = os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022")
                response = completion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    num_retries=3,
                    fallbacks=["gpt-4o", "gemini-2.0-flash-exp"]
                )

            # Track usage and cost
            self._track_llm_cost(response)

            # Extract content from response
            content = response.choices[0].message.content

            return content

        except Exception as e:
            self._track_llm_error(e)
            raise

    def generate_text(self, prompt: str, max_tokens: int = 1000) -> str:
        """Generate arbitrary text through the configured LLM provider."""
        return self._call_llm(prompt, max_tokens=max_tokens)

    def generate_twitter_post(
        self,
        pillar: Optional[str] = None,
        hook_type: Optional[str] = None,
        topic: Optional[str] = None
    ) -> Dict:
        """Generate a Twitter/X post using LLM

        Args:
            pillar: Content pillar (radical_transparency, production_engineering, etc.)
            hook_type: Type of hook (curiosity, story, value, contrarian)
            topic: Specific topic to focus on

        Returns:
            Dict with generated content and metadata
        """
        # Use weighted selections if not specified
        if not pillar:
            pillar = self._select_pillar()
        if not hook_type:
            hook_type = self._select_hook()

        # Build prompt
        prompt = self._build_twitter_prompt(pillar, hook_type, topic)

        # Generate content
        content = self._call_llm(prompt, max_tokens=1200)

        # Extract metadata from response
        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "twitter",
            "content_type": "thread",  # Default to thread
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
        """Build prompt for Twitter content generation

        Enhanced with 9-pattern hook library, CTA strategy, and brand voice.
        """

        # Extract relevant strategy sections
        strategy_context = self._extract_strategy_context(pillar, "twitter")

        # Get CTA suggestions
        cta_suggestions = self._get_cta_suggestions("twitter")

        # Get brand voice context
        brand_voice_context = self._get_brand_voice_context("twitter")

        # Load and format learning patterns
        learning_patterns = self._load_learning_patterns()
        learning_section = self._format_learning_patterns(learning_patterns)
        learning_block = f"\nLEARNING PATTERNS:\n{learning_section}\n" if learning_section else ""

        # Get structured hook guidance from the pattern library
        hook_guidance = self._get_hook_pattern_guidance(hook_type, "twitter")

        project_name = getattr(self.project, "name", None) or getattr(getattr(self.project, "config", None), "name", None) or "this brand"
        if self.project is not None:
            project_name = getattr(self.project, "name", None) or project_name
        prompt = f"""You write social content for {project_name}.
Follow the BRAND VOICE GUIDELINES below as the source of truth. Do not invent a different product, company, or audience.
If guidelines conflict with any generic defaults, the guidelines win.
{brand_voice_context}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}
{strategy_context}

HOOK PATTERN: {hook_type.upper()}
{hook_guidance}
{learning_block}
TASK: Generate a Twitter/X thread (6-8 tweets total) about {topic or "this week's theme from the brand guidelines and content plan"}.

REQUIREMENTS:
1. Start with a strong {hook_type} hook (first tweet) - follow the pattern guidance above
2. Write 5-7 follow-up tweets that build the narrative
3. Each tweet should be under 280 characters (on average)
4. End with a clear CTA from these options: {', '.join(cta_suggestions[:3])}
5. Make it specific and actionable - no vague statements
6. Include real examples or technical insights when possible
7. Use appropriate emoji sparingly
8. No placeholders like "[X]" or fill-in-the-blank - write the full content
9. Apply brand voice personality and tone consistently

FORMAT: Return ONLY the thread content, starting with the first tweet."""

        return prompt

    def generate_linkedin_post(
        self,
        pillar: Optional[str] = None,
        content_type: str = "story_post",
        topic: Optional[str] = None
    ) -> Dict:
        """Generate a LinkedIn post using LLM

        Args:
            pillar: Content pillar
            content_type: story_post, how_to, contrarian_take
            topic: Specific topic to focus on

        Returns:
            Dict with generated content and metadata
        """
        # Use weighted pillar selection if not specified
        if not pillar:
            pillar = self._select_pillar()

        # Build prompt
        prompt = self._build_linkedin_prompt(pillar, content_type, topic)

        # Generate content
        content = self._call_llm(prompt, max_tokens=1500)

        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "linkedin",
            "content_type": content_type,
            "pillar": pillar,
            "hook_type": "story",  # LinkedIn uses more story-based hooks
            "topic": topic or self._extract_topic(content),
            "content": self._clean_content(content),
            "suggested_actions": [
                "Ensure professional yet conversational tone",
                "Add line breaks for readability (under 300 chars per line)",
                "Include specific examples or data points",
                "Add relevant hashtag(s) at the end"
            ],
            "generated_at": generated_at
        }

    def _build_linkedin_prompt(
        self,
        pillar: str,
        content_type: str,
        topic: Optional[str]
    ) -> str:
        """Build prompt for LinkedIn content generation

        Enhanced with hook pattern library, CTA strategy, and brand voice.
        """

        strategy_context = self._extract_strategy_context(pillar, "linkedin")

        # Get CTA suggestions
        cta_suggestions = self._get_cta_suggestions("linkedin")

        # Get brand voice context
        brand_voice_context = self._get_brand_voice_context("linkedin")

        # Load and format learning patterns
        learning_patterns = self._load_learning_patterns()
        learning_section = self._format_learning_patterns(learning_patterns)
        learning_block = f"\nLEARNING PATTERNS:\n{learning_section}\n" if learning_section else ""

        # LinkedIn works best with story, empathy, or contrarian hooks
        linkedin_hook = self._select_hook()
        hook_guidance = self._get_hook_pattern_guidance(linkedin_hook, "linkedin")

        prompt = f"""You write social content for the active marketing project. Follow BRAND VOICE GUIDELINES as source of truth.

CONTEXT:
- Use only the brand voice guidelines and content plan for this project.
- Do not write about unrelated products (including generic AI-agent platforms) unless the brand voice says so.
{brand_voice_context}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}
{strategy_context}

CONTENT TYPE: {content_type}
HOOK PATTERN: {linkedin_hook.upper()}
{hook_guidance}
{learning_block}
TASK: Generate a LinkedIn post about {topic or 'themes from the brand guidelines and content plan'}.

REQUIREMENTS:
1. Start with a compelling {linkedin_hook} hook (first 2-3 lines are critical - follow the pattern guidance)
2. Use short paragraphs (1-3 sentences max per paragraph)
3. Include at least 2-3 line breaks for readability
4. End with a clear CTA from these options: {', '.join(cta_suggestions[:3])}
5. Be specific and actionable - no vague statements
6. Include real examples, metrics, or technical insights
7. Professional tone but avoid corporate buzzwords
8. Length: 500-1500 characters (optimal for LinkedIn)
9. Apply brand voice personality and tone consistently

FORMAT: Return ONLY the LinkedIn post content."""

        return prompt

    def _extract_strategy_context(self, pillar: str, platform: str) -> str:
        """Extract relevant strategy context from marketing documents"""
        strategy_doc = self.twitter_strategy if platform == "twitter" else self.linkedin_strategy

        # Extract sections relevant to the pillar
        if not strategy_doc:
            return "No specific strategy context available."

        # Simple extraction - look for pillar mentions
        pillar_mentions = []
        for line in strategy_doc.split('\n'):
            if pillar.lower() in line.lower():
                # Include this line and next 2-3 lines
                idx = strategy_doc.index(line)
                context_lines = strategy_doc[idx:min(idx + 150, len(strategy_doc))]
                pillar_mentions.append(context_lines[:300])  # First 300 chars
                break  # Just get one relevant section

        if pillar_mentions:
            return f"\nStrategy Context:\n{pillar_mentions[0]}\n"

        return "Use general best practices for this pillar."

    def _get_hook_examples(self, hook_type: str) -> List[str]:
        """Get example hooks for a specific type

        Enhanced with hook formulas from knowledge-work-plugins/marketing
        """
        examples = {
            "contrarian": [
                "Everyone says AI agents are the future. They're wrong — the future is already here.",
                "Unpopular opinion: RAG is wrong for most use cases.",
                "I stopped using GPT-4 and got better results.",
                "Most companies don't need AI agents yet.",
            ],
            "question": [
                "When was the last time a marketing email actually changed what you bought?",
                "Why do 90% of AI agent prototypes never reach production?",
                "What if your content pipeline could run itself — what would you do with the time?",
                "Is your content strategy actually working, or just making noise?",
            ],
            "story": [
                "Last week our agent deleted our production database.",
                "I almost shut down the company 3 months ago.",
                "Two years ago I thought AI agents were a buzzword. Then one wrote our docs.",
                "Our first user found a critical bug that changed our entire roadmap.",
            ],
            "statistic": [
                "73% of marketers say their biggest challenge isn't budget — it's focus.",
                "Companies using AI agents see 40% faster response times.",
                "We analyzed 10,000 tweets. Only 12% drove meaningful engagement.",
                "Most landing pages lose 50% of visitors in the first 3 seconds.",
            ],
            "list_preview": [
                "5 patterns that separate reliable AI agents from prototypes:",
                "7 things I learned deploying agents to production this year:",
                "3 mistakes every team makes when building with LLMs:",
                "The 4-step framework we use to evaluate agent reliability:",
            ],
            "bold_claim": [
                "The real reason agents fail isn't hallucinations — it's state management.",
                "Your content strategy is broken. Not because of the content — because of the workflow.",
                "Most 'autonomous' agents aren't autonomous at all.",
                "The best marketing teams don't create more content — they create better systems.",
            ],
            "empathy": [
                "You know that feeling when you spend hours on content and it gets zero engagement?",
                "If you're drowning in content calendars and approval chains, you're not alone.",
                "Every founder I talk to has the same problem: too many ideas, not enough published.",
                "Building an AI product is hard enough. Explaining it shouldn't be harder.",
            ],
            "before_after": [
                "Before: 20 hours/week on content. After: 3 hours. Here's the system.",
                "We went from 2 blog posts/month to 15 without adding headcount.",
                "6 months ago our content pipeline was a spreadsheet. Today it runs itself.",
                "Last quarter: 12% engagement. This quarter: 34%. Same content, different system.",
            ],
            "confession": [
                "I've been generating content the wrong way for 2 years. Here's what I fixed.",
                "The biggest mistake I made with AI content: treating it like a volume game.",
                "We shipped an agent that confidently did the wrong thing for 3 weeks.",
                "I used to think more content meant more reach. I was wrong.",
            ],
        }
        return examples.get(hook_type, [])

    # =========================================================================
    # Hook Pattern Library (from blacktwist/social-media-skills analysis)
    # 9 proven hook patterns with per-platform guidance
    # =========================================================================

    HOOK_PATTERNS = {
        "contrarian": {
            "description": "Challenge a widely held belief. Creates tension that demands attention.",
            "twitter_tips": [
                "State the unpopular opinion directly in the first line",
                "Follow with 'Here's why:' or evidence in tweet 2",
                "Don't be contrarian just for clicks — have a real argument",
            ],
            "linkedin_tips": [
                "Open with the contrarian statement as a standalone paragraph",
                "Use 'Unpopular opinion:' or 'I used to believe X. I was wrong.'",
                "Support with data or a personal story in the next paragraph",
            ],
            "formulas": [
                "Everyone says [X]. They're wrong.",
                "Unpopular opinion: [contrarian take]",
                "[Common belief] is a trap. Here's what actually works:",
            ],
        },
        "question": {
            "description": "Pose a provocative question that creates a knowledge gap. Reader must keep reading to find the answer.",
            "twitter_tips": [
                "Ask something the audience genuinely wonders about",
                "Don't ask yes/no — ask 'why' or 'how' questions",
                "Answer the question within the thread",
            ],
            "linkedin_tips": [
                "Open with the question as a one-line paragraph",
                "The question should trigger self-reflection",
                "Answer it with your experience, not theory",
            ],
            "formulas": [
                "Why do most [X] fail at [Y]?",
                "What if [assumption] isn't true?",
                "When was the last time [relatable scenario]?",
            ],
        },
        "story": {
            "description": "Open with a personal narrative. Stories create emotional investment before the insight.",
            "twitter_tips": [
                "Start with a specific moment, not a summary",
                "'Last week…' or 'Two years ago…' grounds the story in time",
                "Reveal the lesson in tweet 3-4, CTA at the end",
            ],
            "linkedin_tips": [
                "First line: the inciting incident",
                "Keep paragraphs to 1-2 sentences for scroll-friendly pacing",
                "End the story, then add the takeaway as a separate section",
            ],
            "formulas": [
                "Last [timeframe], [something surprising happened].",
                "I almost [dramatic action]. Here's what stopped me.",
                "[Time ago] I [mistake/decision]. It changed everything.",
            ],
        },
        "statistic": {
            "description": "Lead with a surprising number. Data creates authority and curiosity simultaneously.",
            "twitter_tips": [
                "Use real, verifiable data when possible",
                "Follow with context: 'Here's what that means for [audience]'",
                "Round numbers are less believable — prefer specific figures",
            ],
            "linkedin_tips": [
                "State the stat, then immediately explain why it matters",
                "Source the data when you can (builds credibility)",
                "Connect the stat to a decision your reader faces",
            ],
            "formulas": [
                "[X]% of [group] [surprising behavior]. Here's what that means.",
                "We analyzed [N] [items]. Only [X]% [unexpected finding].",
                "[Metric] dropped/increased by [X]%. The reason surprised us.",
            ],
        },
        "list_preview": {
            "description": "Preview a numbered list or framework. Creates expectation of structured value.",
            "twitter_tips": [
                "State the number of items in the hook tweet",
                "One item per subsequent tweet for maximum engagement",
                "End with a summary tweet that reinforces the framework",
            ],
            "linkedin_tips": [
                "Open with 'X things I learned about [topic]:'",
                "Use bullet points or numbered items in the body",
                "Bold the key phrase in each item",
            ],
            "formulas": [
                "[N] [adjectives] ways to [achieve result]:",
                "[N] patterns every [role] should know:",
                "The [N]-step framework for [outcome]:",
            ],
        },
        "bold_claim": {
            "description": "Make a strong, specific assertion. Confidence attracts; vagueness repels.",
            "twitter_tips": [
                "The claim should be debatable but defensible",
                "Support it in the thread — don't just assert",
                "Avoid obvious claims ('AI is the future') — be specific",
            ],
            "linkedin_tips": [
                "State the claim in one sentence, then build your case",
                "Use data, examples, or experience as evidence",
                "Acknowledge the counterargument briefly, then dismantle it",
            ],
            "formulas": [
                "[X] is the most underrated [skill/tool/strategy] in [domain].",
                "The real reason [problem] isn't [obvious cause].",
                "Your [process] is broken. Here's the fix.",
            ],
        },
        "empathy": {
            "description": "Acknowledge a pain point your audience feels. Creates instant connection and trust.",
            "twitter_tips": [
                "Describe the pain specifically, not abstractly",
                "Use 'you' language: 'You know that feeling when…'",
                "Transition to the solution by tweet 3",
            ],
            "linkedin_tips": [
                "Name the struggle your reader faces",
                "Share that you've been there too (briefly)",
                "The solution should feel earned, not salesy",
            ],
            "formulas": [
                "You know the feeling when [specific pain point]?",
                "If you're struggling with [X], you're not alone.",
                "[Role] deal with [pain] every day. It doesn't have to be that way.",
            ],
        },
        "before_after": {
            "description": "Show a transformation. Contrast creates compelling narrative tension.",
            "twitter_tips": [
                "Tweet 1: the 'before' state (relatable problem)",
                "Tweet 2-5: the transformation steps",
                "Final tweet: the 'after' state + CTA",
            ],
            "linkedin_tips": [
                "Paragraph 1: Before (the struggle)",
                "Body: What changed (the process)",
                "Closing: After (the result) + CTA",
            ],
            "formulas": [
                "Before: [painful state]. After: [desired state]. Here's the bridge.",
                "We went from [bad metric] to [good metric] in [timeframe].",
                "6 months ago, [bad situation]. Today, [good situation]. Here's what changed.",
            ],
        },
        "confession": {
            "description": "Admit a mistake or vulnerability. Authenticity builds trust faster than authority.",
            "twitter_tips": [
                "Be specific about the mistake, not vague",
                "Share the lesson, not just the guilt",
                "Keep it real — over-dramatization reads as fake",
            ],
            "linkedin_tips": [
                "Open with the confession directly",
                "Explain what you learned, not just what happened",
                "The vulnerability should serve the reader, not just vent",
            ],
            "formulas": [
                "I [made a mistake]. It cost me [consequence].",
                "I've been [doing X wrong] for [timeframe]. Here's what I fixed.",
                "The biggest mistake I see in [domain]: [specific mistake]. I made it too.",
            ],
        },
    }

    def _get_hook_pattern_guidance(self, hook_type: str, platform: str) -> str:
        """Get structured guidance for a specific hook pattern.

        Args:
            hook_type: One of the 9 hook pattern types.
            platform: "twitter" or "linkedin" for platform-specific tips.

        Returns:
            Formatted guidance string for injection into prompts.
        """
        pattern = self.HOOK_PATTERNS.get(hook_type)
        if not pattern:
            # Fallback to existing examples for unknown types
            examples = self._get_hook_examples(hook_type)
            if examples:
                return (
                    f"Use a {hook_type} hook to grab attention.\n"
                    f"Examples:\n" + "\n".join(f"- {ex}" for ex in examples[:4])
                )
            return f"Use a {hook_type} hook to grab attention immediately."

        tips_key = f"{platform}_tips"
        tips = pattern.get(tips_key, [])
        formulas = pattern.get("formulas", [])
        description = pattern.get("description", "")

        lines = [
            f"Pattern: {description}",
            "",
            "Platform-specific tips:",
        ]
        for tip in tips:
            lines.append(f"  • {tip}")

        if formulas:
            lines.append("")
            lines.append("Hook formulas:")
            for formula in formulas[:3]:
                lines.append(f"  • {formula}")

        return "\n".join(lines)

    def _get_headline_formulas(self) -> List[str]:
        """Get headline formulas from knowledge-work-plugins

        Returns 6 proven headline formulas for higher engagement
        """
        return [
            "How to [achieve result] [without common obstacle]",
            "[Number] [adjective] ways to [achieve result]",
            "Why [common belief] is wrong (and what to do instead)",
            "The [adjective] guide to [topic]",
            "[Do this], not [that]",
            "What [impressive result] taught us about [topic]"
        ]

    def _extract_topic(self, content: str) -> str:
        """Extract a topic from generated content"""
        # Simple heuristic: first few words or first sentence
        first_sentence = content.split('\n')[0]
        # Remove emoji and special chars
        topic = first_sentence[:50].strip()
        return topic

    def _apply_analytics_weights(self) -> Dict:
        """Apply analytics-based weights to content selection

        Returns:
            Dict with weighted selections for pillars, hooks, and platforms
        """
        weighted = {
            "pillar_weights": {},
            "hook_weights": {},
            "platform_weights": {}
        }

        # Apply pillar weights from analytics
        pillar_weights = self.preferences.get("pillar_weights", {})
        if pillar_weights:
            weighted["pillar_weights"] = pillar_weights
        else:
            # Equal weights if no analytics data
            weighted["pillar_weights"] = {
                pillar: 1.0 / len(self.content_pillars)
                for pillar in self.content_pillars
            }

        # Apply hook preferences
        hook_prefs = self.preferences.get("hook_preferences", [])
        if hook_prefs:
            for hook_pref in hook_prefs:
                hook_type = hook_pref["hook_type"]
                frequency = hook_pref["frequency"]

                # Convert frequency to weight
                if frequency == "high":
                    weighted["hook_weights"][hook_type] = 0.6
                elif frequency == "medium":
                    weighted["hook_weights"][hook_type] = 0.3
                else:  # low
                    weighted["hook_weights"][hook_type] = 0.1

        # Apply platform preferences
        platform_prefs = self.preferences.get("platform_preferences", [])
        if platform_prefs:
            for platform_pref in platform_prefs:
                platform = platform_pref["platform"]
                allocation = platform_pref["allocation"]

                # Convert allocation to weight
                if allocation == "high":
                    weighted["platform_weights"][platform] = 0.7
                elif allocation == "medium":
                    weighted["platform_weights"][platform] = 0.3
                else:  # low
                    weighted["platform_weights"][platform] = 0.1

        return weighted

    def _select_pillar(self) -> str:
        """Select pillar weighted by analytics performance

        Returns:
            Selected pillar name
        """
        weighted = self._apply_analytics_weights()
        pillar_weights = weighted["pillar_weights"]

        if pillar_weights:
            # Weighted random selection favoring high performers
            pillars = list(pillar_weights.keys())
            weights = list(pillar_weights.values())

            # Normalize weights
            total_weight = sum(weights)
            if total_weight > 0:
                normalized_weights = [w / total_weight for w in weights]
                return random.choices(pillars, weights=normalized_weights)[0]

        # Fallback to equal weights
        return random.choice(self.content_pillars)

    def _select_hook(self) -> str:
        """Select hook type weighted by analytics performance

        Returns:
            Selected hook type

        Enhanced with 6 hook types from knowledge-work-plugins:
        - statistic, contrarian, question, scenario, claim, story
        """
        weighted = self._apply_analytics_weights()
        hook_weights = weighted["hook_weights"]

        # Enhanced hook types — 9-pattern library from social media skills analysis
        all_hooks = [
            "contrarian",    # Challenge a widely held belief
            "question",      # Provocative question (knowledge gap)
            "story",         # Personal narrative opening
            "statistic",     # Surprising data point
            "list_preview",  # Preview of numbered list/framework
            "bold_claim",    # Strong, specific assertion
            "empathy",       # Acknowledge audience pain point
            "before_after",  # Show transformation
            "confession",    # Admit a mistake (authenticity)
        ]

        if hook_weights:
            # Weighted random selection
            hooks = list(hook_weights.keys())
            weights = list(hook_weights.values())

            # Normalize weights
            total_weight = sum(weights)
            if total_weight > 0:
                normalized_weights = [w / total_weight for w in weights]
                selected_hook = random.choices(hooks, weights=normalized_weights)[0]
                return selected_hook

        # Fallback to equal weights
        return random.choice(all_hooks)

    def _get_cta_suggestions(self, platform: str, content_type: str = "post") -> List[str]:
        """Get platform-specific CTA suggestions from knowledge-work-plugins

        Args:
            platform: twitter, linkedin, email, etc.
            content_type: Type of content (post, blog, landing_page, etc.)

        Returns:
            List of CTA suggestions for the platform
        """
        cta_examples = {
            "twitter": [
                "Drop a comment if you agree",
                "Save this for later",
                "Link in bio",
                "Retweet if this resonated",
                "Follow for more insights",
                "Share your thoughts below"
            ],
            "linkedin": [
                "Share your thoughts in the comments",
                "Follow for more insights like this",
                "Save this post for later",
                "Tag someone who needs to see this",
                "Let's discuss in the comments",
                "Share your experience below"
            ],
            "email": [
                "Read the full story",
                "Claim your spot",
                "Reply and tell us what you think",
                "Get started now",
                "Learn more",
                "Join the waitlist"
            ],
            "blog": [
                "Read our complete guide to [topic]",
                "Subscribe for weekly insights",
                "Share this post with your network",
                "Leave a comment below",
                "Related: [link to related post]"
            ],
            "landing_page": [
                "Start free trial",
                "Get a demo",
                "See pricing",
                "Start now",
                "Try it free",
                "Get started"
            ]
        }

        return cta_examples.get(platform, ["Learn more", "Find out more"])

    def _select_platform(self, available_platforms: List[str]) -> str:
        """Select platform weighted by analytics performance

        Args:
            available_platforms: List of available platform names

        Returns:
            Selected platform name
        """
        weighted = self._apply_analytics_weights()
        platform_weights = weighted["platform_weights"]

        if platform_weights:
            # Filter to only available platforms
            available_weights = {
                platform: platform_weights.get(platform, 0.1)
                for platform in available_platforms
            }

            # Weighted random selection
            platforms = list(available_weights.keys())
            weights = list(available_weights.values())

            # Normalize weights
            total_weight = sum(weights)
            if total_weight > 0:
                normalized_weights = [w / total_weight for w in weights]
                return random.choices(platforms, weights=normalized_weights)[0]

        # Fallback to equal weights
        return random.choice(available_platforms)

    def generate_batch(
        self,
        count: int = 10,
        platforms: Optional[List[str]] = None,
        pillars: Optional[List[str]] = None,
        repurpose: bool = False,
    ) -> Dict:
        """Generate a batch of content

        Args:
            count: Number of posts to generate
            platforms: List of platforms (twitter, linkedin)
            pillars: List of pillars to focus on
            repurpose: If True, generate primary content then derive variants
                for other platforms instead of independent LLM calls.

        Returns:
            Dict with generated posts and metadata
        """
        if not platforms:
            platforms = ["twitter", "linkedin"]

        if repurpose:
            return self._generate_batch_repurposed(count, platforms, pillars)

        batch = []
        for i in range(count):
            # Use weighted platform selection
            platform = self._select_platform(platforms)

            if platform == "twitter":
                pillar = random.choice(pillars) if pillars else self._select_pillar()
                hook = self._select_hook()
                post = self.generate_twitter_post(pillar=pillar, hook_type=hook)
            else:  # linkedin
                pillar = random.choice(pillars) if pillars else self._select_pillar()
                post = self.generate_linkedin_post(pillar=pillar)

            batch.append(post)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(batch),
            "posts": batch,
            "analytics_enabled": bool(self.analytics_weights),
            "selection_strategy": "analytics-weighted" if self.analytics_weights else "random"
        }

    # =========================================================================
    # Repurposing Mode (generate once, derive per-platform variants)
    # =========================================================================

    REPURPOSE_RULES = {
        "twitter": {
            "max_chars_per_tweet": 280,
            "tone": "casual, punchy, uses emoji sparingly",
            "structure": "Thread format: hook tweet + 4-7 follow-up tweets + CTA tweet",
            "adaptations": [
                "Break long paragraphs into individual tweets",
                "Add thread numbering (1/6, 2/6, etc.) or line breaks between tweets",
                "Shorten sentences — aim for punchy, quotable lines",
                "Replace formal transitions with casual connectors",
                "Use 1-2 relevant hashtags max",
            ],
        },
        "linkedin": {
            "max_chars_total": 1500,
            "tone": "professional but authentic, first person, story-driven",
            "structure": "Hook paragraph → 3-5 short paragraphs → CTA",
            "adaptations": [
                "Keep paragraphs to 1-3 sentences",
                "Add extra line breaks for readability",
                "Strengthen the opening hook for scroll-stop impact",
                "Replace casual language with professional phrasing",
                "End with a discussion question or clear CTA",
            ],
        },
        "threads": {
            "max_chars_per_post": 500,
            "tone": "conversational, personal, community-oriented",
            "structure": "Single post or short thread (2-3 posts)",
            "adaptations": [
                "Conversational tone — like talking to a friend",
                "Shorter than Twitter threads — get to the point fast",
                "No hashtags (Threads algorithm doesn't use them)",
                "More personal, less polished",
            ],
        },
        "nostr": {
            "max_chars_per_note": 1000,
            "tone": "technical, community-minded, no jargon",
            "structure": "Single note, markdown-friendly",
            "adaptations": [
                "Use markdown formatting freely",
                "Technical audience — depth over polish",
                "Include links to sources/references",
                "Community-oriented framing",
            ],
        },
    }

    def repurpose_content(
        self,
        source_content: str,
        source_platform: str,
        target_platforms: Optional[List[str]] = None,
        pillar: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Dict:
        """Repurpose existing content for other platforms.

        Instead of generating each platform variant independently via separate
        LLM calls, this takes one source piece and adapts it — faster, more
        consistent, and the variants stay on-message.

        Args:
            source_content: The original content to repurpose.
            source_platform: Platform the content was originally for.
            target_platforms: Platforms to adapt to. If None, adapts to all
                platforms except source_platform.
            pillar: Content pillar for metadata.
            topic: Topic for metadata.

        Returns:
            Dict with source info, variants (one per target platform), and metadata.
        """
        if not target_platforms:
            target_platforms = [p for p in self.REPURPOSE_RULES if p != source_platform]

        if not pillar:
            pillar = self._select_pillar()

        brand_voice_context = self._get_brand_voice_context(source_platform)
        hook_type = self._select_hook()

        variants = []
        for target in target_platforms:
            if target == source_platform:
                continue

            rules = self.REPURPOSE_RULES.get(target, self.REPURPOSE_RULES["twitter"])
            adaptations = "\n".join(f"  • {a}" for a in rules["adaptations"])

            prompt = f"""You are a content repurposing specialist for Draper.

{brand_voice_context}

SOURCE CONTENT (originally for {source_platform}):
---
{source_content}
---

TARGET PLATFORM: {target}
Tone: {rules['tone']}
Structure: {rules['structure']}

ADAPTATION RULES:
{adaptations}

TASK: Rewrite the source content for {target}. Keep the core message and insights
identical but adapt the format, tone, and length to match {target} best practices.

RULES:
1. Do NOT add new claims or data not in the source
2. Do NOT change the core message or narrative arc
3. DO adjust tone, length, and formatting for {target}
4. DO ensure the hook pattern matches {target} expectations
5. Write the complete adapted content — no placeholders

FORMAT: Return ONLY the {target} post content."""

            adapted = self._call_llm(prompt, max_tokens=1500)
            cleaned = self._clean_content(adapted)

            variants.append({
                "platform": target,
                "content": cleaned,
                "pillar": pillar,
                "hook_type": hook_type,
                "topic": topic or self._extract_topic(cleaned),
                "content_type": "repurposed",
                "source_platform": source_platform,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            })

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_platform": source_platform,
            "target_platforms": [v["platform"] for v in variants],
            "pillar": pillar,
            "topic": topic,
            "variants": variants,
            "strategy": "repurpose",
        }

    def _generate_batch_repurposed(
        self,
        count: int,
        platforms: List[str],
        pillars: Optional[List[str]],
    ) -> Dict:
        """Generate a batch using repurposing mode.

        Generates primary content (LinkedIn — longer form) then derives
        variants for other platforms, instead of independent LLM calls.
        """
        batch = []
        for _ in range(count):
            pillar = random.choice(pillars) if pillars else self._select_pillar()
            hook = self._select_hook()

            # Generate primary (LinkedIn — richer source material)
            primary = self.generate_linkedin_post(pillar=pillar)
            primary["content_type"] = "primary"
            primary["generation_strategy"] = "repurpose-primary"
            batch.append(primary)

            # Derive variants for other platforms
            target_platforms = [p for p in platforms if p != "linkedin"]
            if target_platforms:
                result = self.repurpose_content(
                    source_content=primary["content"],
                    source_platform="linkedin",
                    target_platforms=target_platforms,
                    pillar=pillar,
                    topic=primary.get("topic"),
                )
                for variant in result.get("variants", []):
                    variant["generation_strategy"] = "repurpose-derived"
                    batch.append(variant)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(batch),
            "posts": batch,
            "analytics_enabled": bool(self.analytics_weights),
            "selection_strategy": "repurpose",
        }

    # =============================================================================
    # New Content Type Methods (Phase 2)
    # =============================================================================

    def generate_blog_post(
        self,
        pillar: Optional[str] = None,
        topic: Optional[str] = None,
        seo_mode: bool = False
    ) -> Dict:
        """Generate a blog post using LLM

        Args:
            pillar: Content pillar
            topic: Specific topic to focus on
            seo_mode: If True, include SEO optimization

        Returns:
            Dict with generated content and metadata
        """
        if not pillar:
            pillar = self._select_pillar()

        prompt = self._build_blog_prompt(pillar, topic, seo_mode)
        content = self._call_llm(prompt, max_tokens=2500)

        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "blog",
            "content_type": "blog_post",
            "pillar": pillar,
            "topic": topic or self._extract_topic(content),
            "content": self._clean_content(content),
            "seo_optimized": seo_mode,
            "suggested_actions": [
                "Review for accuracy and add specific examples",
                "Add internal links to related content",
                "Include relevant images or diagrams",
                "Optimize meta description for click-through rate"
            ],
            "generated_at": generated_at
        }

    def generate_email_newsletter(
        self,
        pillar: Optional[str] = None,
        topic: Optional[str] = None
    ) -> Dict:
        """Generate an email newsletter using LLM

        Args:
            pillar: Content pillar
            topic: Specific topic to focus on

        Returns:
            Dict with generated content and metadata
        """
        if not pillar:
            pillar = self._select_pillar()

        prompt = self._build_email_prompt(pillar, topic)
        content = self._call_llm(prompt, max_tokens=2000)

        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "email",
            "content_type": "newsletter",
            "pillar": pillar,
            "topic": topic or self._extract_topic(content),
            "content": self._clean_content(content),
            "suggested_actions": [
                "Add personalized greeting variables",
                "Include unsubscribe link",
                "Test subject lines for open rates",
                "Add visual elements or formatting"
            ],
            "generated_at": generated_at
        }

    def generate_landing_page(
        self,
        pillar: Optional[str] = None,
        topic: Optional[str] = None
    ) -> Dict:
        """Generate landing page copy using LLM

        Args:
            pillar: Content pillar
            topic: Specific topic to focus on

        Returns:
            Dict with generated content and metadata
        """
        if not pillar:
            pillar = self._select_pillar()

        prompt = self._build_landing_page_prompt(pillar, topic)
        content = self._call_llm(prompt, max_tokens=2500)

        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "web",
            "content_type": "landing_page",
            "pillar": pillar,
            "topic": topic or self._extract_topic(content),
            "content": self._clean_content(content),
            "suggested_actions": [
                "Add social proof elements",
                "Include trust badges or security indicators",
                "Create compelling visuals",
                "A/B test headline and CTA variations"
            ],
            "generated_at": generated_at
        }

    def generate_press_release(
        self,
        pillar: Optional[str] = None,
        topic: Optional[str] = None
    ) -> Dict:
        """Generate a press release using LLM

        Args:
            pillar: Content pillar
            topic: Specific topic to focus on

        Returns:
            Dict with generated content and metadata
        """
        if not pillar:
            pillar = self._select_pillar()

        prompt = self._build_press_release_prompt(pillar, topic)
        content = self._call_llm(prompt, max_tokens=2000)

        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "pr",
            "content_type": "press_release",
            "pillar": pillar,
            "topic": topic or self._extract_topic(content),
            "content": self._clean_content(content),
            "suggested_actions": [
                "Add quotes from leadership",
                "Include company boilerplate",
                "Add media contact information",
                "Distribute to relevant media outlets"
            ],
            "generated_at": generated_at
        }

    def generate_case_study(
        self,
        pillar: Optional[str] = None,
        topic: Optional[str] = None
    ) -> Dict:
        """Generate a case study using LLM

        Args:
            pillar: Content pillar
            topic: Specific topic to focus on

        Returns:
            Dict with generated content and metadata
        """
        if not pillar:
            pillar = self._select_pillar()

        prompt = self._build_case_study_prompt(pillar, topic)
        content = self._call_llm(prompt, max_tokens=2500)

        generated_at = datetime.now(timezone.utc).isoformat()

        return {
            "platform": "web",
            "content_type": "case_study",
            "pillar": pillar,
            "topic": topic or self._extract_topic(content),
            "content": self._clean_content(content),
            "suggested_actions": [
                "Add real customer metrics and data",
                "Include customer testimonials",
                "Add relevant visuals or charts",
                "Get customer approval before publishing"
            ],
            "generated_at": generated_at
        }

    # =============================================================================
    # Content Type Prompt Builders
    # =============================================================================

    # =========================================================================
    # Carousel Generation (structured slide-by-slide system)
    # 5 carousel archetypes from blacktwist/social-media-skills analysis
    # =========================================================================

    CAROUSEL_ARCHETYPES = {
        "listicle": {
            "description": "N items/tips/lessons, one per slide",
            "structure": [
                ("Cover", "Hook + title"),
                ("Slides 2-N", "One item per slide, max 30 words"),
                ("CTA", "Follow for more / Save this / Share"),
            ],
        },
        "framework": {
            "description": "Step-by-step process or mental model",
            "structure": [
                ("Cover", "Hook + framework name"),
                ("Context", "Frame the problem the framework solves"),
                ("Slides 3-N", "One step per slide"),
                ("CTA", "Try this / Bookmark this"),
            ],
        },
        "before_after": {
            "description": "Transformation story with contrast",
            "structure": [
                ("Cover", "Hook + bold 'Before → After' statement"),
                ("Before", "The painful/inefficient state"),
                ("Bridge Slides", "What changed, step by step"),
                ("After", "The improved state with metrics"),
                ("CTA", "Start your transformation"),
            ],
        },
        "data_story": {
            "description": "Data-driven narrative with key stats per slide",
            "structure": [
                ("Cover", "Hook + most surprising stat"),
                ("Context", "Why this data matters"),
                ("Data Slides", "One insight per slide with supporting number"),
                ("Takeaway", "What to do with this information"),
                ("CTA", "Share if you learned something"),
            ],
        },
        "mini_case_study": {
            "description": "Short case study: problem → solution → result",
            "structure": [
                ("Cover", "Hook + company/situation name"),
                ("Problem", "What was broken"),
                ("Solution", "What was built/changed (2-3 slides)"),
                ("Result", "Measurable outcome"),
                ("CTA", "Learn more / Read full case study"),
            ],
        },
    }

    def generate_carousel_copy(
        self,
        topic: Optional[str] = None,
        archetype: Optional[str] = None,
        pillar: Optional[str] = None,
        num_slides: int = 5,
    ) -> Dict:
        """Generate structured carousel copy with slide-by-slide content.

        Uses the LLM to produce structured slide copy (cover, context, body,
        CTA) suitable for feeding into Gamma or other carousel generators.

        Args:
            topic: Topic for the carousel.
            archetype: One of listicle, framework, before_after, data_story,
                mini_case_study. Auto-selected if None.
            pillar: Content pillar.
            num_slides: Total slides including cover and CTA (default 5).

        Returns:
            Dict with slides list, archetype, and metadata.
        """
        if not pillar:
            pillar = self._select_pillar()

        if not archetype:
            archetype = random.choice(list(self.CAROUSEL_ARCHETYPES.keys()))

        archetype_info = self.CAROUSEL_ARCHETYPES[archetype]
        structure_desc = "\n".join(
            f"  - {step[0]}: {step[1]}" for step in archetype_info["structure"]
        )

        brand_voice_context = self._get_brand_voice_context("linkedin")
        hook_type = self._select_hook()
        hook_guidance = self._get_hook_pattern_guidance(hook_type, "linkedin")

        prompt = f"""You are a social media carousel designer for Draper, an AI-powered autonomous agent platform.

{brand_voice_context}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}
TOPIC: {topic or 'AI agents/autonomous systems'}

CAROUSEL ARCHETYPE: {archetype}
Description: {archetype_info['description']}
Structure:
{structure_desc}

HOOK PATTERN: {hook_type.upper()}
{hook_guidance}

TASK: Generate a {num_slides}-slide carousel. Each slide needs:
- **headline**: 3-8 words, bold and attention-grabbing
- **body**: 15-30 words max, one key point per slide
- **visual_hint**: brief description of what the visual should show (e.g., "icon of a rocket", "chart trending up")

RULES:
1. Cover slide: Hook headline only (no body), strong visual hint
2. Body slides: One idea per slide, scannable text, no walls of words
3. CTA slide (last): Clear action + short reason to act
4. Tone: {('professional' if archetype in ('framework', 'data_story', 'mini_case_study') else 'conversational')}
5. Use specific numbers, examples, or frameworks where possible
6. No placeholders — write the actual content

OUTPUT FORMAT (return exactly this JSON structure):
```json
{{
  "archetype": "{archetype}",
  "hook_type": "{hook_type}",
  "slides": [
    {{"slide": 1, "type": "cover", "headline": "...", "body": "", "visual_hint": "..."}},
    {{"slide": 2, "type": "content", "headline": "...", "body": "...", "visual_hint": "..."}},
    ...
    {{"slide": {num_slides}, "type": "cta", "headline": "...", "body": "...", "visual_hint": "..."}}
  ]
}}
```"""

        raw = self._call_llm(prompt, max_tokens=1500)
        cleaned = self._clean_content(raw)

        # Parse JSON from response
        slides_data = self._parse_carousel_json(cleaned)
        if slides_data is None:
            # Fallback: return raw text if JSON parse fails
            slides_data = {
                "archetype": archetype,
                "hook_type": hook_type,
                "raw_text": cleaned,
                "parse_error": True,
            }

        slides_data["pillar"] = pillar
        slides_data["topic"] = topic or self._extract_topic(cleaned)
        slides_data["generated_at"] = datetime.now(timezone.utc).isoformat()
        slides_data["num_slides"] = num_slides
        slides_data["platform"] = "carousel"

        return slides_data

    def _parse_carousel_json(self, text: str) -> Optional[Dict]:
        """Extract carousel JSON from LLM response.

        Handles cases where the LLM wraps JSON in markdown code blocks
        or adds extra text around it.
        """
        # Try to find JSON in code blocks first
        import re
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try parsing the whole text as JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try finding first { to last }
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        return None

    def _build_blog_prompt(
        self,
        pillar: str,
        topic: Optional[str],
        seo_mode: bool
    ) -> str:
        """Build prompt for blog post generation

        Templates from knowledge-work-plugins/marketing/content-creation
        """
        strategy_context = self._extract_strategy_context(pillar, "blog")
        brand_voice_context = self._get_brand_voice_context("blog")

        seo_section = ""
        if seo_mode:
            seo_section = """
SEO REQUIREMENTS:
- Suggest a primary keyword for this topic
- Include keyword in: headline, first paragraph, one subheading, meta description
- Suggest a meta description (under 160 characters)
- Use H2 for main sections, H3 for subsections
- Write at 8th-grade reading level for broad accessibility
"""

        prompt = f"""You write social content for the active marketing project. Follow BRAND VOICE GUIDELINES as source of truth.

{brand_voice_context}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}
{strategy_context}

TASK: Write a blog post about {topic or 'themes from the brand guidelines and content plan'}.

BLOG POST STRUCTURE:
1. **Headline** -- clear, benefit-driven, includes primary keyword (60 chars or less)
2. **Introduction** (100-150 words) -- hook with a question, statistic, or bold claim
3. **Body sections** (3-5 sections) -- each with descriptive H2 subheading
4. **Conclusion** (75-100 words) -- summarize key takeaways, include CTA
5. **Meta description** -- under 160 characters, compels the click
{seo_section}

REQUIREMENTS:
- Write in short paragraphs (2-4 sentences)
- Include at least one data point, example, or quote per section
- Use active voice
- Front-load key information in each section
- Professional but conversational tone
- Target word count: 1000-1500 words

FORMAT: Return the complete blog post with headline, body sections, conclusion, and meta description.
"""

        return prompt

    def _build_email_prompt(
        self,
        pillar: str,
        topic: Optional[str]
    ) -> str:
        """Build prompt for email newsletter generation"""
        strategy_context = self._extract_strategy_context(pillar, "email")
        brand_voice_context = self._get_brand_voice_context("email")
        cta_suggestions = self._get_cta_suggestions("email")

        prompt = f"""You are an email marketer for Draper.

{brand_voice_context}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}
{strategy_context}

TASK: Write an email newsletter about {topic or 'themes from the brand guidelines and content plan'}.

EMAIL NEWSLETTER STRUCTURE:
1. **Subject line** -- under 50 characters, creates curiosity or states clear value (provide 3 options)
2. **Preview text** -- complements subject line, does not repeat it
3. **Header/hero** -- one-line value statement
4. **Body sections** -- 2-3 content blocks, each scannable with bold intro sentence
5. **Primary CTA** -- one clear action (e.g., {cta_suggestions[0]})
6. **Footer** -- unsubscribe link, company info, social links

REQUIREMENTS:
- Personalize where possible (name, company references)
- Make body copy scannable: bold key phrases, short paragraphs, bullet points
- Mobile-first: most email is read on mobile
- One primary CTA per email
- Professional but authentic tone

FORMAT: Return the complete email with subject line options, preview text, body, and CTA.
"""

        return prompt

    def _build_landing_page_prompt(
        self,
        pillar: str,
        topic: Optional[str]
    ) -> str:
        """Build prompt for landing page copy generation"""
        strategy_context = self._extract_strategy_context(pillar, "landing_page")
        brand_voice_context = self._get_brand_voice_context("web")
        cta_suggestions = self._get_cta_suggestions("landing_page")

        prompt = f"""You are a conversion copywriter for Draper.

{brand_voice_context}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}
{strategy_context}

TASK: Write landing page copy for {topic or 'AI agents/autonomous systems'}.

LANDING PAGE STRUCTURE:
1. **Headline** -- primary benefit in under 10 words
2. **Subheadline** -- elaborates on headline with supporting context
3. **Hero section** -- headline, subheadline, primary CTA ({cta_suggestions[0]}), supporting image prompt
4. **Value propositions** -- 3-4 benefit-driven sections with icons
5. **Social proof** -- testimonial placeholders, stats, logos
6. **Objection handling** -- FAQ or trust signals
7. **Final CTA** -- repeat primary call to action
8. **SEO** -- meta title and meta description suggestions

REQUIREMENTS:
- Lead with benefits, not features
- Use "you" language -- speak to the reader directly
- Minimize jargon unless the audience expects it
- Every section should answer "so what?" from reader's perspective
- Reduce friction: clear next steps, trust signals near CTAs

FORMAT: Return complete landing page copy with all sections.
"""

        return prompt

    def _build_press_release_prompt(
        self,
        pillar: str,
        topic: Optional[str]
    ) -> str:
        """Build prompt for press release generation"""
        brand_voice_context = self._get_brand_voice_context("pr")

        prompt = f"""You are a PR professional for Draper.

{brand_voice_context}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}

TASK: Write a press release about {topic or 'themes from the brand guidelines and content plan'}.

PRESS RELEASE STRUCTURE:
1. **Headline** -- factual, newsworthy, under 80 characters
2. **Subheadline** -- optional, adds context
3. **Dateline** -- city, state -- date
4. **Lead paragraph** -- who, what, when, where, why in 2-3 sentences
5. **Body paragraphs** -- supporting details, context, quotes (provide quote placeholders)
6. **Boilerplate** -- company description (provide placeholder)
7. **Media contact** -- name, email, phone (provide placeholder)

REQUIREMENTS:
- Journalistic style: factual, objective, newsworthy
- Inverted pyramid: most important info first
- Include quotes from leadership (placeholders)
- Standard press release formatting
- Formal tone

FORMAT: Return complete press release with headline, dateline, body, boilerplate, and media contact.
"""

        return prompt

    def _build_case_study_prompt(
        self,
        pillar: str,
        topic: Optional[str]
    ) -> str:
        """Build prompt for case study generation"""
        brand_voice_context = self._get_brand_voice_context("web")
        cta_suggestions = self._get_cta_suggestions("blog")

        prompt = f"""You are a content marketer for Draper.

{brand_voice_context}

CONTENT PILLAR: {pillar.replace('_', ' ').upper()}

TASK: Write a case study about {topic or 'themes from the brand guidelines and content plan'}.

CASE STUDY STRUCTURE:
1. **Title** -- "[Customer] achieves [result] with [product]"
2. **Snapshot** -- customer name, industry, company size, product used, key result
3. **Challenge** -- what problem the customer faced
4. **Solution** -- what was implemented and how
5. **Results** -- quantified outcomes with specific metrics
6. **Quote** -- customer testimonial (provide placeholder)
7. **CTA** -- learn more, get a demo, read more case studies

REQUIREMENTS:
- Focus on quantified results and metrics
- Use real customer journey and challenges
- Include specific implementation details
- Authentic customer voice in quotes (placeholder)
- Results-oriented narrative

FORMAT: Return complete case study with all sections and quote placeholders.
"""

        return prompt


def main():
    """CLI for LLM content generation"""
    import argparse

    parser = argparse.ArgumentParser(description="Generate social media content using LLMs")
    parser.add_argument("--platform", choices=["twitter", "linkedin", "both"], help="Platform to generate for")
    parser.add_argument("--count", type=int, default=1, help="Number of posts to generate")
    parser.add_argument("--pillar", choices=[
        "radical_transparency", "production_engineering", "educational",
        "behind_the_scenes", "industry_insights"
    ], help="Content pillar")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()

    try:
        generator = LLMContentGenerator()

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
            print(f"\nSaved to {args.output}")

    except ValueError as e:
        print(f"Error: {e}")
        print("\nLiteLLM requires at least one LLM API key:")
        print("  export ANTHROPIC_API_KEY='your-anthropic-api-key'  # Recommended (Claude)")
        print("  export OPENAI_API_KEY='your-openai-api-key'        # Fallback (GPT-4)")
        print("  export GEMINI_API_KEY='your-gemini-api-key'        # Alternative (Gemini)")
        print("\nOptional: Configure model and fallbacks:")
        print("  export LLM_MODEL='claude-3-5-sonnet-20241022'  # Primary model")
        print("  export LLM_FALLBACKS='gpt-4o,gemini-2.0-flash-exp'  # Fallback chain")
        return 1

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
