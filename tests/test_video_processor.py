import asyncio
import os
import tempfile
from pathlib import Path
import pytest
from bot.services.video_processor import process_video, MAX_VIDEO_SIZE


@pytest.mark.asyncio
async def test_video_processing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        synth_input = tmp_path / "test_synth.mp4"

        # Generate a 1-second synthetic MP4 test clip with FFmpeg
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=640x360:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(synth_input)
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        assert synth_input.exists(), "Synthetic test video generation failed"

        with open(synth_input, "rb") as f:
            raw_bytes = f.read()

        # Run our video processing service
        webm_bytes = await process_video(raw_bytes, temp_dir=tmp_path)

        assert len(webm_bytes) > 0
        assert len(webm_bytes) <= MAX_VIDEO_SIZE

        # Verify output with ffprobe
        out_file = tmp_path / "result.webm"
        with open(out_file, "wb") as f:
            f.write(webm_bytes)

        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=width,height,codec_name:format=duration",
            "-of", "default=noprint_wrappers=1",
            str(out_file)
        ]
        probe_proc = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await probe_proc.communicate()
        probe_text = stdout.decode("utf-8")

        assert "codec_name=vp9" in probe_text
        assert "width=512" in probe_text
