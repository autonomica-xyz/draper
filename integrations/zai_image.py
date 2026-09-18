#!/usr/bin/env python3
"""
ZAI GLM-Image API Integration
Generates images using ZAI's GLM-Image model for social media content.

API: POST https://api.z.ai/api/paas/v4/images/generations
Model: glm-image
Cost: $0.015/image
Size constraints: 512-2048px, multiples of 32

SETUP:
1. Get your ZAI API key
2. Set environment variable: export ZAI_API_KEY="your-key"
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import httpx

# Platform-optimized image sizes (width x height)
PLATFORM_SIZES = {
    "twitter": "1568x1056",  # 3:2 landscape
    "x": "1568x1056",  # alias for twitter
    "linkedin": "1280x1280",  # 1:1 square
    "instagram": "1056x1568",  # 2:3 portrait (close to 4:5)
    "youtube": "1728x960",  # 16:9 landscape
    "default": "1280x1280",  # 1:1 square
}

# Aspect ratio to recommended size mapping
ASPECT_RATIO_SIZES = {
    "1:1": "1280x1280",
    "3:2": "1568x1056",
    "2:3": "1056x1568",
    "16:9": "1728x960",
    "9:16": "960x1728",
}


class ZAIImageGenerator:
    """Generate images using ZAI's GLM-Image API"""

    def __init__(self):
        """Initialize ZAI image generator.

        Loads ZAI_API_KEY from environment variables.
        """
        self.api_key = os.getenv("ZAI_API_KEY", "")
        self.api_url = "https://api.z.ai/api/paas/v4/images/generations"
        self.model = "glm-image"
        self.timeout = 30.0
        self.cost_per_image = 0.015

        # Data directory for downloaded images
        self.data_dir = Path(__file__).resolve().parent.parent / "data" / "media"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if not self.api_key:
            print("WARNING: ZAI_API_KEY not set")
            print("   Set it with: export ZAI_API_KEY='your-key'")

    def is_configured(self) -> bool:
        """Check if API key is present and non-empty."""
        return bool(self.api_key)

    async def generate_image(
        self,
        prompt: str,
        size: str = "1280x1280",
        aspect_ratio: Optional[str] = None,
    ) -> Dict:
        """Generate an image from a text prompt using GLM-Image.

        Args:
            prompt: Text description of the image to generate.
            size: Image dimensions as 'WIDTHxHEIGHT' (512-2048, multiples of 32).
                  Ignored if aspect_ratio is provided.
            aspect_ratio: Optional aspect ratio string (e.g. '1:1', '16:9').
                          Overrides size with a recommended dimension.

        Returns:
            Dict with keys: success, url, error (on failure), provider, size, prompt.
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "ZAI_API_KEY not configured",
                "provider": "zai",
            }

        # Resolve size from aspect ratio if provided
        if aspect_ratio and aspect_ratio in ASPECT_RATIO_SIZES:
            size = ASPECT_RATIO_SIZES[aspect_ratio]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            # Extract image URL from response: data[0].url
            image_url = None
            if "data" in data and len(data["data"]) > 0:
                image_url = data["data"][0].get("url")

            if not image_url:
                return {
                    "success": False,
                    "error": "No image URL in response",
                    "provider": "zai",
                    "response": data,
                }

            return {
                "success": True,
                "url": image_url,
                "provider": "zai",
                "size": size,
                "prompt": prompt,
                "cost": self.cost_per_image,
            }

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Request timed out (30s)",
                "provider": "zai",
            }
        except httpx.HTTPStatusError as e:
            print(f"ZAI image API HTTP {e.response.status_code}: {e.response.text[:500]}")
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}",
                "provider": "zai",
            }
        except Exception as e:
            print(f"ZAI image generation failed: {e}")
            return {
                "success": False,
                "error": "Image generation failed",
                "provider": "zai",
            }

    async def generate_social_image(
        self,
        topic: str,
        platform: str,
        style: str = "minimal",
    ) -> Dict:
        """Generate a platform-optimized image for social media.

        Builds a descriptive prompt from the topic and style, then calls
        generate_image with the correct dimensions for the target platform.

        Args:
            topic: Subject matter of the image.
            platform: Target platform (twitter, linkedin, instagram, youtube).
            style: Visual style hint (minimal, bold, tech, creative, professional).

        Returns:
            Dict with keys: success, url, platform, topic, style, size, error, provider.
        """
        platform_lower = platform.lower()
        size = PLATFORM_SIZES.get(platform_lower, PLATFORM_SIZES["default"])

        # Build a descriptive prompt that incorporates style
        style_descriptors = {
            "minimal": "clean, minimalist design with ample whitespace",
            "bold": "bold, high-contrast design with strong visual impact",
            "tech": "modern technology aesthetic, dark theme with glowing accents",
            "creative": "creative, colorful illustration style",
            "professional": "professional, corporate-quality visual",
        }
        style_desc = style_descriptors.get(style, "clean, professional design")

        prompt = (
            f"Social media image about {topic}. "
            f"Style: {style_desc}. "
            f"Suitable for {platform} posting. "
            f"No text overlays, visually striking, high quality."
        )

        result = await self.generate_image(prompt=prompt, size=size)

        # Enrich the result with social context
        result["platform"] = platform_lower
        result["topic"] = topic
        result["style"] = style
        result["size"] = size

        return result

    async def download_image(self, url: str, save_path: str) -> Dict:
        """Download an image from a URL and save it locally.

        Args:
            url: Remote image URL to download.
            save_path: Local filesystem path to save the image to.

        Returns:
            Dict with keys: success, local_path, error (on failure).
        """
        try:
            output_path = Path(save_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()

                with open(output_path, "wb") as f:
                    f.write(response.content)

            return {
                "success": True,
                "local_path": str(output_path),
            }

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Download timed out (30s)",
            }
        except httpx.HTTPStatusError as e:
            print(f"ZAI image download HTTP {e.response.status_code}: {e.response.text[:500]}")
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}",
            }
        except Exception as e:
            print(f"ZAI image download failed: {e}")
            return {
                "success": False,
                "error": "Image download failed",
            }

    async def generate_and_download(
        self,
        prompt: str,
        size: str = "1280x1280",
        aspect_ratio: Optional[str] = None,
        save_dir: Optional[str] = None,
    ) -> Dict:
        """Generate an image and download it to local storage.

        Convenience method that combines generate_image and download_image.

        Args:
            prompt: Text description of the image.
            size: Image dimensions.
            aspect_ratio: Optional aspect ratio override.
            save_dir: Directory to save the image in. Defaults to data/media.

        Returns:
            Dict with keys: success, url, local_path, error, provider, size, prompt.
        """
        result = await self.generate_image(
            prompt=prompt,
            size=size,
            aspect_ratio=aspect_ratio,
        )

        if not result.get("success"):
            return result

        # Build output path
        target_dir = Path(save_dir) if save_dir else self.data_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(datetime.now(timezone.utc).timestamp())
        safe_prompt = prompt[:40].replace(" ", "_").replace("/", "_")
        filename = f"zai_{safe_prompt}_{timestamp}.png"
        output_path = target_dir / filename

        download_result = await self.download_image(result["url"], str(output_path))

        if download_result.get("success"):
            result["local_path"] = download_result["local_path"]
        else:
            result["download_error"] = download_result.get("error")

        return result
