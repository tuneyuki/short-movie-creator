"""完成済み動画に Lyria BGM + Gemini TTS のセリフを合成する。

  uv run --native-tls python dub.py

OUTPUT_DIR/final.mp4 を入力に、Veo音声は捨て、
  ・Lyria BGM（bed）
  ・各シーンのセリフ(TTS)をシーン開始位置に配置
を合成して OUTPUT_DIR/final_dub.mp4 を作る。BGM(bgm.wav)が既にあれば流用。
"""

from __future__ import annotations

from pathlib import Path

import config
from extract import load_saved_storyboard
from music import bgm_prompt_from_style, generate_bgm
from pipeline import add_dub
from tts import synthesize_scenes


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

    # BGM（既存があれば流用）
    bgm_wav = out_dir / "bgm.wav"
    if not bgm_wav.exists():
        prompt = bgm_prompt_from_style(sb.style)
        print(f"BGMプロンプト: {prompt}")
        print(f"Lyria でBGM生成中... -> {bgm_wav}")
        generate_bgm(prompt, bgm_wav)
    else:
        print(f"既存BGMを流用: {bgm_wav}")

    # 各シーンのセリフを音声化（キャラ別ボイス）
    print("TTS でセリフ生成中...")
    clips = synthesize_scenes(sb, out_dir, total)
    tts_clips = [(wav, off) for (_, wav, _, off) in clips]

    video_out = out_dir / "final_dub.mp4"
    print(f"BGM+セリフを合成中（{total:.0f}秒）... -> {video_out}")
    add_dub(video_in, bgm_wav, tts_clips, video_out, total)
    print(f"完成: {video_out}")


if __name__ == "__main__":
    main()
