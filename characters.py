"""主要登場人物の参照画像を Nano Banana Pro (gemini-3-pro-image-preview) で生成する。

生成した画像は output/char_NN.png に保存し、Veo の ASSET リファレンスとして使う。
"""

from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types

import config
from extract import Character, Storyboard


def _client() -> genai.Client:
    # Nano Banana Pro (Gemini 3 系) は global エンドポイント
    return genai.Client(
        vertexai=True,
        project=config.PROJECT_ID,
        location=config.IMAGE_LOCATION,
    )


def generate_character_image(
    client: genai.Client, char: Character, style: str, out_path: Path
) -> Path:
    """1人分の人物参照画像を生成して保存する。"""
    prompt = (
        f"{style} "
        f"Character reference portrait of {char.name}. {char.description} "
        "Single subject, waist-up, facing camera, neutral expression, "
        "plain neutral background, soft even lighting, clear detailed face, "
        "consistent character design, photorealistic, period-accurate."
    )
    resp = client.models.generate_content(
        model=config.IMAGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="3:4", image_size="1K"),
        ),
    )

    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            out_path.write_bytes(part.inline_data.data)
            return out_path
    raise RuntimeError(f"人物画像が生成されませんでした: {char.name}")


def generate_all(sb: Storyboard) -> dict[str, Path]:
    """全主要人物の画像を生成し、{人物名: 画像パス} を返す（既存はスキップ）。"""
    out_dir = Path(config.OUTPUT_DIR)
    out_dir.mkdir(exist_ok=True)
    client = _client()

    mapping: dict[str, Path] = {}
    for i, c in enumerate(sb.characters):
        path = out_dir / f"char_{i:02d}.png"
        if path.exists():
            print(f"人物画像（既存をスキップ）: {c.name} -> {path}")
        else:
            print(f"人物画像生成: {c.name} -> {path}")
            generate_character_image(client, c, sb.style, path)
        mapping[c.name] = path
    return mapping
