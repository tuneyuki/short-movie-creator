"""Gemini TTS で各シーンのセリフを音声化する（キャラごとに声を割り当て）。

返ってくるのは raw PCM (L16 24kHz mono) なので WAV に包んで保存する。
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel

import config

# Gemini TTS のプリセット音声。トーン/性別のヒント付き（公式の voice 一覧より）。
VOICE_HINTS = {
    # --- female ---
    "Zephyr": "bright, female",
    "Kore": "firm, female",
    "Leda": "youthful, female",
    "Aoede": "breezy, female",
    "Callirrhoe": "easy-going, female",
    "Autonoe": "bright, female",
    "Despina": "smooth, female",
    "Erinome": "clear, female",
    "Gacrux": "mature, calm, female",      # 落ち着いた成熟女性（妖艶役向き）
    "Sulafat": "warm, female",
    "Achernar": "soft, female",
    "Vindemiatrix": "gentle, female",
    "Pulcherrima": "forward, female",
    # --- male ---
    "Puck": "upbeat, male",
    "Charon": "deep, informative, male",
    "Fenrir": "excitable, bright, male",
    "Orus": "firm, male",
    "Enceladus": "breathy, male",
    "Iapetus": "clear, male",
    "Algieba": "smooth, male",
    "Algenib": "gravelly, rough, male",    # ザラついた荒い男性（チンピラ役向き）
    "Alnilam": "firm, male",
    "Schedar": "even, male",
    "Rasalgethi": "informative, male",
    "Sadaltager": "knowledgeable, male",
    "Umbriel": "easy-going, male",
}
DEFAULT_VOICE = "Charon"


class _VoiceAssign(BaseModel):
    name: str   # キャラ名
    voice: str  # 割り当てた音声名


def _client(loc: str) -> genai.Client:
    return genai.Client(vertexai=True, project=config.PROJECT_ID, location=loc)


def assign_voices(sb) -> dict[str, str]:
    """各キャラに Gemini TTS の音声を割り当てる。

    config.VOICE_OVERRIDES の指定が最優先。残りを Gemini が容姿/性格から自動選択する。
    """
    overrides = {k: v for k, v in getattr(config, "VOICE_OVERRIDES", {}).items()
                 if v in VOICE_HINTS}
    remaining = [c for c in sb.characters if c.name not in overrides]
    if not remaining:
        return dict(overrides)
    options = "\n".join(f"- {v}: {h}" for v, h in VOICE_HINTS.items())
    chars = "\n".join(f"- {c.name}: {c.description}" for c in sb.characters)
    client = _client(config.GEMINI_LOCATION)
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=f"登場人物:\n{chars}\n\n音声候補:\n{options}",
        config=types.GenerateContentConfig(
            system_instruction=(
                "各登場人物に最も合う音声を、音声候補の名前から1つずつ割り当てる。"
                "性別と性格が合うものを選ぶ。なるべく重複させない。"
            ),
            response_mime_type="application/json",
            response_schema=list[_VoiceAssign],
            temperature=0.3,
        ),
    )
    assigns: list[_VoiceAssign] = resp.parsed or []
    # overrides を最優先、その上に Gemini の割当（override 済みキャラは無視）
    valid = dict(overrides)
    for a in assigns:
        if a.voice in VOICE_HINTS and a.name not in valid:
            valid[a.name] = a.voice
    # 抜け漏れは未使用の候補から補完
    pool = [v for v in VOICE_HINTS if v not in valid.values()] or list(VOICE_HINTS)
    for c in sb.characters:
        if c.name not in valid:
            valid[c.name] = pool.pop(0) if pool else DEFAULT_VOICE
    return valid


def voice_for_scene(scene, char_voices: dict[str, str]) -> str:
    """シーンの話者に対応する音声を決める。"""
    for n in scene.characters:
        if n in char_voices:
            return char_voices[n]
    spk = scene.speaker or ""
    for name, v in char_voices.items():
        if name.split()[0] in spk:  # 話者テキストにキャラ名が含まれれば一致
            return v
    return DEFAULT_VOICE


class _SpeechStart(BaseModel):
    speaks: bool
    start_seconds: float


def detect_speech_start(clip_path: Path) -> float | None:
    """シーン映像をGeminiで解析し、人物が話し始める秒数を返す（不可なら None）。"""
    if not clip_path.exists():
        return None
    try:
        client = _client(config.VISION_LOCATION)
        resp = client.models.generate_content(
            model=config.VISION_MODEL,
            contents=[
                types.Part.from_bytes(
                    data=clip_path.read_bytes(), mime_type="video/mp4"
                ),
                "この動画で人物が口を動かして話し始める瞬間は、先頭から何秒後か。"
                "話す人物がいなければ speaks=false。",
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SpeechStart,
                temperature=0,
            ),
        )
        r: _SpeechStart = resp.parsed
        if r and r.speaks and r.start_seconds >= 0:
            return float(r.start_seconds)
    except Exception as e:
        print(f"  （口の動き検出に失敗: {str(e).splitlines()[0][:60]}）")
    return None


def synthesize(text: str, voice: str, out_wav: Path) -> tuple[Path, float]:
    """セリフ1行を音声化して WAV 保存（PCM L16 24kHz を WAV に包む）。返り: (path, 秒)。"""
    client = _client(config.TTS_LOCATION)
    resp = client.models.generate_content(
        model=config.TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    pcm = resp.candidates[0].content.parts[0].inline_data.data
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)        # 16-bit
        w.setframerate(24000)    # L16 24kHz
        w.writeframes(pcm)
    return out_wav, len(pcm) / 2 / 24000  # 秒（16bit mono 24kHz）


def synthesize_scenes(
    sb, out_dir: Path, total_seconds: float
) -> list[tuple[int, Path, str, float]]:
    """各シーンのセリフを音声化。返り値: [(scene_index, wav, voice, offset_seconds)]。

    offset は基本シーン開始位置だが、セリフがシーン尾で動画終端を超える場合は
    終端に収まるよう前倒しする（直前のセリフ終わりとは重ねない）。
    """
    char_voices = assign_voices(sb)
    print(f"ボイス割当: {char_voices}")

    # まず全セリフを合成し、(index, wav, voice, target_start, dur) を集める。
    # target_start = シーン開始 + リードイン（映像で口が動き出すまでの間）。
    # リードインはシーンごとに上書き可（TTS_LEAD_IN_PER_SCENE、1始まり）。
    default_lead = getattr(config, "TTS_LEAD_IN", 0.0)
    per_scene = getattr(config, "TTS_LEAD_IN_PER_SCENE", {})
    auto = getattr(config, "TTS_LEAD_IN_AUTO", False)
    raw: list[tuple[int, Path, str, float, float]] = []
    start = 0.0
    for i, s in enumerate(sb.scenes):
        dur = getattr(s, "duration_seconds", None) or config.SCENE_SECONDS
        if s.dialogue.strip():
            # リードイン決定: 手動指定 > 自動検出 > デフォルト
            if (i + 1) in per_scene:
                lead, src = per_scene[i + 1], "手動"
            elif auto and (d := detect_speech_start(out_dir / f"scene_{i:02d}.mp4")) is not None:
                lead, src = d, "自動検出"
            else:
                lead, src = default_lead, "既定"
            voice = voice_for_scene(s, char_voices)
            wav = out_dir / f"tts_{i:02d}.wav"
            _, tts_dur = synthesize(s.dialogue, voice, wav)
            print(f"  S{i + 1}: リードイン {lead:.1f}s（{src}）/ ボイス {voice}")
            raw.append((i, wav, voice, start + lead, tts_dur))
        start += dur

    # 終端超過を前倒しで吸収（前のセリフ終端とは重ねない）
    results: list[tuple[int, Path, str, float]] = []
    last_end = 0.0
    for i, wav, voice, scene_start, tts_dur in raw:
        off = scene_start
        if off + tts_dur > total_seconds:
            off = total_seconds - tts_dur
        off = max(off, last_end)        # 直前のセリフと重ねない
        off = max(off, 0.0)
        last_end = off + tts_dur
        if abs(off - scene_start) > 0.05:
            print(f"  S{i + 1}: 位置調整 {scene_start:.1f}s → {off:.1f}s（尺{tts_dur:.1f}s）")
        else:
            print(f"  S{i + 1} @ {off:.0f}s [{voice}]（尺{tts_dur:.1f}s）")
        results.append((i, wav, voice, off))
    return results
