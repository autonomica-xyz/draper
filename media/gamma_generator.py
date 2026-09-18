#!/usr/bin/env python3
"""
Media Generator using DynaPictures API and ZAI GLM-Image API
Creates graphical materials for social media content

PROVIDER PRIORITY:
1. DynaPictures - template-based image generation (if configured)
2. ZAI GLM-Image - AI-generated images (if configured)
3. Placeholder response - when no provider is configured

DYNAPICTURES SETUP:
1. Sign up at https://dynapictures.com/
2. Create templates in their web UI (Twitter images, LinkedIn carousels, etc.)
3. Get your API key from the account page
4. Get template UIDs from template pages (top left corner)
5. Set environment variable: export DYNAPICTURES_API_KEY="your-key"
6. Configure template UIDs in this file or pass them as parameters

ZAI SETUP:
1. Get your ZAI API key
2. Set environment variable: export ZAI_API_KEY="your-key"
3. Images generated via GLM-Image model at $0.015/image

PRICING:
- DynaPictures free tier: 30 images/month
- DynaPictures paid plans: $29-39/month
- DynaPictures rate limit: 150 requests/10 seconds (~15 req/sec)
- ZAI GLM-Image: $0.015/image
"""

import json
import os
import httpx
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime, timezone
import asyncio

from integrations.zai_image import ZAIImageGenerator


