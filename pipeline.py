#!/usr/bin/env python3
"""
Draper Marketing Pipeline - Main Controller
End-to-end pipeline: Generate → Review → Schedule
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Add modules to path
sys.path.insert(0, str(Path(__file__).parent))

from generator.llm_content_generator import LLMContentGenerator
from feedback import FeedbackManager
from orchestrator.social_orchestrator import SocialOrchestrator
from media.gamma_generator import GammaMediaGenerator
from media.video_generator import VideoGenerator


class MarketingPipeline:
    """Main pipeline controller for autonomous marketing"""

    def __init__(
        self,
        slack_channel: str = None,
        batch_size: int = 10,
        generate_media: bool = False
    ):
        self.generator = LLMContentGenerator()
        self.feedback_manager = FeedbackManager(data_dir=str(Path(__file__).resolve().parent / "data"))
        self.orchestrator = SocialOrchestrator()
        self.media_generator = GammaMediaGenerator()
        self.video_generator = VideoGenerator()
        self.batch_size = batch_size
        self.generate_media = generate_media

        self.data_dir = Path(__file__).resolve().parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _check_generator_config(self) -> bool:
        """Check if LLM generator is configured"""
        import os
        if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
            print("⚠️  No LLM API key found. Content generation requires API key.")
            print("   Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.")
            print("   Example: export ANTHROPIC_API_KEY='your-anthropic-api-key'")
            return False
        return True

    def run_daily_generation(self) -> Dict:
        """Generate daily batch of content and post to Slack for review"""
        # Check API key configuration
        if not self._check_generator_config():
            return {
                "success": False,
                "error": "LLM API key not configured"
            }

        print(f"\n🤖 Generating daily batch of {self.batch_size} posts...")

        # Generate batch
        batch_result = self.generator.generate_batch(
            count=self.batch_size,
            platforms=["twitter", "linkedin"]
        )
        batch = batch_result.get("posts", [])

        print(f"✅ Generated {len(batch)} posts")

        # Post each for review
        review_results = []
        for post in batch:
            result = self.feedback_manager.post_content_for_review(post)
            review_results.append({
                "post": post,
                "result": result
            })

        print(f"✅ Posted {len(review_results)} posts to Slack for review")

        # Save batch metadata
        self._save_batch_metadata(batch, review_results)

        return {
            "success": True,
            "generated": len(batch),
            "posted_for_review": len(review_results),
            "batch_id": datetime.now(timezone.utc).isoformat()
        }

    def process_approved_queue(self) -> Dict:
        """Process approved posts and schedule them"""
        print(f"\n📅 Processing approved posts...")

        # Get approved posts
        approved = self.feedback_manager.get_scheduled_posts()

        if not approved:
            print("✅ No approved posts to schedule")
            return {
                "success": True,
                "scheduled": 0,
                "message": "No approved posts"
            }

        print(f"📝 Found {len(approved)} approved posts")

        scheduled_count = 0
        for item in approved:
            post_data = item["post_data"]
            platform = post_data["platform"]

            # Schedule post
            result = self.orchestrator.schedule_post(
                post_data=post_data,
                platform=platform
            )

            if result.get("success"):
                scheduled_count += 1
                print(f"  ✅ Scheduled {platform} post: {post_data['topic']}")
            else:
                print(f"  ❌ Failed to schedule {platform} post: {result.get('error')}")

            # Update feedback manager status
            # This would clear it from the approved queue

        print(f"✅ Scheduled {scheduled_count}/{len(approved)} posts")

        return {
            "success": True,
            "scheduled": scheduled_count,
            "total": len(approved)
        }

    def get_pipeline_status(self) -> Dict:
        """Get overall pipeline status"""
        pending_reviews = self.feedback_manager.get_pending_reviews()
        approved_posts = self.feedback_manager.get_scheduled_posts()
        scheduled = self.orchestrator.get_scheduled_posts()

        # Generate breakdown by platform
        twitter_pending = [p for p in pending_reviews if p["post_data"]["platform"] == "twitter"]
        linkedin_pending = [p for p in pending_reviews if p["post_data"]["platform"] == "linkedin"]
        twitter_approved = [p for p in approved_posts if p["post_data"]["platform"] == "twitter"]
        linkedin_approved = [p for p in approved_posts if p["post_data"]["platform"] == "linkedin"]
        twitter_scheduled = [p for p in scheduled if p["platform"] == "twitter"]
        linkedin_scheduled = [p for p in scheduled if p["platform"] == "linkedin"]

        return {
            "pending_reviews": {
                "total": len(pending_reviews),
                "twitter": len(twitter_pending),
                "linkedin": len(linkedin_pending)
            },
            "approved_awaiting_schedule": {
                "total": len(approved_posts),
                "twitter": len(twitter_approved),
                "linkedin": len(linkedin_approved)
            },
            "scheduled_posts": {
                "total": len(scheduled),
                "twitter": len(twitter_scheduled),
                "linkedin": len(linkedin_scheduled)
            }
        }

    def _save_batch_metadata(self, batch: list, review_results: list):
        """Save batch metadata for tracking"""
        batch_file = self.data_dir / "batches.json"

        if batch_file.exists():
            with open(batch_file, 'r') as f:
                batches = json.load(f)
        else:
            batches = {}

        batch_id = datetime.now(timezone.utc).isoformat()

        batches[batch_id] = {
            "generated_at": batch_id,
            "count": len(batch),
            "platforms": [p["platform"] for p in batch],
            "pillars": [p["pillar"] for p in batch],
            "review_results": [
                {
                    "platform": r["post"]["platform"],
                    "topic": r["post"]["topic"],
                    "success": r["result"]["success"]
                }
                for r in review_results
            ]
        }

        with open(batch_file, 'w') as f:
            json.dump(batches, f, indent=2)

    def generate_media_for_posts(self, posts: List[Dict]) -> Dict:
        """Generate media (images, graphics) for posts

        Args:
            posts: List of generated posts

        Returns:
            Dict with generation results
        """
        if not self.generate_media:
            return {
                "success": True,
                "generated": 0,
                "message": "Media generation disabled"
            }

        print(f"\n🎨 Generating media for {len(posts)} posts...")

        results = []
        for post in posts:
            # Generate Twitter image if needed
            if post["platform"] == "twitter":
                result = self.media_generator.generate_twitter_image(
                    topic=post["topic"],
                    style="minimal"
                )
                results.append(result)

        successful = sum(1 for r in results if r.get("success"))
        print(f"✅ Generated media for {successful}/{len(posts)} posts")

        return {
            "success": True,
            "total": len(posts),
            "generated": successful,
            "results": results
        }

    def generate_youtube_video_from_content(
        self,
        content_data: Dict,
        output_path: Optional[str] = None
    ) -> Dict:
        """Generate YouTube video from content (thread or post)

        Args:
            content_data: Content from ContentGenerator
            output_path: Optional output video path

        Returns:
            Dict with video generation result
        """
        from media.gamma_generator import ContentToSlideConverter

        print(f"\n🎬 Generating YouTube video from: {content_data['topic']}")

        # Convert content to slides
        if content_data["platform"] == "twitter" and content_data["content_type"] == "thread":
            slides = ContentToSlideConverter.thread_to_slides(content_data["content"])
        elif content_data["platform"] == "linkedin":
            slides = ContentToSlideConverter.linkedin_post_to_slides(content_data["content"])
        else:
            # Single slide for other content
            slides = [{
                "title": content_data["topic"],
                "content": [content_data["content"][:200]],
                "image": None
            }]

        # Generate images for slides (placeholder)
        # In production, would call Gamma API
        print(f"  📝 Converted to {len(slides)} slides")

        # Generate video
        result = self.video_generator.generate_youtube_video(
            slides_data=slides,
            output_path=output_path,
            duration_per_slide=8.0
        )

        if result["success"]:
            print(f"  ✅ Video generated: {result['output']}")
        else:
            print(f"  ❌ Failed: {result.get('error')}")

        return result

    def generate_youtube_batch(
        self,
        count: int = 3,
        pillar: Optional[str] = None
    ) -> Dict:
        """Generate batch of YouTube videos from content

        Args:
            count: Number of videos to generate
            pillar: Content pillar (optional)

        Returns:
            Dict with generation results
        """
        print(f"\n🎬 Generating {count} YouTube videos...")

        # Generate content
        batch_result = self.generator.generate_batch(
            count=count,
            platforms=["linkedin"],  # Longer content works better for video
            pillars=[pillar] if pillar else None
        )
        batch = batch_result.get("posts", [])

        print(f"  📝 Generated {len(batch)} content items")

        # Generate videos from content
        results = []
        for item in batch:
            result = self.generate_youtube_video_from_content(item)
            results.append({
                "content": item,
                "video_result": result
            })

        successful = sum(1 for r in results if r["video_result"].get("success"))
        print(f"\n✅ Generated {successful}/{len(results)} YouTube videos")

        return {
            "success": True,
            "total": len(batch),
            "generated": successful,
            "results": results
        }

    def print_status(self):
        """Pretty-print pipeline status"""
        status = self.get_pipeline_status()

        print("\n" + "="*60)
        print("📊 DRAPER MARKETING PIPELINE STATUS")
        print("="*60)

        print(f"\n📝 Pending Reviews:")
        print(f"   Total: {status['pending_reviews']['total']}")
        print(f"   Twitter: {status['pending_reviews']['twitter']}")
        print(f"   LinkedIn: {status['pending_reviews']['linkedin']}")

        print(f"\n✅ Approved (Awaiting Schedule):")
        print(f"   Total: {status['approved_awaiting_schedule']['total']}")
        print(f"   Twitter: {status['approved_awaiting_schedule']['twitter']}")
        print(f"   LinkedIn: {status['approved_awaiting_schedule']['linkedin']}")

        print(f"\n📅 Scheduled Posts:")
        print(f"   Total: {status['scheduled_posts']['total']}")
        print(f"   Twitter: {status['scheduled_posts']['twitter']}")
        print(f"   LinkedIn: {status['scheduled_posts']['linkedin']}")

        print("\n" + "="*60 + "\n")


def main():
    """CLI for pipeline management"""
    import argparse

    parser = argparse.ArgumentParser(description="Draper Marketing Pipeline")
    parser.add_argument("--generate", action="store_true", help="Run daily content generation")
    parser.add_argument("--generate-with-media", action="store_true", help="Generate content with media")
    parser.add_argument("--process", action="store_true", help="Process approved queue and schedule posts")
    parser.add_argument("--status", action="store_true", help="Show pipeline status")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of posts to generate")
    parser.add_argument("--channel", help="Slack channel ID for content review")
    parser.add_argument("--run-full", action="store_true", help="Generate + Process in one run")
    parser.add_argument("--generate-youtube", action="store_true", help="Generate YouTube videos")
    parser.add_argument("--youtube-count", type=int, default=3, help="Number of YouTube videos to generate")
    parser.add_argument("--pillar", type=str, help="Content pillar for YouTube videos")

    args = parser.parse_args()

    pipeline = MarketingPipeline(
        slack_channel=args.channel,
        batch_size=args.batch_size,
        generate_media=args.generate_with_media
    )

    if args.status:
        pipeline.print_status()

    elif args.generate_with_media:
        print("Generating content with media...")
        gen_result = pipeline.run_daily_generation()
        # Get posts from batch file
        batch_file = pipeline.data_dir / "batches.json"
        if batch_file.exists():
            with open(batch_file, 'r') as f:
                batches = json.load(f)
            latest_batch = list(batches.values())[-1]
            # Generate media for posts (placeholder implementation)
            media_result = pipeline.generate_media_for_posts(
                [{"topic": "test"}] * gen_result["generated"]
            )
        print(f"\n✅ Generation complete:")
        print(f"   Generated: {gen_result['generated']}")
        print(f"   Posted for review: {gen_result['posted_for_review']}")

    elif args.generate:
        result = pipeline.run_daily_generation()
        print(f"\n✅ Generation complete:")
        print(f"   Generated: {result['generated']}")
        print(f"   Posted for review: {result['posted_for_review']}")

    elif args.generate_youtube:
        result = pipeline.generate_youtube_batch(
            count=args.youtube_count,
            pillar=args.pillar
        )
        print(f"\n✅ YouTube generation complete:")
        print(f"   Total: {result['total']}")
        print(f"   Generated: {result['generated']}")

    elif args.process:
        result = pipeline.process_approved_queue()
        print(f"\n✅ Processing complete:")
        print(f"   Scheduled: {result['scheduled']}/{result['total']}")

    elif args.run_full:
        print("Running full pipeline...")
        gen_result = pipeline.run_daily_generation()
        proc_result = pipeline.process_approved_queue()

        print("\n" + "="*60)
        print("🚀 FULL PIPELINE RUN COMPLETE")
        print("="*60)
        print(f"Generated: {gen_result['generated']}")
        print(f"Posted for review: {gen_result['posted_for_review']}")
        print(f"Scheduled: {proc_result['scheduled']}/{proc_result['total']}")
        print("="*60)


if __name__ == "__main__":
    main()
