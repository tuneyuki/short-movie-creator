"""動画生成パイプラインの設定。ここを変えれば挙動が変わる。"""

import os

# --- Vertex AI ---
# GCP プロジェクトIDは環境変数 GCP_PROJECT_ID から読む（リポジトリに実値を残さない）。
#   PowerShell:  $env:GCP_PROJECT_ID = "your-project-id"
#   bash:        export GCP_PROJECT_ID=your-project-id
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "your-gcp-project-id")
LOCATION = "us-central1"  # Veo が使えるリージョン

# Veo モデル。
#   veo-3.1-generate-001      : GA・高品質。リファレンス画像(ASSET 最大3枚)・4/6/8秒可変尺・音声対応
#   veo-3.1-fast-generate-001 : 速い・安い版（同機能）
#   veo-3.1-lite-generate-001 : 軽量・リファレンス画像 非対応
#   veo-3.0-fast-generate-001 : Veo3.0 Fast。リファレンス画像 非対応
MODEL = "veo-3.1-generate-001"

# --- 動画の仕様 ---
ASPECT_RATIO = "9:16"      # "16:9"（横）or "9:16"（縦）
RESOLUTION = "720p"        # "720p" or "1080p"
PERSON_GENERATION = "allow_adult"  # "dont_allow" or "allow_adult"

# --- 作風（雰囲気・時代・舞台） ---
# 既定は空。空のときは Gemini が小説本文から時代背景・舞台・雰囲気を読み取って
# 自動で作風を決め、全シーンに反映する。
# 文字列を入れると自動導出を上書きして手動指定できる。
STYLE_OVERRIDE = ""

# Veo プロンプトの文字数上限（保守的な安全値）。
# 公式の明確な数値は非公開だが概ね 1024 トークン程度とされるため、
# 余裕を見てこの範囲で情報密度を最大化する。
MAX_PROMPT_CHARS = 1800

# Veo 3.1 は 4 / 6 / 8 秒の可変尺に対応。シーンの長さは Gemini が内容に応じて
# シーンごとに割り当てる（掛け合いは8秒、一瞬の見せ場は4秒など）。
SCENE_SECONDS = 8          # 既定/フォールバックの尺（Gemini 未指定時）
ALLOWED_DURATIONS = (4, 6, 8)  # Veo 3.1 が受け付ける尺
NUM_SCENES = 5             # シーン（クリップ）数
TARGET_TOTAL_SECONDS = 32  # 全シーンの尺合計のtarget（Gemini が 4/6/8 を配分して近づける）
WITH_AUDIO = True          # Veo 3 系は音声付き。Veo 2 を使う場合は False

# 各クリップを先頭この秒数にトリムして繋ぐ機能（None=トリムしない）。
# 可変尺を Veo にネイティブ生成させるので通常は None。
CLIP_SECONDS = None

# 連結後に全体を指定秒数へトリムしたい場合のみ秒数を入れる（None なら成り行き）
TRIM_SECONDS = None

# --- 題材 → セリフ抽出（Gemini） ---
NOVEL_PATH = "scripts/57405_60036.html"  # 題材（.html=青空文庫 / .txt=プレーン）
GEMINI_MODEL = "gemini-3.1-pro-preview"  # 抽出用（高品質）。軽くするなら "gemini-2.5-flash"
GEMINI_LOCATION = "global"  # Gemini 3 系は global エンドポイント
DIALOGUE_LANG = "ja"          # "ja"=日本語セリフ / "en"=英語セリフ / "none"=セリフなし字幕
# 予告編としてネタバレを避けるか。物語そのものを動画化する場合は False（結末まで描く）。
AVOID_SPOILERS = True

# --- 登場人物の参照画像（Nano Banana Pro → Veo リファレンス） ---
USE_CHARACTER_REFS = True     # 主要人物の画像(Nano Banana Pro)を生成し Veo にリファレンスとして渡す。
                              # veo-3.1-generate-001 はリファレンス画像(ASSET 最大3枚)対応。
MAX_CHARACTERS = 3            # 抽出する主要登場キャラの上限
# 画像ref非対応モデルでの代替として容姿をプロンプトに埋め込む機能。
# 画像生成用の詳細説明は危険語を含みやすく安全フィルタを誘発するため既定 False。
# （人物の見た目は各 visual 内に既に含まれる）
EMBED_CHARACTER_APPEARANCE = False
IMAGE_MODEL = "gemini-3.1-flash-image"  # 人物画像生成（Gemini 3.1 Flash Image）
# Gemini 3 系は Vertex では global エンドポイント提供（Veo の us-central1 とは別）
IMAGE_LOCATION = "global"

# --- BGM（Lyria）---
# Veo の音声は使わず（サイレント扱い）、Lyria で作ったBGMを被せる。
LYRIA_MODEL = "lyria-002"     # 1回で約32.8秒の器楽WAVを生成
LYRIA_LOCATION = "global"     # 本プロジェクトでは global でアクセス可（us-central1 は不可）
BGM_PROMPT_OVERRIDE = ""      # 空なら作風(style)から自動でBGMプロンプトを導出
BGM_VOLUME = 0.35             # BGMの音量（0〜1。低めにして bed にする）

# --- TTS ダブ（Gemini TTS）---
# 各シーンのセリフをキャラ別ボイスで音声化し、シーン開始位置に差し込む。
TTS_MODEL = "gemini-2.5-flash-preview-tts"  # 品質重視なら "gemini-2.5-pro-preview-tts"
TTS_LOCATION = "global"
TTS_VOLUME = 1.6              # セリフの音量（BGMより前に出す）
DUB_BGM_VOLUME = 0.22        # ダブ併用時のBGM音量（セリフを邪魔しないよう更に下げる）
# 声の開始を、映像内でキャラが喋り出すタイミングに合わせる仕組み。
# 優先順位: per-scene 手動指定 > 自動検出(AUTO) > 全体デフォルト(TTS_LEAD_IN)。
TTS_LEAD_IN = 1.2                  # 全体デフォルト（自動検出オフ/失敗時）
TTS_LEAD_IN_AUTO = True            # 各シーン映像をGeminiで解析し口の動き出し秒を自動採用
VISION_MODEL = "gemini-2.5-flash"  # 動画理解に使うモデル
VISION_LOCATION = "us-central1"
# シーン番号(1始まり)→秒 で手動上書き（最優先）。例: {2: 1.8, 3: 0.6}
TTS_LEAD_IN_PER_SCENE: dict[int, float] = {}
# キャラ名 → 使う音声を手動固定（空なら自動割当）。tts.py の VOICE_HINTS に候補一覧。
VOICE_OVERRIDES = {
    "Kurotokage": "Gacrux",      # 成熟・落ち着いた女性（妖艶寄り）
    "Amemiya Junichi": "Algenib",  # ザラついた（gravelly）男性
    "Akechi Kogoro": "Charon",   # 深く知的な男性
}

# --- 出力 ---
OUTPUT_DIR = "output"   # 既存の char_*.png / storyboard.json（暗黒街の女王）を流用する
