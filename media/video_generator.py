#!/usr/bin/env python3
"""
Video Generator using FFmpeg
Creates videos from slides with Ken Burns effect for YouTube
"""

import json
import subprocess
from typing import Dict, List, Tuple, Optional
from pathlib import Path


class KenBurnsEffect:
    """Ken Burns effect parameters for video generation"""

    @staticmethod
    def calculate_pan_zoom(
        width: int,
        height: int,
        duration: float,
        effect_type: str = "zoom_in"
    ) -> Tuple[str, str]:
        """Calculate pan/zoom filter string for FFmpeg

        Args:
            width: Image width
            height: Image height
            duration: Duration in seconds
            effect_type: zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down

        Returns:
            Tuple of (scale filter, overlay filter)
        """
        # Ken Burns effect: subtle zoom/pan over time
        zoom_factor = 1.1  # 10% zoom
        pan_offset = width * 0.05  # 5% pan

        if effect_type == "zoom_in":
            # Zoom from 110% to 100%
            scale_filter = f"scale=iw*{zoom_factor}:-1,zoompan=z='min(zoom+0.0015,1.5)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=width:height:d={int(duration)}:fps=30"
        elif effect_type == "zoom_out":
            # Zoom from 100% to 110%
            scale_filter = f"scale=iw*{zoom_factor}:-1,zoompan=z='max(zoom-0.0015,1.0)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=width:height:d={int(duration)}:fps=30"
        elif effect_type == "pan_left":
            # Pan from right to left
            scale_filter = f"scale=iw*{zoom_factor}:-1,zoompan=z=1.1:d=1:x='iw/zoom-(iw/zoom/2+{pan_offset}*t/{duration})':y='ih/2-(ih/zoom/2)':s=width:height:d={int(duration)}:fps=30"
        elif effect_type == "pan_right":
            # Pan from left to right
            scale_filter = f"scale=iw*{zoom_factor}:-1,zoompan=z=1.1:d=1:x='iw/zoom-(iw/zoom/2-{pan_offset}*t/{duration})':y='ih/2-(ih/zoom/2)':s=width:height:d={int(duration)}:fps=30"
        else:
            # Default: gentle zoom in
            scale_filter = f"scale=iw*1.1:-1,zoompan=z='min(zoom+0.0015,1.5)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920:1080:d={int(duration)}:fps=30"

        overlay_filter = None
        return scale_filter, overlay_filter


