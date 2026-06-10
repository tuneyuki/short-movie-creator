"""Veo でシーンを生成し、ffmpeg で連結するパイプライン。"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import imageio_ffmpeg
from google import genai
from google.genai import types

import config


def _client() -> genai.Client:
    """Vertex AI バックエンドのクライアント。認証は ADC。"""
    return genai.Client(
        vertexai=True,
        project=config.PROJECT_ID,
        location=config.LOCATION,
    )


class SafetyBlocked(RuntimeError):
    """セーフティ/利用規約フィルタでプロンプトが拒否された。"""


class RefsUnsupported(RuntimeError):
    """このモデルがリファレンス画像に対応していない（allowlist 未許可など）。"""


def _scene_reference_images(
    char_names: list[str], char_images: dict[str, Path]
) -> list[types.VideoGenerationReferenceImage] | None:
    """シーンに登場する人物の画像を Veo の ASSET リファレンス（最大3）に変換。"""
    refs: list[types.VideoGenerationReferenceImage] = []
    for name in char_names[:3]:  # Veo のリファレンス画像は最大3枚
        path = char_images.get(name)
        if path and path.exists():
            refs.append(
                types.VideoGenerationReferenceImage(
                    image=types.Image(
                        image_bytes=path.read_bytes(), mime_type="image/png"
                    ),
                    reference_type="ASSET",
                )
            )
    return refs or None


def _generate_once(
    client: genai.Client,
    prompt: str,
    out_path: Path,
    reference_images: list[types.VideoGenerationReferenceImage] | None,
    duration: int,
) -> Path:
    cfg = types.GenerateVideosConfig(
        number_of_videos=1,
        duration_seconds=duration,
        aspect_ratio=config.ASPECT_RATIO,
        resolution=config.RESOLUTION,
        person_generation=config.PERSON_GENERATION,
    )
    if reference_images:
        cfg.reference_images = reference_images

    try:
        op = client.models.generate_videos(model=config.MODEL, prompt=prompt, config=cfg)
        # 生成は非同期。完了までポーリングする（通常 1〜3分）。
        while not op.done:
            time.sleep(15)
            op = client.operations.get(op)
    except Exception as e:  # 送信時エラー（400/404 等）を分類
        _classify_error(str(e), bool(reference_images))
        raise

    if op.error:
        _classify_error(str(op.error), bool(reference_images))
        raise RuntimeError(f"Veo 生成エラー: {op.error}")
    return _save_video(op, out_path)


def _classify_error(msg: str, has_refs: bool) -> None:
    """既知のエラーを専用例外に変換する（未知ならそのまま戻る）。"""
    low = msg.lower()
    if has_refs and ("not supported by this model" in low or "failed_precondition" in low):
        raise RefsUnsupported(msg)
    if "usage guidelines" in low or "violate" in low or "safety" in low:
        raise SafetyBlocked(msg)


def _save_video(op, out_path: Path) -> Path:
    resp = op.response
    videos = resp.generated_videos
    if not videos:
        reasons = getattr(resp, "rai_media_filtered_reasons", None) or []
        if reasons:
            print(f"  RAIフィルタ理由: {' / '.join(reasons)}")
            raise SafetyBlocked("RAI media filtered: " + " / ".join(reasons))
        raise RuntimeError("動画が返ってきませんでした（フィルタ等で拒否された可能性）")

    video = videos[0].video
    if not video.video_bytes:
        raise RuntimeError(
            "動画バイト列が空です。output_gcs_uri を使う構成の可能性があります。"
        )

    out_path.write_bytes(video.video_bytes)
    return out_path


def generate_scene(
    client: genai.Client,
    prompt: str,
    out_path: Path,
    reference_images: list[types.VideoGenerationReferenceImage] | None = None,
    duration: int = config.SCENE_SECONDS,
) -> Path:
    """1シーン生成。

    - リファレンス画像が非対応のモデルなら、画像を外してテキストのみで再試行する
      （人物の容姿はプロンプトに埋め込み済み）。
    - セーフティでブロックされたらプロンプトを穏当化して再試行する。
    """
    for attempt in range(3):
        try:
            return _generate_once(client, prompt, out_path, reference_images, duration)
        except RefsUnsupported:
            if reference_images is None:
                raise
            print(
                "  このモデルは人物画像リファレンス非対応。"
                "画像を外し、容姿はプロンプトのテキストで反映して再試行..."
            )
            reference_images = None
        except SafetyBlocked:
            if attempt == 2:
                raise
            from extract import soften_prompt

            print("  セーフティでブロック。プロンプトを穏当化して再試行...")
            prompt = soften_prompt(prompt)
    raise AssertionError("unreachable")


def _concat_cmd(ffmpeg: str, clips: list[Path], out_path: Path, with_audio: bool) -> list[str]:
    n = len(clips)
    clip_s = config.CLIP_SECONDS  # 各クリップを先頭この秒数にトリム（None なら全長）
    cmd: list[str] = [ffmpeg, "-y"]
    for clip in clips:
        cmd += ["-i", str(clip)]

    # concat フィルタで連結（解像度/コーデック差異も吸収できる）。
    # CLIP_SECONDS 指定時は各入力を trim/atrim で先頭だけ切り出してから繋ぐ。
    pre: list[str] = []
    labels = ""
    for i in range(n):
        if clip_s:
            pre.append(f"[{i}:v:0]trim=0:{clip_s},setpts=PTS-STARTPTS[v{i}]")
            labels += f"[v{i}]"
            if with_audio:
                pre.append(f"[{i}:a:0]atrim=0:{clip_s},asetpts=PTS-STARTPTS[a{i}]")
                labels += f"[a{i}]"
        else:
            labels += f"[{i}:v:0]" + (f"[{i}:a:0]" if with_audio else "")

    if with_audio:
        pre.append(f"{labels}concat=n={n}:v=1:a=1[v][a]")
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac"]
    else:
        pre.append(f"{labels}concat=n={n}:v=1:a=0[v]")
        maps = ["-map", "[v]"]

    cmd += ["-filter_complex", ";".join(pre), *maps]
    if config.TRIM_SECONDS:
        cmd += ["-t", str(config.TRIM_SECONDS)]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)]
    return cmd


def concat(clips: list[Path], out_path: Path) -> Path:
    """複数クリップを連結する。音声があれば含め、無ければ自動で映像のみにフォールバック。"""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if config.WITH_AUDIO:
        r = subprocess.run(_concat_cmd(ffmpeg, clips, out_path, True))
        if r.returncode == 0:
            return out_path
        print("  音声付き連結に失敗。映像のみで再試行...")
    subprocess.run(_concat_cmd(ffmpeg, clips, out_path, False), check=True)
    return out_path


def add_bgm(
    video_in: Path,
    bgm_wav: Path,
    video_out: Path,
    total_seconds: float,
    volume: float | None = None,
) -> Path:
    """動画の音声を捨て、BGM(WAV)を被せて mux する（サイレント映像＋BGM）。

    BGM は音量を下げ、頭にフェードイン・尻にフェードアウトを付け、動画尺に合わせて切る。
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    vol = config.BGM_VOLUME if volume is None else volume
    fade_out_st = max(0.0, total_seconds - 2.0)
    afilter = (
        f"[1:a]volume={vol},"
        f"afade=t=in:st=0:d=1.5,"
        f"afade=t=out:st={fade_out_st}:d=2[a]"
    )
    cmd = [
        ffmpeg, "-y",
        "-i", str(video_in),
        "-i", str(bgm_wav),
        "-filter_complex", afilter,
        "-map", "0:v", "-map", "[a]",   # 0:v=映像のみ（元音声は捨てる）, BGMを音声に
        "-t", str(total_seconds),
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        str(video_out),
    ]
    subprocess.run(cmd, check=True)
    return video_out


