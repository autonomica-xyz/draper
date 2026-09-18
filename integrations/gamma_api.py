#!/usr/bin/env python3
"""
Gamma.app API Integration (v1.0)
https://developers.gamma.app/reference/generate-a-gamma

Generates social carousels and presentations via the Gamma public API.
Authentication uses X-API-KEY header with your Gamma API key.
"""

import asyncio
import io
import os
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import httpx

# Platform-to-dimensions mapping for social format
PLATFORM_DIMENSIONS = {
    "linkedin": "4x5",
    "instagram": "4x5",
    "twitter": "1x1",
    "x": "1x1",
    "stories": "9x16",
    "reels": "9x16",
}
MAX_EXPORT_BYTES = 25 * 1024 * 1024
MAX_CARD_IMAGE_BYTES = 10 * 1024 * 1024
MAX_EXPORTED_IMAGES = 20


class GammaAPIClient:
    """
    Client for Gamma.app public API v1.0

    Gamma generates visual presentations and social carousels from text content.
    Requires GAMMA_APP_API_KEY environment variable.

    Usage:
        client = GammaAPIClient()

        # Generate a LinkedIn carousel
        result = await client.generate_carousel(
            content="5 Ways AI Agents Fail...",
            title="AI Agent Failure Modes",
            num_cards=5,
            platform="linkedin"
        )

        # Generate a presentation
        result = await client.generate_presentation(
            content="Quarterly strategy overview...",
            title="Q1 Strategy",
            num_cards=10
        )
    """

    BASE_URL = "https://public-api.gamma.app/v1.0"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Gamma.app API client.

        Args:
            api_key: Gamma API key. If not provided, uses GAMMA_APP_API_KEY env var.
        """
        self.api_key = (
            api_key or os.getenv("GAMMA_APP_API_KEY", "") or os.getenv("GAMMA_APP_KEY", "")
        )
        if not self.api_key:
            print("WARNING: GAMMA_APP_API_KEY not set - Gamma integration will not work")

    def is_configured(self) -> bool:
        """Check if the API key is present and the client can make requests."""
        return bool(self.api_key)

    async def generate_carousel(
        self,
        content: str,
        title: str = "",
        num_cards: int = 5,
        platform: str = "linkedin",
        tone: str = "professional",
        language: str = "en",
    ) -> Dict:
        """
        Generate a social media carousel using Gamma.app.

        Args:
            content: Text content to turn into a carousel.
            title: Carousel title (prepended to content if provided).
            num_cards: Number of cards/slides (default 5).
            platform: Target platform - determines card dimensions.
                      "linkedin" / "instagram" -> 4x5
                      "twitter" / "x" -> 1x1
                      "stories" / "reels" -> 9x16
            tone: Text tone (professional, casual, formal).
            language: Language code (default "en").

        Returns:
            Dict with keys:
                success (bool), gamma_url (str), export_url (str),
                generation_id (str), error (str or None)
        """
        if not self.is_configured():
            return self._error_result("GAMMA_APP_API_KEY not configured")

        dimensions = PLATFORM_DIMENSIONS.get(platform.lower(), "4x5")

        input_text = content
        if title:
            input_text = f"{title}\n\n{content}"

        payload = {
            "inputText": input_text,
            "format": "social",
            "textMode": "preserve",
            "numCards": num_cards,
            "cardSplit": "auto",
            "cardOptions": {
                "dimensions": dimensions,
            },
            "textOptions": {
                "amount": "medium",
                "tone": tone,
                "language": language,
            },
            "imageOptions": {
                "source": "aiGenerated",
            },
            "exportAs": "png",
        }

        return await self._submit_and_poll(payload)

    async def generate_visual_prop(
        self,
        content: str,
        title: str = "",
        platform: str = "linkedin",
        tone: str = "professional",
        language: str = "en",
    ) -> Dict:
        """
        Generate a single-card visual prop image using Gamma.app.

        A visual prop is a single designed image that accompanies a social post.
        Uses Gamma's social format with numCards=1 to produce one card, then
        exports as PNG for inline display.

        Args:
            content: Text content for the visual.
            title: Optional title.
            platform: Target platform for dimensions.
            tone: Text tone.
            language: Language code.

        Returns:
            Same dict shape as generate_carousel.
        """
        return await self.generate_carousel(
            content=content,
            title=title,
            num_cards=1,
            platform=platform,
            tone=tone,
            language=language,
        )

    async def generate_infographic(
        self,
        content: str,
        title: str = "",
        style: str = "polished_flat",
        aspect_ratio: str = "4x5",
        tone: str = "professional",
        language: str = "en",
    ) -> Dict:
        """
        Generate an infographic using Gamma.app.

        Uses Gamma's API with specific instructions to produce data-driven
        infographic layouts — charts, timelines, process flows, statistics.

        Args:
            content: Structured text content (stats, steps, comparisons).
                     Provide explicit data values for best results.
            title: Infographic title.
            style: Illustration style — "polished_flat", "isometric",
                   "watercolor", "doodle", "minimal", "bold".
            aspect_ratio: Dimensions — "4x5" (portrait), "1x1" (square),
                          "16x9" (landscape), "9x16" (story).
            tone: Text tone.
            language: Language code.

        Returns:
            Dict with keys:
                success (bool), gamma_url (str), export_url (str),
                generation_id (str), error (str or None)
        """
        if not self.is_configured():
            return self._error_result("GAMMA_APP_API_KEY not configured")

        input_text = content
        if title:
            input_text = f"{title}\n\n{content}"

        style_guidance = {
            "polished_flat": "Use a clean, flat design style with solid colors and minimal gradients.",
            "isometric": "Use isometric 3D illustration style for icons and elements.",
            "watercolor": "Use soft watercolor-style illustrations with flowing color transitions.",
            "doodle": "Use hand-drawn doodle style with sketch-like icons and borders.",
            "minimal": "Use a minimalist design with lots of whitespace, thin lines, and subtle colors.",
            "bold": "Use bold, high-contrast design with strong typography and vibrant colors.",
        }

        payload = {
            "inputText": input_text,
            "format": "social",
            "textMode": "preserve",
            "numCards": 1,
            "cardSplit": "auto",
            "cardOptions": {
                "dimensions": aspect_ratio,
            },
            "textOptions": {
                "amount": "medium",
                "tone": tone,
                "language": language,
            },
            "imageOptions": {
                "source": "aiGenerated",
            },
            "additionalInstructions": (
                f"Design this as an INFOGRAPHIC, not a simple social card. "
                f"Include visual data representation: charts, icons, statistics with large numbers, "
                f"comparison panels, or timeline elements as appropriate. "
                f"Use structured layout with clear sections. "
                f"{style_guidance.get(style, style_guidance['polished_flat'])} "
                f"Make it visually rich with icons, dividers, and data highlights. "
                f"The output should look like a professional infographic poster."
            ),
            "exportAs": "png",
        }

        return await self._submit_and_poll(payload)

    async def generate_presentation(
        self,
        content: str,
        title: str = "",
        num_cards: int = 10,
        dimensions: str = "16x9",
        tone: str = "professional",
        language: str = "en",
    ) -> Dict:
        """
        Generate a slide presentation using Gamma.app.

        Args:
            content: Text content to turn into a presentation.
            title: Presentation title (prepended to content if provided).
            num_cards: Number of slides (default 10).
            dimensions: Slide dimensions - "fluid", "16x9", or "4x3".
            tone: Text tone (professional, casual, formal).
            language: Language code (default "en").

        Returns:
            Dict with keys:
                success (bool), gamma_url (str), export_url (str),
                generation_id (str), error (str or None)
        """
        if not self.is_configured():
            return self._error_result("GAMMA_APP_API_KEY not configured")

        input_text = content
        if title:
            input_text = f"{title}\n\n{content}"

        payload = {
            "inputText": input_text,
            "format": "presentation",
            "textMode": "preserve",
            "numCards": num_cards,
            "cardSplit": "auto",
            "cardOptions": {
                "dimensions": dimensions,
            },
            "textOptions": {
                "amount": "medium",
                "tone": tone,
                "language": language,
            },
            "imageOptions": {
                "source": "aiGenerated",
            },
            "exportAs": "pdf",
        }

        return await self._submit_and_poll(payload)

    async def _submit_and_poll(self, payload: Dict, timeout: int = 120) -> Dict:
        """
        Submit a generation request and poll until completion.

        Args:
            payload: Request body for the generations endpoint.
            timeout: Max seconds to wait for completion (default 120).

        Returns:
            Result dict with success, gamma_url, export_url, generation_id, error.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Submit generation request
                response = await client.post(
                    f"{self.BASE_URL}/generations",
                    headers={
                        "X-API-KEY": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            generation_id = data.get("generationId")
            if not generation_id:
                return self._error_result(
                    "No generationId in API response",
                    raw_response=data,
                )

            # Poll for completion
            return await self._poll_generation(generation_id, timeout=timeout)

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            print(f"Gamma API HTTP {status}: {e.response.text[:500]}")
            return self._error_result(
                f"Gamma API HTTP {status}",
                generation_id=None,
            )
        except httpx.TimeoutException:
            return self._error_result("Gamma API request timed out")
        except Exception as e:
            print(f"Gamma API request failed: {e}")
            return self._error_result("Gamma API request failed")

    async def _poll_generation(
        self,
        generation_id: str,
        timeout: int = 120,
    ) -> Dict:
        """
        Poll the generation status endpoint until complete or timeout.

        Uses exponential backoff: 2s, 4s, 8s, then 10s intervals.

        Args:
            generation_id: The generation ID returned from the submit call.
            timeout: Max seconds to wait (default 120).

        Returns:
            Result dict with success, gamma_url, export_url, generation_id, error.
        """
        url = f"{self.BASE_URL}/generations/{generation_id}"
        headers = {
            "X-API-KEY": self.api_key,
        }

        start_time = time.monotonic()
        poll_interval = 2.0  # Start at 2 seconds

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    return self._error_result(
                        f"Generation timed out after {timeout}s",
                        generation_id=generation_id,
                    )

                await asyncio.sleep(poll_interval)

                try:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    # Transient errors -- keep polling
                    if status in (429, 500, 502, 503, 504):
                        poll_interval = min(poll_interval * 2, 10.0)
                        continue
                    try:
                        body = e.response.json()
                    except Exception:
                        body = e.response.text
                    return self._error_result(
                        f"Poll HTTP {status}: {body}",
                        generation_id=generation_id,
                    )
                except (httpx.TimeoutException, httpx.ConnectError):
                    # Network hiccup -- keep polling
                    poll_interval = min(poll_interval * 2, 10.0)
                    continue

                status_value = data.get("status", "")

                if status_value == "completed":
                    gamma_url = data.get("gammaUrl", "")
                    # Build export URL from the gamma URL if not provided directly
                    export_url = data.get("exportUrl", "")
                    if not export_url and gamma_url:
                        export_url = f"{gamma_url}/pdf"

                    return {
                        "success": True,
                        "gamma_url": gamma_url,
                        "export_url": export_url,
                        "generation_id": generation_id,
                        "credits": data.get("credits"),
                        "error": None,
                    }

                if status_value in ("failed", "error"):
                    return self._error_result(
                        f"Generation failed: {data.get('error', status_value)}",
                        generation_id=generation_id,
                    )

                # Still processing -- back off gradually
                poll_interval = min(poll_interval * 1.5, 10.0)

    @staticmethod
    def _error_result(
        error: str,
        generation_id: Optional[str] = None,
        raw_response: Optional[Dict] = None,
    ) -> Dict:
        """Build a standardised error result dict."""
        result = {
            "success": False,
            "gamma_url": "",
            "export_url": "",
            "generation_id": generation_id or "",
            "error": error,
        }
        if raw_response is not None:
            result["raw_response"] = raw_response
        return result

    async def download_card_images(
        self,
        export_url: str,
        dest_dir: str,
        generation_id: str,
    ) -> List[str]:
        """Download the PNG export and extract individual card images.

        Handles both zip archives (multi-card) and direct PNG images (single card).

        Args:
            export_url: The signed export URL from Gamma.
            dest_dir: Base directory for cached media (e.g. data/media).
            generation_id: Used as subfolder name.

        Returns:
            List of relative file paths to extracted PNG images, sorted by name.
        """
        out_dir = Path(dest_dir) / "carousels" / generation_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # Check cache
        existing = sorted(out_dir.glob("*.png"))
        if existing:
            return [str(p) for p in existing]

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(export_url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            content = response.content
        if len(content) > MAX_EXPORT_BYTES:
            raise ValueError("Gamma export is too large")

        # Direct image (single card / visual prop)
        if content_type.startswith("image/") or not self._is_zip(content):
            if len(content) > MAX_CARD_IMAGE_BYTES:
                raise ValueError("Gamma image is too large")
            out_path = out_dir / f"{generation_id}.png"
            out_path.write_bytes(content)
            return [str(out_path)]

        # ZIP archive (multi-card carousel)
        zip_bytes = io.BytesIO(content)
        extracted = []
        with zipfile.ZipFile(zip_bytes) as zf:
            png_infos = [
                info
                for info in zf.infolist()
                if info.filename.lower().endswith(".png") and not info.is_dir()
            ]
            if len(png_infos) > MAX_EXPORTED_IMAGES:
                raise ValueError("Gamma export contains too many images")
            for info in sorted(png_infos, key=lambda item: item.filename):
                if info.file_size > MAX_CARD_IMAGE_BYTES:
                    raise ValueError("Gamma export image is too large")
                data = zf.read(info)
                out_path = out_dir / Path(info.filename).name
                out_path.write_bytes(data)
                extracted.append(str(out_path))

        return extracted

    @staticmethod
    def _is_zip(data: bytes) -> bool:
        """Check if bytes start with ZIP magic number."""
        return len(data) >= 4 and data[:4] == b"PK\x03\x04"


# Example usage
async def main():
    """Test Gamma.app client"""
    client = GammaAPIClient()

    if not client.is_configured():
        print("GAMMA_APP_API_KEY is not set. Skipping test.")
        return

    # Generate a carousel
    print("Generating LinkedIn carousel...")
    result = await client.generate_carousel(
        content=(
            "5 Ways AI Agents Fail\n\n"
            "1. Hallucination Loop\n"
            "2. Infinite Tool Calls\n"
            "3. Context Overflow\n"
            "4. Misaligned Objectives\n"
            "5. No Error Recovery"
        ),
        title="AI Agent Failure Modes",
        num_cards=5,
        platform="linkedin",
    )

    if result["success"]:
        print(f"Carousel URL: {result['gamma_url']}")
        print(f"Export PDF:   {result['export_url']}")
    else:
        print(f"Error: {result['error']}")

    # Generate a presentation
    print("\nGenerating presentation...")
    presentation = await client.generate_presentation(
        content=(
            "Confidential AI keeps data safe. "
            "Attestation proves trust. "
            "No more data leaks. "
            "Verifiable isolation."
        ),
        title="Confidential AI Explained",
        num_cards=6,
    )

    if presentation["success"]:
        print(f"Presentation URL: {presentation['gamma_url']}")
        print(f"Export PDF:       {presentation['export_url']}")
    else:
        print(f"Error: {presentation['error']}")


if __name__ == "__main__":
    asyncio.run(main())
