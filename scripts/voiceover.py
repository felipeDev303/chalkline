"""Synthesize the demo video's voice-over with Azure AI Speech, one WAV per scene.

Usage: uv run python scripts/voiceover.py [--voice en-GB-RyanNeural]

Reads the voice-over column of docs/VIDEO.md (so script and audio never drift apart)
and writes data/voiceover/NN_<start>.wav plus a timing summary. Keyless: the Foundry
account named by FOUNDRY_PROJECT_ENDPOINT (kind AIServices) includes Speech; `az
login` and the "Cognitive Services Speech User" role on that account are enough.
Never reads a .env file.
"""

from __future__ import annotations

import argparse
import os
import re
import wave
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import httpx
from azure.identity import DefaultAzureCredential

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs" / "VIDEO.md"
OUT = ROOT / "data" / "voiceover"
FORMAT = "riff-24khz-16bit-mono-pcm"  # WAV: any editor takes it, and its length is exact
LIMIT_S = 120.0

# Spoken forms for things a voice reads badly.
SAY = {
    "0.014": "zero point zero one four",
    "35 to 40 percent": "thirty-five to forty percent",
}


def tts_endpoint() -> str:
    """Speech endpoint of the Foundry account named by FOUNDRY_PROJECT_ENDPOINT."""
    project = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not project:
        raise SystemExit("set FOUNDRY_PROJECT_ENDPOINT (infra/foundry.bicep output)")
    account = (urlparse(project).hostname or "").split(".")[0]
    return f"https://{account}.cognitiveservices.azure.com/tts/cognitiveservices/v1"


def scenes() -> list[tuple[str, str]]:
    """(start time, voice-over) for each row of the script's table."""
    out = []
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (\d:\d\d)-\d:\d\d \|.*\| \"(.+)\" \|$", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def ssml(text: str, voice: str) -> str:
    for written, spoken in SAY.items():
        text = text.replace(written, spoken)
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-GB">'
        f'<voice name="{voice}"><prosody rate="-4%">{escape(text)}</prosody></voice></speak>'
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default="en-GB-RyanNeural")
    args = parser.parse_args()
    rows = scenes()
    if not rows:
        raise SystemExit(f"no voice-over rows found in {SCRIPT}")
    endpoint = tts_endpoint()
    token = DefaultAzureCredential().get_token("https://cognitiveservices.azure.com/.default")
    headers = {"Authorization": f"Bearer {token.token}",
               "Content-Type": "application/ssml+xml",
               "X-Microsoft-OutputFormat": FORMAT, "User-Agent": "chalkline-voiceover"}
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0.0
    clips = []  # (start seconds, frames, params)
    with httpx.Client(timeout=60) as client:
        for i, (start, text) in enumerate(rows, start=1):
            r = client.post(endpoint, headers=headers, content=ssml(text, args.voice).encode())
            r.raise_for_status()
            path = OUT / f"{i:02d}_{start.replace(':', '-')}.wav"
            path.write_bytes(r.content)
            with wave.open(str(path)) as w:
                seconds = w.getnframes() / w.getframerate()
                clips.append((_seconds(start), w.readframes(w.getnframes()), w.getparams()))
            total += seconds
            print(f"{path.name}: {seconds:5.1f} s  (scene starts at {start})")
    verdict = "fits" if total < LIMIT_S else "TOO LONG: trim the script"
    print(f"total speech {total:.1f} s of {LIMIT_S:.0f} s: {verdict}")
    full_track(clips)


def _seconds(mark: str) -> float:
    minutes, seconds = mark.split(":")
    return int(minutes) * 60 + int(seconds)


GAP_S = 0.3  # least silence between two clips


def full_track(clips: list) -> None:
    """One WAV with each clip at its scene's start, pushed later if the one before runs
    over (keeping GAP_S of silence); prints where each clip landed."""
    params = clips[0][2]
    frame = params.sampwidth * params.nchannels
    bytes_per_s = params.framerate * frame
    audio = bytearray()
    for i, (start, frames, _) in enumerate(clips, start=1):
        earliest = len(audio) + (int(GAP_S * bytes_per_s) if audio else 0)
        at = max(int(start * bytes_per_s), earliest) // frame * frame
        audio += bytes(at - len(audio)) + frames
        print(f"  clip {i} at {at / bytes_per_s:5.1f} s (script: {start:.0f} s)")
    with wave.open(str(OUT / "full_voiceover.wav"), "wb") as w:
        w.setparams(params)
        w.writeframes(bytes(audio))
    print(f"full_voiceover.wav: {len(audio) / bytes_per_s:.1f} s")


if __name__ == "__main__":
    main()