def add_dub(
    video_in: Path,
    bgm_wav: Path,
    tts_clips: list[tuple[Path, float]],
    video_out: Path,
    total_seconds: float,
    bgm_volume: float | None = None,
    tts_volume: float | None = None,
) -> Path:
    """サイレント映像に BGM + 各シーンのセリフ(TTS)を合成して mux する。

    tts_clips: [(wav, offset_seconds)] … offset はそのセリフを差し込む開始位置。
    BGM は bed として下げ、各 TTS は adelay で所定位置に配置し amix で混ぜる。
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    bvol = config.DUB_BGM_VOLUME if bgm_volume is None else bgm_volume
    tvol = config.TTS_VOLUME if tts_volume is None else tts_volume
    fade_out_st = max(0.0, total_seconds - 2.0)

    cmd: list[str] = [ffmpeg, "-y", "-i", str(video_in), "-i", str(bgm_wav)]
    for wav, _ in tts_clips:
        cmd += ["-i", str(wav)]

    parts: list[str] = []
    # BGM（入力1）: 音量↓・フェード・48k/stereo化
    parts.append(
        f"[1:a]volume={bvol},afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_st}:d=2,"
        f"aformat=sample_rates=48000:channel_layouts=stereo[bgm]"
    )
    labels = "[bgm]"
    # 各TTS（入力2..）: 所定位置へ遅延・音量↑・48k/stereo化
    for k, (_, off) in enumerate(tts_clips):
        ms = int(off * 1000)
        parts.append(
            f"[{2 + k}:a]adelay={ms}|{ms},volume={tvol},"
            f"aformat=sample_rates=48000:channel_layouts=stereo[s{k}]"
        )
        labels += f"[s{k}]"
    n_in = 1 + len(tts_clips)
    parts.append(
        f"{labels}amix=inputs={n_in}:normalize=0:duration=longest,"
        f"alimiter=limit=0.95[a]"  # 加算で割れないよう最後にリミッタ
    )

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "0:v", "-map", "[a]",   # 映像のみ＋合成音声（Veo元音声は捨てる）
        "-t", str(total_seconds),
        "-c:v", "copy", "-c:a", "aac",
        str(video_out),
    ]
    subprocess.run(cmd, check=True)
    return video_out


def run(sb=None, char_images: dict[str, Path] | None = None) -> Path:
    """絵コンテ全体を生成 → 連結 → 動画を出力する。

    sb（Storyboard）を渡すと作風・人物リファレンス付きで生成。
    None の場合は storyboard.py の SCENES をプレーンに使う（--manual 相当）。
    """
    from extract import build_prompt

    out_dir = Path(config.OUTPUT_DIR)
    out_dir.mkdir(exist_ok=True)
    char_images = char_images or {}

    if sb is None:
        from storyboard import SCENES

        scenes_prompts = [(p, [], config.SCENE_SECONDS) for p in SCENES]
    else:
        char_map = {c.name: c for c in sb.characters}
        scenes_prompts = []
        for s in sb.scenes:
            scene_chars = [char_map[n] for n in s.characters if n in char_map]
            dur = s.duration_seconds if s.duration_seconds in config.ALLOWED_DURATIONS else config.SCENE_SECONDS
            # 容姿はプロンプトにも埋め込む（画像ref非対応モデルでのフォールバック用）
            scenes_prompts.append(
                (build_prompt(s, sb.style, scene_chars), s.characters, dur)
            )

    client = _client()
    clips: list[Path] = []
    for i, (prompt, char_names, dur) in enumerate(scenes_prompts):
        clip_path = out_dir / f"scene_{i:02d}.mp4"
        if clip_path.exists():
            print(f"[{i + 1}/{len(scenes_prompts)}] 既存をスキップ -> {clip_path}")
            clips.append(clip_path)
            continue
        # リファレンス画像(reference_to_video)は尺8秒のみ対応。8秒シーンだけ ref を付ける。
        refs = _scene_reference_images(char_names, char_images) if dur == 8 else None
        tag = (f"人物ref {len(refs)}枚 / " if refs else "") + f"{dur}秒"
        print(f"[{i + 1}/{len(scenes_prompts)}] シーン生成中（{tag}）... -> {clip_path}")
        generate_scene(client, prompt, clip_path, refs, dur)
        clips.append(clip_path)

    final = out_dir / "final.mp4"
    print(f"連結中... -> {final}")
    concat(clips, final)
    print(f"完成: {final}")
    return final
