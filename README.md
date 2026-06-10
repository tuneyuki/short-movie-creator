# short-movie-creator

**小説や物語のテキストから、縦型ショート動画を自動生成するツール。**

Google Cloud の生成AI（Gemini / Veo / Nano Banana / Lyria / Gemini TTS）を Vertex AI 経由で組み合わせ、
題材テキストを渡すだけで「作風の決定 → 絵コンテ → 人物画像 → 映像生成 → 連結 →（任意で）BGM・セリフ」までを行う。

試作した動画の作り方は **2パターン**ある。

---

## パターン1: Veo だけで作る（映像＋Veo内蔵音声）

Veo が映像と音声（セリフ含む）をまとめて生成する、最もシンプルな構成。

```
題材テキスト（小説HTML / プレーンテキスト）
   │
   ├─ ① Gemini が本文から「作風・登場人物・絵コンテ」を作成        … extract.py
   ├─ ② Nano Banana が登場人物のイメージ画像を生成                … characters.py
   ├─ ③ 絵コンテを元に各シーンを Veo で 8秒（または4/6秒）生成     … pipeline.py
   │      （②の人物画像をリファレンスとして渡し、見た目を一貫させる）
   └─ ④ ffmpeg で全シーンを連結                                  … pipeline.py
   ↓
OUTPUT_DIR/final.mp4   （音声は Veo が生成したもの）
```

### 走らせ方

```powershell
# 小説/題材（config.NOVEL_PATH）から一気通貫で生成
uv run --native-tls python main.py

# 既存の絵コンテ(storyboard.json)・人物画像・クリップを流用して続きから
uv run --native-tls python main.py --resume

# 気に入らないシーンだけ選び直してから再生成
uv run --native-tls python reextract.py        # reextract.py 内の SCENE_GUIDANCE を編集
uv run --native-tls python main.py --resume
```

`main.py` が ①→②→③→④ を順に実行する。出力は `OUTPUT_DIR/final.mp4`、
絵コンテは `OUTPUT_DIR/storyboard.json`、人物画像は `OUTPUT_DIR/char_NN.png`、各クリップは `scene_NN.mp4`。

---

## パターン2: 映像=Veo / BGM=Lyria / 音声=TTS

Veo の音声は使わず（サイレント扱い）、**BGMを Lyria、セリフを Gemini TTS** で別々に作って被せる。
Veo 内蔵音声より制御しやすく、日本語セリフの品質・タイミングも安定する。

```
① まずパターン1で映像を作る（main.py）。Veoの音声は後で捨てるので無視してよい
   ↓ OUTPUT_DIR/final.mp4
② 音声を組み立てて被せる                                          … dub.py
   ├─ Lyria が作風に合った器楽BGMを生成（約32.8秒WAV）            … music.py
   ├─ Gemini TTS が各シーンのセリフをキャラ別ボイスで音声化        … tts.py
   │     ・各シーン映像を Gemini で解析し「口が動き出す秒」を自動検出してそこに配置
   └─ ffmpeg で「BGM(bed) + 各セリフ(所定位置)」を合成し映像に mux  … pipeline.py (add_dub)
   ↓
OUTPUT_DIR/final_dub.mp4   （Veo音声を捨て、Lyria BGM + TTSセリフ）
```

### 走らせ方

```powershell
# 1) まず映像を作る（パターン1と同じ）
uv run --native-tls python main.py

# 2) BGM + セリフ(TTS) を被せる  →  final_dub.mp4
uv run --native-tls python dub.py

# BGMだけ被せたい場合（TTSなし）  →  final_bgm.mp4
uv run --native-tls python add_bgm.py
```

`dub.py` は BGM(`bgm.wav` があれば流用) → 各シーンのTTS生成 → 合成、の順に実行する。
セリフのタイミングは `TTS_LEAD_IN_AUTO=True` のとき映像解析で自動。ズレる場合は
`config.TTS_LEAD_IN_PER_SCENE`（シーン番号→秒, 1始まり）で手動上書きできる。

---

## セットアップ

```powershell
gcloud auth application-default login   # ADC 認証（初回のみ）
```

- 依存は uv 管理（インストール済み）。ffmpeg もインストール不要（`imageio-ffmpeg` 同梱）。
- 社内プロキシ(Zscaler)対策で [pyproject.toml](pyproject.toml) に `native-tls = true` 設定済み。`uv run` には `--native-tls` を付ける。
- 設定はすべて [config.py](config.py) に集約（題材・モデル・尺・声・音量など）。