class VideoGenerator:
    """Generate videos from slides using FFmpeg"""

    def __init__(
        self,
        output_dir: str = None,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30
    ):
        if output_dir is None:
            output_dir = str(Path(__file__).resolve().parent.parent / "data" / "videos")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.width = width
        self.height = height
        self.fps = fps

    def check_ffmpeg(self) -> bool:
        """Check if FFmpeg is installed"""
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def generate_image_video(
        self,
        image_path: str,
        duration: float = 5.0,
        effect_type: str = "zoom_in",
        output_path: Optional[str] = None
    ) -> Dict:
        """Generate video from single image with Ken Burns effect

        Args:
            image_path: Path to source image
            duration: Duration in seconds
            effect_type: Ken Burns effect type
            output_path: Output video path

        Returns:
            Dict with result and output path
        """
        if not self.check_ffmpeg():
            return {
                "success": False,
                "error": "FFmpeg not installed"
            }

        if not output_path:
            output_path = str(self.output_dir / f"{Path(image_path).stem}_video.mp4")

        # Calculate Ken Burns filter
        scale_filter, overlay_filter = KenBurnsEffect.calculate_pan_zoom(
            self.width,
            self.height,
            duration,
            effect_type
        )

        # Build FFmpeg command
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-loop", "1",
            "-i", image_path,
            "-vf", scale_filter,
            "-c:v", "libx264",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-r", str(self.fps),
            output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )

            return {
                "success": True,
                "input": image_path,
                "output": output_path,
                "duration": duration,
                "effect": effect_type,
                "resolution": f"{self.width}x{self.height}"
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": e.stderr,
                "command": " ".join(cmd)
            }

    def generate_slideshow_video(
        self,
        image_paths: List[str],
        durations: List[float],
        effects: List[str],
        output_path: Optional[str] = None,
        transition: str = "fade",
        transition_duration: float = 0.5,
        audio_path: Optional[str] = None
    ) -> Dict:
        """Generate slideshow video from multiple images

        Args:
            image_paths: List of image paths
            durations: Duration per slide (seconds)
            effects: Ken Burns effect per slide
            output_path: Output video path
            transition: Transition type (fade, dissolve, none)
            transition_duration: Duration of transitions (seconds)
            audio_path: Optional audio file path

        Returns:
            Dict with result and output path
        """
        if not self.check_ffmpeg():
            return {
                "success": False,
                "error": "FFmpeg not installed"
            }

        if len(image_paths) != len(durations) or len(image_paths) != len(effects):
            return {
                "success": False,
                "error": "image_paths, durations, and effects must have same length"
            }

        if not output_path:
            output_path = str(self.output_dir / f"slideshow_{Path(__file__).stem}.mp4")

        # Generate individual videos for each image
        temp_videos = []
        for i, (img_path, duration, effect) in enumerate(zip(image_paths, durations, effects)):
            temp_output = str(self.output_dir / f"temp_{i}.mp4")
            result = self.generate_image_video(img_path, duration, effect, temp_output)

            if result["success"]:
                temp_videos.append(temp_output)
            else:
                return {
                    "success": False,
                    "error": f"Failed to generate video for {img_path}"
                }

        # Concatenate videos
        concat_list_path = str(self.output_dir / "concat_list.txt")
        with open(concat_list_path, "w") as f:
            for video_path in temp_videos:
                f.write(f"file '{video_path}'\n")

        # Build FFmpeg concat command
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy"
        ]

        # Add audio if provided
        if audio_path:
            cmd.extend([
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest"
            ])

        cmd.append(output_path)

        try:
            subprocess.run(cmd, capture_output=True, check=True)

            # Clean up temp files
            for temp_video in temp_videos:
                Path(temp_video).unlink(missing_ok=True)
            Path(concat_list_path).unlink(missing_ok=True)

            return {
                "success": True,
                "output": output_path,
                "slides": len(image_paths),
                "total_duration": sum(durations),
                "transition": transition,
                "audio": audio_path is not None
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": e.stderr,
                "command": " ".join(cmd)
            }

    def generate_youtube_video(
        self,
        slides_data: List[Dict],
        output_path: Optional[str] = None,
        duration_per_slide: float = 8.0,
        audio_path: Optional[str] = None
    ) -> Dict:
        """Generate YouTube video from slide data

        Args:
            slides_data: List of slide dicts with "image" and "text" keys
            output_path: Output video path
            duration_per_slide: Duration per slide (seconds)
            audio_path: Optional background audio

        Returns:
            Dict with result and metadata
        """
        image_paths = []
        durations = []
        effects = []

        # Determine effect for each slide (alternate between zoom_in and zoom_out)
        for i, slide in enumerate(slides_data):
            image_path = slide.get("image")
            if not image_path:
                # Generate placeholder image if none provided
                continue

            image_paths.append(image_path)
            durations.append(duration_per_slide)

            # Alternate effects for visual variety
            if i % 2 == 0:
                effects.append("zoom_in")
            else:
                effects.append("zoom_out")

        if not image_paths:
            return {
                "success": False,
                "error": "No images provided in slides_data"
            }

        if not output_path:
            output_path = str(self.output_dir / f"youtube_{Path(__file__).stem}.mp4")

        result = self.generate_slideshow_video(
            image_paths=image_paths,
            durations=durations,
            effects=effects,
            output_path=output_path,
            transition="fade",
            transition_duration=0.5,
            audio_path=audio_path
        )

        return result

    def generate_text_video(
        self,
        text: str,
        duration: float = 10.0,
        output_path: Optional[str] = None
    ) -> Dict:
        """Generate video with text overlay

        Args:
            text: Text to display
            duration: Video duration
            output_path: Output video path

        Returns:
            Dict with result and output path
        """
        if not output_path:
            output_path = str(self.output_dir / f"text_{Path(__file__).stem}.mp4")

        # Generate solid background (dark for Draper branding)
        # Drawtext filter for text overlay
        text_filter = f"drawtext=text='{text}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.7:boxborderw=10"

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={self.width}x{self.height}:d={duration}",
            "-vf", text_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", str(self.fps),
            output_path
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)

            return {
                "success": True,
                "output": output_path,
                "text": text,
                "duration": duration
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": e.stderr,
                "command": " ".join(cmd)
            }


def main():
    """CLI for video generation"""
    import argparse

    parser = argparse.ArgumentParser(description="Generate videos with FFmpeg")
    parser.add_argument("--check", action="store_true", help="Check FFmpeg installation")
    parser.add_argument("--image", type=str, help="Generate video from single image")
    parser.add_argument("--duration", type=float, default=5.0, help="Duration in seconds")
    parser.add_argument("--effect", type=str, default="zoom_in",
                       choices=["zoom_in", "zoom_out", "pan_left", "pan_right"],
                       help="Ken Burns effect type")
    parser.add_argument("--slideshow", nargs="+", help="Generate slideshow from images")
    parser.add_argument("--audio", type=str, help="Background audio file")

    args = parser.parse_args()

    generator = VideoGenerator()

    if args.check:
        if generator.check_ffmpeg():
            print("✅ FFmpeg is installed and working")
            result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
            print(result.stdout.decode().split('\n')[0])
        else:
            print("❌ FFmpeg is not installed")

    elif args.image:
        result = generator.generate_image_video(
            image_path=args.image,
            duration=args.duration,
            effect_type=args.effect
        )
        print(json.dumps(result, indent=2))

    elif args.slideshow:
        # Generate slideshow with equal durations
        durations = [5.0] * len(args.slideshow)
        effects = ["zoom_in" if i % 2 == 0 else "zoom_out" for i in range(len(args.slideshow))]

        result = generator.generate_slideshow_video(
            image_paths=args.slideshow,
            durations=durations,
            effects=effects,
            audio_path=args.audio
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
