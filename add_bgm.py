"""完成済み動画に Lyria BGM を被せる（Veo の音声は捨ててサイレント＋BGM）。

  uv run --native-tls python add_bgm.py

OUTPUT_DIR/final.mp4 に、作風から導出した Lyria BGM を被せて
OUTPUT_DIR/final_bgm.mp4 を作る。BGMプロンプトは config.BGM_PROMPT_OVERRIDE で固定も可。
"""

from __future__ import annotations

import json
from pathlib import Path

import config
from extract import load_saved_storyboard
from music import bgm_prompt_from_style, generate_bgm
from pipeline import add_bgm


def _total_seconds(sb) -> float:
    secs = [getattr(s, "duration_seconds", None) or config.SCENE_SECONDS for s in sb.scenes]
    return float(sum(secs))


def main() -> None:
    out_dir = Path(config.OUTPUT_DIR)
    video_in = out_dir / "final.mp4"
    if not video_in.exists():
        raise SystemExit(f"動画が見つかりません: {video_in}")

    sb = load_saved_storyboard()
    total = _total_seconds(sb)

    prompt = bgm_prompt_from_style(sb.style)
    print(f"BGMプロンプト: {prompt}")

    bgm_wav = out_dir / "bgm.wav"
    print(f"Lyria でBGM生成中... -> {bgm_wav}")
    generate_bgm(prompt, bgm_wav)

    video_out = out_dir / "final_bgm.mp4"
    print(f"BGMを合成中（{total:.0f}秒, vol={config.BGM_VOLUME}）... -> {video_out}")
    add_bgm(video_in, bgm_wav, video_out, total)
    print(f"完成: {video_out}")


if __name__ == "__main__":
    main()