class DynaPicturesMediaGenerator:
    """Generate graphical content using DynaPictures REST API with ZAI fallback"""

    def __init__(
        self,
        api_key: str = None,
        twitter_template_uid: str = None,
        linkedin_template_uid: str = None,
        infographic_template_uid: str = None,
        thumbnail_template_uid: str = None,
    ):
        """
        Initialize DynaPictures media generator

        Args:
            api_key: DynaPictures API key (defaults to DYNAPICTURES_API_KEY env var)
            twitter_template_uid: Template UID for Twitter images
            linkedin_template_uid: Template UID for LinkedIn carousels
            infographic_template_uid: Template UID for infographics
            thumbnail_template_uid: Template UID for YouTube thumbnails
        """
        self.api_key = api_key or os.getenv("DYNAPICTURES_API_KEY")
        self.base_url = "https://api.dynapictures.com"

        # Template UIDs - you must create these templates in DynaPictures web UI first
        self.twitter_template_uid = twitter_template_uid or os.getenv("DYNAPICTURES_TWITTER_TEMPLATE")
        self.linkedin_template_uid = linkedin_template_uid or os.getenv("DYNAPICTURES_LINKEDIN_TEMPLATE")
        self.infographic_template_uid = infographic_template_uid or os.getenv("DYNAPICTURES_INFOGRAPHIC_TEMPLATE")
        self.thumbnail_template_uid = thumbnail_template_uid or os.getenv("DYNAPICTURES_THUMBNAIL_TEMPLATE")

        # Data directory for generated images
        self.data_dir = Path(__file__).resolve().parent.parent / "data" / "media"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ZAI image generator as fallback
        self.zai_generator = ZAIImageGenerator()

        # Log configuration status
        if not self.api_key and not self.zai_generator.is_configured():
            print("WARNING: No image generation provider configured")
            print("   Option A (DynaPictures): export DYNAPICTURES_API_KEY='your-key'")
            print("   Option B (ZAI): export ZAI_API_KEY='your-key'")
        elif not self.api_key and self.zai_generator.is_configured():
            print("INFO: Using ZAI GLM-Image for image generation (DynaPictures not configured)")
        elif self.api_key:
            print("INFO: Using DynaPictures for template-based image generation")

    def _dynapictures_configured(self) -> bool:
        """Check if DynaPictures API key is set."""
        return bool(self.api_key)

    async def generate_twitter_image(
        self,
        topic: str,
        style: str = "minimal",
        text: Optional[str] = None,
        template_uid: str = None,
    ) -> Dict:
        """
        Generate an image for Twitter post

        Uses DynaPictures if configured with a template, otherwise falls back
        to ZAI GLM-Image for AI-generated images.

        Args:
            topic: Content topic
            style: Visual style (minimal, bold, tech, creative)
            text: Optional text overlay
            template_uid: Override template UID

        Returns:
            Dict with image path and metadata
        """
        # Try DynaPictures first if configured with template
        if self._dynapictures_configured() and (template_uid or self.twitter_template_uid):
            return await self._generate_twitter_image_dynapictures(
                topic, style, text, template_uid
            )

        # Fall back to ZAI if configured
        if self.zai_generator.is_configured():
            return await self._generate_image_zai(topic, "twitter", style)

        # No provider available
        return self._placeholder_response("twitter", topic, style, "No image provider configured")

    async def _generate_twitter_image_dynapictures(
        self,
        topic: str,
        style: str,
        text: Optional[str],
        template_uid: str = None,
    ) -> Dict:
        """Generate Twitter image via DynaPictures API."""
        template_uid = template_uid or self.twitter_template_uid

        try:
            # Build request params - customize based on your template layers
            params = [
                {"name": "canvas", "backgroundColor": self._get_style_color(style)},
                {"name": "title", "text": topic, "color": "#333333"},
            ]

            if text:
                params.append({"name": "text", "text": text, "color": "#555555"})

            # Generate image
            response_data = await self._call_dynapictures_api(template_uid, params)

            if not response_data.get("imageUrl"):
                return {
                    "success": False,
                    "platform": "twitter",
                    "topic": topic,
                    "error": "No image URL in response",
                    "response": response_data,
                }

            # Download image
            timestamp = int(datetime.now(timezone.utc).timestamp())
            output_path = self.data_dir / f"twitter_{topic.replace(' ', '_')}_{timestamp}.png"

            await self._download_image(response_data["imageUrl"], output_path)

            return {
                "success": True,
                "platform": "twitter",
                "topic": topic,
                "style": style,
                "image_path": str(output_path),
                "image_url": response_data["imageUrl"],
                "thumbnail_url": response_data.get("thumbnailUrl"),
                "width": response_data.get("width"),
                "height": response_data.get("height"),
                "provider": "dynapictures",
            }

        except Exception as e:
            # If DynaPictures fails, try ZAI fallback
            if self.zai_generator.is_configured():
                print(f"DynaPictures failed ({e}), falling back to ZAI")
                return await self._generate_image_zai(topic, "twitter", style)

            return {
                "success": False,
                "platform": "twitter",
                "topic": topic,
                "error": str(e),
                "note": f"DynaPictures API error: {e}",
            }

    async def _generate_image_zai(
        self,
        topic: str,
        platform: str,
        style: str = "minimal",
    ) -> Dict:
        """Generate an image via ZAI GLM-Image and download it locally.

        Args:
            topic: Content topic for the image.
            platform: Target platform (twitter, linkedin, instagram, youtube).
            style: Visual style hint.

        Returns:
            Dict with image path, URL, and metadata.
        """
        result = await self.zai_generator.generate_social_image(
            topic=topic,
            platform=platform,
            style=style,
        )

        if not result.get("success"):
            return {
                "success": False,
                "platform": platform,
                "topic": topic,
                "style": style,
                "error": result.get("error", "ZAI image generation failed"),
                "provider": "zai",
            }

        # Download to local storage
        timestamp = int(datetime.now(timezone.utc).timestamp())
        safe_topic = topic.replace(" ", "_")[:50]
        output_path = self.data_dir / f"{platform}_{safe_topic}_{timestamp}.png"

        download_result = await self.zai_generator.download_image(
            result["url"], str(output_path)
        )

        return {
            "success": True,
            "platform": platform,
            "topic": topic,
            "style": style,
            "image_path": str(output_path) if download_result.get("success") else None,
            "image_url": result["url"],
            "width": int(result["size"].split("x")[0]) if result.get("size") else None,
            "height": int(result["size"].split("x")[1]) if result.get("size") else None,
            "provider": "zai",
            "cost": result.get("cost"),
        }

    async def generate_linkedin_carousel(
        self,
        slides_data: List[Dict],
        style: str = "professional",
        template_uid: str = None,
    ) -> Dict:
        """
        Generate LinkedIn carousel (document posts) using multipage templates

        Args:
            slides_data: List of dicts with slide content
                         [{"title": "...", "content": "...", "image": "..."}]
            style: Visual style
            template_uid: Override template UID

        Returns:
            Dict with carousel PDF path and metadata
        """
        if not self.api_key:
            # ZAI does not support multi-page PDF generation, so fall back to placeholder
            return self._placeholder_response("linkedin", "carousel", style, "API key not configured")

        if not template_uid and not self.linkedin_template_uid:
            return self._placeholder_response(
                "linkedin",
                "carousel",
                style,
                "LinkedIn template UID not configured - create multipage template at https://dynapictures.com/",
            )

        template_uid = template_uid or self.linkedin_template_uid

        try:
            # Build multipage request
            pages = []
            for i, slide in enumerate(slides_data):
                layers = [
                    {"name": "title", "text": slide.get("title", ""), "color": "#333333"},
                ]

                if slide.get("content"):
                    layers.append({"name": "content", "text": slide["content"], "color": "#555555"})

                if slide.get("image"):
                    layers.append({"name": "image", "imageUrl": slide["image"]})

                pages.append({"index": i, "layers": layers})

            # Generate PDF
            response_data = await self._call_dynapictures_api(
                template_uid, pages=pages, format="pdf", metadata=f"LinkedIn carousel - {len(slides_data)} slides"
            )

            if not response_data.get("imageUrl"):
                return {
                    "success": False,
                    "platform": "linkedin",
                    "type": "carousel",
                    "error": "No PDF URL in response",
                    "response": response_data,
                }

            # Download PDF
            timestamp = int(datetime.now(timezone.utc).timestamp())
            output_path = self.data_dir / f"linkedin_carousel_{timestamp}.pdf"

            await self._download_image(response_data["imageUrl"], output_path)

            return {
                "success": True,
                "platform": "linkedin",
                "type": "carousel",
                "slide_count": len(slides_data),
                "style": style,
                "output_path": str(output_path),
                "pdf_url": response_data["imageUrl"],
                "provider": "dynapictures",
            }

        except Exception as e:
            return {
                "success": False,
                "platform": "linkedin",
                "type": "carousel",
                "error": str(e),
                "note": f"DynaPictures API error: {e}",
            }

    async def generate_linkedin_image(
        self,
        topic: str,
        style: str = "professional",
    ) -> Dict:
        """Generate a single image for a LinkedIn post.

        Uses DynaPictures if configured, otherwise ZAI, otherwise placeholder.

        Args:
            topic: Content topic.
            style: Visual style.

        Returns:
            Dict with image path and metadata.
        """
        # Try ZAI for simple image generation (DynaPictures needs templates for single images)
        if self.zai_generator.is_configured():
            return await self._generate_image_zai(topic, "linkedin", style)

        return self._placeholder_response("linkedin", topic, style, "No image provider configured")

    async def generate_infographic(
        self,
        data_points: List[Dict],
        title: str,
        style: str = "data_viz",
        template_uid: str = None,
    ) -> Dict:
        """
        Generate infographic from data

        Args:
            data_points: List of dicts with data
                         [{"label": "...", "value": 123}, ...]
            title: Infographic title
            style: Visual style
            template_uid: Override template UID

        Returns:
            Dict with infographic path and metadata
        """
        if not self.api_key:
            return self._placeholder_response("infographic", title, style, "API key not configured")

        if not template_uid and not self.infographic_template_uid:
            return self._placeholder_response(
                "infographic",
                title,
                style,
                "Infographic template UID not configured - create template at https://dynapictures.com/",
            )

        template_uid = template_uid or self.infographic_template_uid

        try:
            # Build request params with chart data
            labels = [dp["label"] for dp in data_points]
            values = [dp["value"] for dp in data_points]

            params = [
                {"name": "title", "text": title, "color": "#333333"},
                {
                    "name": "chart",
                    "chartDataLabels": labels,
                    "chartDataValues": values,
                    "chartColor": "#4A90E2",
                    "chartLabelColor": "#666666",
                },
            ]

            # Generate image
            response_data = await self._call_dynapictures_api(template_uid, params)

            if not response_data.get("imageUrl"):
                return {
                    "success": False,
                    "type": "infographic",
                    "title": title,
                    "error": "No image URL in response",
                    "response": response_data,
                }

            # Download image
            timestamp = int(datetime.now(timezone.utc).timestamp())
            output_path = self.data_dir / f"infographic_{title.replace(' ', '_')}_{timestamp}.png"

            await self._download_image(response_data["imageUrl"], output_path)

            return {
                "success": True,
                "type": "infographic",
                "title": title,
                "data_points": len(data_points),
                "style": style,
                "output_path": str(output_path),
                "image_url": response_data["imageUrl"],
                "width": response_data.get("width"),
                "height": response_data.get("height"),
                "provider": "dynapictures",
            }

        except Exception as e:
            return {
                "success": False,
                "type": "infographic",
                "title": title,
                "error": str(e),
                "note": f"DynaPictures API error: {e}",
            }

    async def generate_thumbnail(
        self,
        title: str,
        topic: str,
        style: str = "youtube",
        template_uid: str = None,
    ) -> Dict:
        """
        Generate YouTube thumbnail

        Uses DynaPictures if configured with a template, otherwise falls back
        to ZAI GLM-Image.

        Args:
            title: Video title
            topic: Main topic
            style: Thumbnail style
            template_uid: Override template UID

        Returns:
            Dict with thumbnail path and metadata
        """
        # Try DynaPictures if configured with template
        if self._dynapictures_configured() and (template_uid or self.thumbnail_template_uid):
            return await self._generate_thumbnail_dynapictures(title, topic, style, template_uid)

        # Fall back to ZAI
        if self.zai_generator.is_configured():
            return await self._generate_image_zai(
                f"{title} - {topic}", "youtube", style
            )

        return self._placeholder_response("thumbnail", title, style, "No image provider configured")

    async def _generate_thumbnail_dynapictures(
        self,
        title: str,
        topic: str,
        style: str,
        template_uid: str = None,
    ) -> Dict:
        """Generate thumbnail via DynaPictures API."""
        template_uid = template_uid or self.thumbnail_template_uid

        try:
            # Build request params
            params = [
                {"name": "title", "text": title, "color": "#FFFFFF"},
                {"name": "topic", "text": topic, "color": "#CCCCCC"},
            ]

            # Generate image
            response_data = await self._call_dynapictures_api(template_uid, params)

            if not response_data.get("imageUrl"):
                return {
                    "success": False,
                    "type": "thumbnail",
                    "title": title,
                    "error": "No image URL in response",
                    "response": response_data,
                }

            # Download image
            timestamp = int(datetime.now(timezone.utc).timestamp())
            safe_title = title.replace(' ', '_')[:50]  # Limit filename length
            output_path = self.data_dir / f"thumbnail_{safe_title}_{timestamp}.png"

            await self._download_image(response_data["imageUrl"], output_path)

            return {
                "success": True,
                "type": "thumbnail",
                "title": title,
                "topic": topic,
                "style": style,
                "output_path": str(output_path),
                "image_url": response_data["imageUrl"],
                "width": response_data.get("width"),
                "height": response_data.get("height"),
                "provider": "dynapictures",
            }

        except Exception as e:
            # If DynaPictures fails, try ZAI fallback
            if self.zai_generator.is_configured():
                print(f"DynaPictures failed ({e}), falling back to ZAI")
                return await self._generate_image_zai(
                    f"{title} - {topic}", "youtube", style
                )

            return {
                "success": False,
                "type": "thumbnail",
                "title": title,
                "error": str(e),
                "note": f"DynaPictures API error: {e}",
            }

    async def generate_social_image(
        self,
        topic: str,
        platform: str,
        style: str = "minimal",
    ) -> Dict:
        """Generate a platform-optimized image for any social platform.

        Unified entry point that routes to the best available provider.

        Args:
            topic: Content topic.
            platform: Target platform (twitter, linkedin, instagram, youtube).
            style: Visual style.

        Returns:
            Dict with image path, URL, and metadata.
        """
        platform_lower = platform.lower()

        # Route to platform-specific methods where DynaPictures templates exist
        if platform_lower in ("twitter", "x"):
            return await self.generate_twitter_image(topic, style)

        if platform_lower == "linkedin":
            return await self.generate_linkedin_image(topic, style)

        # For other platforms, use ZAI directly if available
        if self.zai_generator.is_configured():
            return await self._generate_image_zai(topic, platform_lower, style)

        return self._placeholder_response(platform_lower, topic, style, "No image provider configured")

    async def batch_generate_twitter_images(
        self,
        topics: List[str],
        style: str = "minimal",
    ) -> List[Dict]:
        """
        Generate multiple Twitter images in batch

        Args:
            topics: List of topics
            style: Visual style for all images

        Returns:
            List of generation results
        """
        results = []
        for topic in topics:
            result = await self.generate_twitter_image(topic, style)
            results.append(result)

        return results

    async def _call_dynapictures_api(
        self,
        template_uid: str,
        params: List[Dict] = None,
        pages: List[Dict] = None,
        format: str = "png",
        metadata: str = None,
    ) -> Dict:
        """
        Call DynaPictures REST API

        Args:
            template_uid: Template UID from web UI
            params: List of layer parameters (for single page)
            pages: List of pages (for multipage)
            format: Image format (png, jpeg, pdf)
            metadata: Custom metadata

        Returns:
            API response dict
        """
        url = f"{self.base_url}/designs/{template_uid}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build request body
        body = {"format": format}

        if metadata:
            body["metadata"] = metadata

        if params:
            body["params"] = params

        if pages:
            body["pages"] = pages

        # Make API call
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    async def _download_image(self, url: str, output_path: Path):
        """
        Download image from URL

        Args:
            url: Image URL
            output_path: Local file path to save image
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            response.raise_for_status()

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(response.content)

    def _get_style_color(self, style: str) -> str:
        """Map style names to background colors"""
        style_colors = {
            "minimal": "#FFFFFF",
            "bold": "#1A1A1A",
            "tech": "#0A1929",
            "creative": "#F5F5F5",
            "professional": "#FFFFFF",
            "data_viz": "#FFFFFF",
            "youtube": "#1A1A1A",
        }
        return style_colors.get(style, "#FFFFFF")

    def _placeholder_response(self, platform: str, topic: str, style: str, message: str) -> Dict:
        """Generate a placeholder error response"""
        return {
            "success": False,
            "platform": platform,
            "topic": topic,
            "style": style,
            "error": "No image provider configured",
            "note": message,
            "setup_instructions": {
                "option_a": {
                    "provider": "DynaPictures (template-based)",
                    "1": "Sign up at https://dynapictures.com/",
                    "2": "Create templates in web UI",
                    "3": "Get API key from account page",
                    "4": "Get template UIDs from template pages",
                    "5": "Set environment: export DYNAPICTURES_API_KEY='your-key'",
                    "6": "Set template UIDs in code or environment variables",
                },
                "option_b": {
                    "provider": "ZAI GLM-Image (AI-generated, $0.015/image)",
                    "1": "Get your ZAI API key",
                    "2": "Set environment: export ZAI_API_KEY='your-key'",
                },
            },
        }


# Backwards compatibility alias
GammaMediaGenerator = DynaPicturesMediaGenerator


class ContentToSlideConverter:
    """Convert text content to slide format for DynaPictures"""

    @staticmethod
    def thread_to_slides(thread_content: str) -> List[Dict]:
        """Convert Twitter thread to slides

        Args:
            thread_content: Thread text content

        Returns:
            List of slide dicts
        """
        lines = thread_content.strip().split("\n")
        slides = []

        current_slide = {"title": "", "content": [], "image": None}
        slide_num = 1

        for line in lines:
            line = line.strip()

            if not line:
                continue

            # Check if new slide (numbered line)
            if line.startswith("Tweet ") or line.startswith("Step "):
                if current_slide["title"] or current_slide["content"]:
                    slides.append(current_slide)
                    slide_num += 1
                    current_slide = {"title": f"Tweet {slide_num}", "content": [], "image": None}
                # Extract content after colon
                if ":" in line:
                    current_slide["content"].append(line.split(":", 1)[1].strip())
            elif line.startswith("-") or line.startswith("•"):
                current_slide["content"].append(line[1:].strip())
            else:
                current_slide["content"].append(line)

        # Add last slide
        if current_slide["title"] or current_slide["content"]:
            slides.append(current_slide)

        return slides

    @staticmethod
    def linkedin_post_to_slides(post_content: str) -> List[Dict]:
        """Convert LinkedIn post to slides

        Args:
            post_content: LinkedIn post content

        Returns:
            List of slide dicts
        """
        lines = post_content.strip().split("\n")
        slides = []

        current_slide = {"title": "", "content": [], "image": None}
        slide_num = 1

        for line in lines:
            line = line.strip()

            if not line:
                continue

            # New slide on headers or numbered steps
            if line.startswith("##") or (line[0].isdigit() and "." in line):
                if current_slide["title"] or current_slide["content"]:
                    slides.append(current_slide)
                    slide_num += 1

                if line.startswith("##"):
                    current_slide = {"title": line.replace("##", "").strip(), "content": [], "image": None}
                else:
                    current_slide = {"title": line, "content": [], "image": None}
            else:
                current_slide["content"].append(line)

        # Add last slide
        if current_slide["title"] or current_slide["content"]:
            slides.append(current_slide)

        return slides


async def main():
    """CLI for media generation"""
    import argparse

    parser = argparse.ArgumentParser(description="Generate media with DynaPictures / ZAI")
    parser.add_argument("--generate-twitter", type=str, help="Generate Twitter image from topic")
    parser.add_argument("--generate-social", type=str, help="Generate social image from topic")
    parser.add_argument("--platform", type=str, default="twitter",
                        help="Target platform (twitter, linkedin, instagram, youtube)")
    parser.add_argument("--style", type=str, default="minimal", help="Visual style")
    parser.add_argument("--batch", nargs="+", help="Generate multiple Twitter images")
    parser.add_argument("--template", type=str, help="Override template UID")
    parser.add_argument("--test", action="store_true", help="Test API connectivity")

    args = parser.parse_args()

    generator = DynaPicturesMediaGenerator()

    if args.test:
        print("Testing image generation connectivity...")

        # Check DynaPictures
        if generator.api_key:
            print(f"  DynaPictures API key found: {generator.api_key[:10]}...")
            if generator.twitter_template_uid:
                print(f"  DynaPictures Twitter template: {generator.twitter_template_uid}")
            else:
                print("  DynaPictures Twitter template not configured")
            if generator.linkedin_template_uid:
                print(f"  DynaPictures LinkedIn template: {generator.linkedin_template_uid}")
            else:
                print("  DynaPictures LinkedIn template not configured")
        else:
            print("  DynaPictures: not configured")

        # Check ZAI
        if generator.zai_generator.is_configured():
            zai_key = generator.zai_generator.api_key
            print(f"  ZAI API key found: {zai_key[:10]}...")
            print("  ZAI GLM-Image: ready ($0.015/image)")
        else:
            print("  ZAI: not configured")

        if not generator.api_key and not generator.zai_generator.is_configured():
            print("\nNo image provider configured. Setup options:")
            print("  Option A: export DYNAPICTURES_API_KEY='your-key'")
            print("  Option B: export ZAI_API_KEY='your-key'")
        else:
            print(f"\nOutput directory: {generator.data_dir}")
            print("\nExample usage:")
            print("  python -m media.gamma_generator --generate-twitter 'AI automation'")
            print("  python -m media.gamma_generator --generate-social 'AI agents' --platform linkedin")
            print("  python -m media.gamma_generator --batch AI ML DataScience --style tech")

    elif args.generate_social:
        result = await generator.generate_social_image(
            topic=args.generate_social,
            platform=args.platform,
            style=args.style,
        )
        print(json.dumps(result, indent=2))

    elif args.generate_twitter:
        result = await generator.generate_twitter_image(
            topic=args.generate_twitter,
            style=args.style,
            template_uid=args.template,
        )
        print(json.dumps(result, indent=2))

    elif args.batch:
        results = await generator.batch_generate_twitter_images(
            topics=args.batch,
            style=args.style,
        )
        print(f"Generated {len(results)} images")
        for result in results:
            provider = result.get("provider", "unknown")
            if result.get("success"):
                print(f"  [{provider}] {result.get('topic', 'N/A')}: {result.get('image_path', result.get('image_url', 'N/A'))}")
            else:
                print(f"  [{provider}] {result.get('topic', 'N/A')}: {result.get('error', 'Unknown error')}")


if __name__ == "__main__":
    asyncio.run(main())