### 使っている主なモデル / エンドポイント

| 用途 | モデル | ロケーション |
|---|---|---|
| 映像生成 | Veo `veo-3.1-generate-001`（4/6/8秒・人物リファレンス画像対応） | us-central1 |
| 作風・絵コンテ抽出 | Gemini `gemini-3.1-pro-preview` | global |
| 人物画像 | Nano Banana `gemini-3.1-flash-image` | global |
| BGM | Lyria `lyria-002`（約32.8秒WAV） | global |
| セリフ音声 | Gemini TTS `gemini-2.5-flash-preview-tts` | global |
| 口の動き検出 | Gemini `gemini-2.5-flash`（動画解析） | us-central1 |

> 補足: プレビュー系モデルはプロジェクトの allowlist 次第で 404 になることがある。
> Gemini 3 系・Lyria・画像系は `global` エンドポイント、Veo は地域(us-central1)エンドポイント、と別なので注意。

---

## 各 Python スクリプトの役割

| ファイル | 役割 |
|---|---|
| [config.py](config.py) | **全設定**。題材・モデル・尺(NUM_SCENES/可変尺)・作風・人物refの有無・BGM/TTSの音量や声など。まずここを見る |
| [main.py](main.py) | **パターン1のエントリ**。抽出→人物画像→Veo生成→連結 を順に実行（`--resume` / `--manual`） |
| [extract.py](extract.py) | Gemini で 題材→**作風・登場人物・絵コンテ(JSON)** を抽出。Veoプロンプト構築、安全フィルタ用の穏当化、特定シーンの再抽出、storyboard.json の保存/読込 |
| [aozora.py](aozora.py) | 青空文庫 HTML → 本文プレーンテキスト（ルビ・外字を除去） |
| [characters.py](characters.py) | **Nano Banana** で登場人物のイメージ画像を生成（Veo のリファレンス画像に使う） |
| [pipeline.py](pipeline.py) | **Veo 生成**（失敗時の自動リトライ込み）＋ **ffmpeg 連結**。さらに `add_bgm`（BGM被せ）/ `add_dub`（BGM＋TTS合成）も持つ |
| [reextract.py](reextract.py) | **特定シーンだけ**を条件指定で選び直して storyboard.json を差し替えるツール |
| [music.py](music.py) | **Lyria** で作風に合う器楽BGMを生成（`lyria-002` の predict を直叩き） |
| [tts.py](tts.py) | **Gemini TTS** でセリフ音声化。キャラ→声の自動/手動割当、**映像解析による喋り出し秒の自動検出**、終端に収める配置調整 |
| [dub.py](dub.py) | **パターン2のエントリ**。BGM(Lyria)＋セリフ(TTS)を合成して `final_dub.mp4` を作る |
| [add_bgm.py](add_bgm.py) | BGM だけ被せるエントリ（`final_bgm.mp4`） |
| [storyboard.py](storyboard.py) | 手書きの絵コンテ（`main.py --manual` で使用） |

中間生成物・完成品はすべて `OUTPUT_DIR`（題材ごとに分けると過去作を保全できる）に出力される。

---

## 新しい題材で作る手順

1. 題材テキストを置く（`stories/xxx.txt`、青空文庫なら `.html` のまま可）
2. [config.py](config.py) で `NOVEL_PATH` と `OUTPUT_DIR`（題材ごとに分ける）を設定
3. 物語そのものを描くなら `AVOID_SPOILERS=False`、予告編なら `True`
4. パターン1: `uv run --native-tls python main.py`
5. （任意）パターン2: 続けて `uv run --native-tls python dub.py`

## 既知の制約・ハマりどころ

- **Veo の安全フィルタが厳しい**: 死・暴力・喫煙・飲酒・賭け・「人物を凝視する構図」等で生成がブロックされやすい。
  抽出時に回避指示を入れ、ブロック時は穏当化リトライするが、執拗な場合はシーンを選び直す（[reextract.py](reextract.py)）。
- **人物リファレンス画像は対応モデル限定**: `veo-3.1-generate-001` 等が必要。非対応モデルだと自動で画像を外してテキストで代替する。
- **Veo は1クリップ最大8秒**: 長い動画は複数クリップを連結。可変尺(4/6/8)は Gemini が内容に応じて配分する。
- **TTS の口合わせは ±0.5秒程度**: 自動検出はおおむね合うが、ズレる場合は per-scene で微調整する。
- **生成は課金・非同期**: クリップ・音声を増やすほど時間とコストが増える。
