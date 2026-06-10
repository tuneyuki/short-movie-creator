"""Lyria (lyria-002) で作風に合った器楽BGMを生成する。

Vertex の predict エンドポイントを直接叩く（google-genai に固定尺Lyriaの
便利メソッドが無いため）。1回で約32.8秒・48kHz ステレオ WAV が返る。
"""

from __future__ import annotations

import base64
from pathlib import Path

import google.auth
from google import genai
from google.auth.transport.requests import AuthorizedSession
from google.genai import types

import config


def bgm_prompt_from_style(style: str) -> str:
    """作風 → セリフ無しの器楽BGM用プロンプト（英語）を Gemini で導出。"""
    if config.BGM_PROMPT_OVERRIDE.strip():
        return config.BGM_PROMPT_OVERRIDE.strip()

    client = genai.Client(
        vertexai=True, project=config.PROJECT_ID, location=config.GEMINI_LOCATION
    )
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=f"作風: {style}",
        config=types.GenerateContentConfig(
            system_instruction=(
                "次の作風に合う、セリフ・ボーカル無しの器楽BGMを表す英語プロンプトを1つ作る。"
                "楽器編成・テンポ・ムード・時代感を具体的に書く（1〜2文）。"
                "出力はプロンプト文字列のみ。"
            ),
            temperature=0.6,
        ),
    )
    return (resp.text or "gentle cinematic instrumental, calm mood").strip()


def generate_bgm(prompt: str, out_wav: Path, negative_prompt: str = "vocals, lyrics, singing") -> Path:
    """Lyria でBGMを生成して WAV を保存する。"""
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(creds)

    loc = config.LYRIA_LOCATION
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    url = (
        f"https://{host}/v1/projects/{config.PROJECT_ID}/locations/{loc}"
        f"/publishers/google/models/{config.LYRIA_MODEL}:predict"
    )
    body = {
        "instances": [{"prompt": prompt, "negative_prompt": negative_prompt}],
        "parameters": {"sample_count": 1},
    }
    resp = session.post(url, json=body, timeout=300)
    if resp.status_code != 200:
        raise RuntimeError(f"Lyria 生成エラー {resp.status_code}: {resp.text[:300]}")

    preds = resp.json().get("predictions", [])
    # 応答の音声フィールドは版により bytesBase64Encoded / audioContent のいずれか
    b64 = None
    if preds:
        b64 = preds[0].get("bytesBase64Encoded") or preds[0].get("audioContent")
    if not b64:
        raise RuntimeError(f"Lyria 応答に音声がありません: {str(resp.json())[:300]}")

    out_wav.write_bytes(base64.b64decode(b64))
    return out_wav
