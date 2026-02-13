"""
Optimize videos for web streaming by adding fast-start.

This moves the moov atom to the beginning of each video file,
enabling instant seeking in web browsers.

PREREQUISITES:
1. Install ffmpeg: winget install ffmpeg
2. Azure CLI logged in: az login

USAGE:
python optimize_videos.py
"""

import os
import subprocess
import tempfile
from pathlib import Path

# Configuration
STORAGE_ACCOUNT = "stj6lw7vswhnnhw"
CONTAINER = "video-mp4"
TEMP_DIR = Path(tempfile.gettempdir()) / "video-optimize"


def run_cmd(cmd, description):
    """Run a command and return output."""
    print(f"  {description}...")
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[:200]}")
        return None
    return result.stdout.strip()


def list_videos():
    """List all mp4 files in the container."""
    cmd = f'az storage blob list --container-name {CONTAINER} --account-name {STORAGE_ACCOUNT} --query "[].name" -o tsv'
    output = run_cmd(cmd, "Listing videos")
    if output:
        return [name for name in output.split('\n') if name.endswith('.mp4')]
    return []


def download_video(blob_name, local_path):
    """Download a video from blob storage."""
    cmd = f'az storage blob download --container-name {CONTAINER} --name "{blob_name}" --file "{local_path}" --account-name {STORAGE_ACCOUNT} --only-show-errors'
    return run_cmd(cmd, f"Downloading") is not None


def upload_video(local_path, blob_name):
    """Upload a video to blob storage."""
    cmd = f'az storage blob upload --container-name {CONTAINER} --name "{blob_name}" --file "{local_path}" --account-name {STORAGE_ACCOUNT} --overwrite --only-show-errors'
    return run_cmd(cmd, f"Uploading") is not None


def optimize_video(input_path, output_path):
    """Re-encode video with keyframes for proper seeking + fast-start."""
    # Full re-encode with regular keyframes (required for seeking)
    # -c:v libx264 = H.264 video codec
    # -preset fast = balance between speed and compression
    # -crf 23 = good quality (lower = better, 18-28 is reasonable)
    # -g 60 = keyframe every 60 frames (~2 sec at 30fps)
    # -keyint_min 30 = minimum keyframe interval
    # -c:a aac = AAC audio codec
    # -movflags +faststart = moov atom at beginning for instant playback
    cmd = f'ffmpeg -i "{input_path}" -c:v libx264 -preset fast -crf 23 -g 60 -keyint_min 30 -c:a aac -movflags +faststart "{output_path}" -y -loglevel error'
    return run_cmd(cmd, "Re-encoding (this takes a while)") is not None


def check_already_optimized(video_path):
    """Check if video already has fast-start (moov atom at beginning)."""
    # Use ffprobe to check atom order
    cmd = f'ffprobe -v quiet -show_entries format_tags=encoder -of default=noprint_wrappers=1 "{video_path}"'
    # This is a simplified check - in practice, we'll just re-process all videos
    return False


def main():
    # Check ffmpeg is installed
    result = subprocess.run("ffmpeg -version", capture_output=True, shell=True)
    if result.returncode != 0:
        print("ERROR: ffmpeg not found. Install it first:")
        print("  winget install ffmpeg")
        print("  (or download from https://ffmpeg.org/download.html)")
        return

    # Create temp directory
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # List videos
    print(f"\nListing videos in {CONTAINER}...")
    videos = list_videos()

    if not videos:
        print("No videos found!")
        return

    print(f"Found {len(videos)} videos to optimize.\n")

    # Process each video
    success = 0
    failed = 0

    for i, blob_name in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}] {blob_name}")

        # Paths
        input_path = TEMP_DIR / f"input_{i}.mp4"
        output_path = TEMP_DIR / f"output_{i}.mp4"

        try:
            # Download
            if not download_video(blob_name, str(input_path)):
                failed += 1
                continue

            # Optimize
            if not optimize_video(str(input_path), str(output_path)):
                failed += 1
                continue

            # Upload
            if not upload_video(str(output_path), blob_name):
                failed += 1
                continue

            success += 1
            print(f"  Done!")

        finally:
            # Clean up temp files
            if input_path.exists():
                input_path.unlink()
            if output_path.exists():
                output_path.unlink()

    print(f"\n{'='*50}")
    print(f"Complete! {success} optimized, {failed} failed")
    print(f"Videos now support instant seeking in browsers.")


if __name__ == "__main__":
    main()
