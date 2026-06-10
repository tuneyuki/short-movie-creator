"""小説本文から「作風＋主要登場人物＋特徴的なセリフ＋シーン描写」を抽出する。

Gemini（Vertex AI）が小説本文を読み、
  1) 作品の時代背景・舞台・雰囲気を作風(style)として導出
  2) 主要登場人物（最大 MAX_CHARACTERS 名）の容姿を導出
  3) 作風と人物に沿った絵コンテ(scenes)
を構造化出力(JSON)する。映像描写は英語（Veo の追従性が高い）、セリフは原文の言語のまま。
"""

from __future__ import annotations

import json
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel

import config


class Character(BaseModel):
    """主要登場人物。description は人物画像生成(Nano Banana Pro)のプロンプト素材。"""

    name: str          # 人物名（原文の呼称）
    description: str   # 英語の容姿説明: 年齢・性別・髪型・服装・体格・雰囲気など詳細に


class Scene(BaseModel):
    """1シーンの構成要素。"""

    visual: str            # 映像描写（英語）: 構図・被写体・ライティング・カメラ動き
    speaker: str           # 話者描写（英語・短く）例: "a young woman murmurs softly"
    dialogue: str          # セリフ（原文の言語のまま・短く）。セリフなしなら空文字
    characters: list[str]  # このシーンに登場する人物名（最大3。Character.name と一致）
    duration_seconds: int = config.SCENE_SECONDS  # 尺。Veo 3.1 は 4/6/8 から選ぶ


class Storyboard(BaseModel):
    """小説から導出した絵コンテ全体。"""

    style: str                  # 作風（英語）: 時代・舞台・人物・雰囲気・映像ルックを集約
    characters: list[Character] # 主要登場人物（最大 MAX_CHARACTERS 名）
    scenes: list[Scene]


_LANG_LABEL = {"ja": "Japanese", "en": "English", "none": ""}


def _duration_rule() -> str:
    """シーン尺の指示文。リファレンス画像利用時は『人物シーン=8秒』制約を課す。"""
    durations = "/".join(str(d) for d in config.ALLOWED_DURATIONS)
    target = config.TARGET_TOTAL_SECONDS
    if config.USE_CHARACTER_REFS:
        # reference_to_video は8秒のみ。人物が映るシーンは8秒、インサートのみ短尺。
        return (
            f"- 各シーンに duration_seconds を設定する。【重要】登場人物(characters)が映るシーンは"
            "必ず 8 秒（人物画像で見た目を固定するため）。人物が映らない物・風景・一瞬のインサート"
            f"のみ 4 または 6 秒にする。全シーンの尺合計が約 {target} 秒になるよう配分する。"
        )
    return (
        f"- 各シーンに duration_seconds を {durations} 秒から内容に応じて設定する"
        f"（掛け合い=8/見せ場の一瞬=4/中間=6）。全シーンの尺合計が約 {target} 秒になるよう配分する。"
    )


def _client() -> genai.Client:
    # Gemini は GEMINI_LOCATION（Gemini 3 系は global）
    return genai.Client(
        vertexai=True,
        project=config.PROJECT_ID,
        location=config.GEMINI_LOCATION,
    )


def _system_instruction() -> str:
    n = config.NUM_SCENES
    m = config.MAX_CHARACTERS
    lang = _LANG_LABEL.get(config.DIALOGUE_LANG, "Japanese")
    # style + visual + speaker でこの予算に収める（セリフは別途・必ず保持）
    visual_budget = max(400, config.MAX_PROMPT_CHARS - 600)

    if config.AVOID_SPOILERS:
        role = "あなたは映画予告編のディレクターです。"
        scenes_rule = (
            f"- scenes はちょうど {n} 個。予告編なので【ネタバレ厳禁】: 結末・真相・犯人・"
            "人物の生死などオチに触れず、序盤〜中盤の引き（緊張・謎・行動など）で惹きつける。"
        )
    else:
        role = "あなたは短編映像のディレクターです。"
        scenes_rule = (
            f"- scenes はちょうど {n} 個で、物語を時系列に【起承転結】で見せる"
            "（導入→展開→山場→結末）。題材の有名な見せ場・名セリフは必ず入れる。"
        )

    if config.STYLE_OVERRIDE.strip():
        style_rule = (
            f"- style は次の指定をそのまま使う（英語に整える）: 「{config.STYLE_OVERRIDE}」。"
        )
    else:
        style_rule = (
            "- style は、小説本文から読み取れる【時代背景・舞台（国/土地）・登場人物の風貌や"
            "服装・全体の雰囲気・ジャンル】を凝縮した英語の作風指示にする（最大400字）。\n"
            "  必ず含める: 時代と土地（例: 1930s Showa-era Japan）、人物の人種・服装、"
            "建築や小物の時代考証、ムード（例: dark film-noir）、映像ルック"
            "（例: vintage cinema, desaturated, film grain, chiaroscuro lighting）。\n"
            "  ※原作の世界観に忠実に。勝手に西洋風・現代風にしない。"
        )

    durations = "/".join(str(d) for d in config.ALLOWED_DURATIONS)
    return f"""{role}
渡された題材を読み込み、合計 {n} シーン（各 {durations} 秒）の短い動画の絵コンテを作ります。
本文からできる限り多くの情報（時代・舞台・人物・小物・天候・色・音）を読み取り、映像に反映してください。

まず作品世界を読み取り、全シーン共通の作風(style)と主要登場キャラ(characters)を定義し、その上で絵コンテ(scenes)を作ります。

要件:
{style_rule}
- characters は物語の中心となる主要キャラ（人物や動物）を最大 {m} 体。各 description は英語で、
  種別・年齢・体格・色・服装・表情・雰囲気を具体的かつ詳細に書く（画像生成に使うため情報量を最大化）。
{scenes_rule}
{_duration_rule()}
- 各 visual は必ず英語。style の時代・舞台・雰囲気に厳密に合わせ、構図・被写体・ライティング・
  レンズ/カメラの動き・色・質感・背景の小物まで、情報を詰め込めるだけ詰める（最大{visual_budget}字）。
- scene.characters には、そのシーンに映るキャラ名を characters の name から最大3つ選ぶ（いなければ空配列）。
- speaker は英語で短く話者を描写する（例: "a young woman murmurs softly", "the detective mutters"）。
- visual は安全性ガイドラインに配慮し、流血・死体・暴力・武器・苦痛の生々しい描写を避け、
  穏当・コミカル・象徴的な言い回しに置き換える。
- dialogue には、題材中の最も印象的で短いセリフを {lang} で入れる
  （そのシーンの尺で発話しきれる長さに短縮。目安: 8秒で約30字、6秒で約22字、4秒で約15字）。""" + (
        "\n- ただし DIALOGUE_LANG=none のため dialogue は必ず空文字にする。"
        if config.DIALOGUE_LANG == "none"
        else ""
    )


def extract_storyboard(novel_text: str) -> Storyboard:
    """小説本文 → 作風＋人物＋シーン。"""
    client = _client()  # GC で httpx が閉じないよう参照を保持する
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=novel_text,
        config=types.GenerateContentConfig(
            system_instruction=_system_instruction(),
            response_mime_type="application/json",
            response_schema=Storyboard,
            temperature=0.7,
        ),
    )
    sb: Storyboard = resp.parsed
    if not sb or not sb.scenes:
        raise RuntimeError("Gemini が絵コンテを返しませんでした")
    sb.scenes = sb.scenes[: config.NUM_SCENES]
    sb.characters = sb.characters[: config.MAX_CHARACTERS]
    _normalize_durations(sb.scenes)
    return sb


def _normalize_durations(scenes: list[Scene]) -> None:
    """各シーンの尺を ALLOWED_DURATIONS に丸める（近い値へ）。"""
    allowed = config.ALLOWED_DURATIONS
    for s in scenes:
        if s.duration_seconds not in allowed:
            s.duration_seconds = min(allowed, key=lambda d: abs(d - s.duration_seconds))


def regenerate_scenes(novel_path: str | Path | None = None) -> Storyboard:
    """既存 storyboard.json の作風・登場人物を保ったまま、絵コンテ(scenes)だけ作り直す。

    人物画像(char_NN.png)を流用するため characters は変えない。
    """
    sb = load_saved_storyboard()  # 既存の style + characters を流用
    path = Path(novel_path or config.NOVEL_PATH)
    if path.suffix.lower() in (".html", ".htm"):
        from aozora import load_text

        novel_text = load_text(path)
    else:
        novel_text = path.read_text(encoding="utf-8")

    n = config.NUM_SCENES
    lang = _LANG_LABEL.get(config.DIALOGUE_LANG, "Japanese")
    chars = "、".join(c.name for c in sb.characters)
    spoiler = (
        "予告編なので【ネタバレ厳禁】結末・真相・人物の生死に触れず、序盤〜中盤の引きで惹きつける。"
        if config.AVOID_SPOILERS
        else "物語を起承転結で見せる。"
    )
    instr = f"""あなたは映像ディレクター。次の作風・登場人物に沿って、題材から {n} シーンの絵コンテを作る。
作風: {sb.style}
登場人物: {chars}
- {spoiler}
- 各 visual は英語で具体的に（構図・光・カメラ・色・小物）。style に厳密に合わせる。
{_duration_rule()}
- scene.characters は登場人物名から最大3つ。speaker は英語で短く。
- dialogue は題材中の短い印象的なセリフ（{lang}・尺で発話しきれる長さ）。
- 【安全性 最重要】visual と dialogue の両方で、Veo の語句フィルタに弾かれる表現を徹底回避する。
  避ける: 流血・死・暴力・武器・喫煙、飲酒/酒/グラスでの乾杯、誘拐/拉致/かどわかし、
  犯罪/賊/兇賊などの語、地下/暗黒街(underworld/underground)、人物をじっと凝視する構図。
  セリフは題材の雰囲気を保ちつつ、これらの語を含まない安全な言い回しを選ぶ（無ければ言い換える）。
  視覚は華やか・優雅・ミステリアスな雰囲気で表現する。"""
    client = _client()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=novel_text,
        config=types.GenerateContentConfig(
            system_instruction=instr,
            response_mime_type="application/json",
            response_schema=list[Scene],
            temperature=0.8,
        ),
    )
    scenes: list[Scene] = resp.parsed
    if not scenes:
        raise RuntimeError("絵コンテを再生成できませんでした")
    sb.scenes = scenes[:n]
    _normalize_durations(sb.scenes)

    out_dir = Path(config.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "storyboard.json").write_text(
        json.dumps(sb.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _report(sb)
    return sb


def extract_replacement_scene(novel_text: str, sb: Storyboard, guidance: str) -> Scene:
    """既存の作風・人物に沿って、条件に合う差し替えシーンを1つ抽出する（ネタバレ回避）。"""
    lang = _LANG_LABEL.get(config.DIALOGUE_LANG, "Japanese")
    chars = "、".join(c.name for c in sb.characters)
    instr = f"""あなたは映画予告編のディレクター。次の作風・登場人物に沿って、
小説本文から指定条件に合うシーンを1つだけ選び、{config.SCENE_SECONDS}秒のクリップ用に構成する。
作風: {sb.style}
登場人物: {chars}
条件: {guidance}
- 【ネタバレ厳禁】結末・真相・犯人・人物の生死などオチに触れない。序盤〜中盤の引きを選ぶ。
- visual は英語で具体的に（構図・光・カメラ・小物まで）。style の時代・舞台に厳密に合わせる。
- 安全性に配慮し、流血・死・暴力・武器・苦痛の生々しい描写を避ける。
- speaker は英語で短く。dialogue は小説中の短い印象的なセリフ（{lang}・目安15文字以内）。
- characters は登場人物名から最大3つ。"""
    client = _client()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=novel_text,
        config=types.GenerateContentConfig(
            system_instruction=instr,
            response_mime_type="application/json",
            response_schema=Scene,
            temperature=0.7,
        ),
    )
    scene: Scene = resp.parsed
    if not scene:
        raise RuntimeError("差し替えシーンを抽出できませんでした")
    return scene


def build_prompt(
    scene: Scene, style: str, scene_chars: list[Character] | None = None
) -> str:
    """Scene + 作風(+登場人物の容姿) → Veo へ渡す1本分のプロンプト文字列。

    画像リファレンスが使えない場合の代替として、登場人物の容姿をテキストで埋め込む。
    予算超過時は容姿テキストを落として、映像とセリフを優先する。
    """
    lang = _LANG_LABEL.get(config.DIALOGUE_LANG, "Japanese")

    if config.DIALOGUE_LANG == "none" or not scene.dialogue.strip():
        dialogue_part = ""
    else:
        # セリフは引用符で囲むと Veo 3 が発話する。言語を明示して精度を上げる。
        dialogue_part = f" {scene.speaker} in {lang}: 「{scene.dialogue}」."

    # 映像とセリフは死守。残り予算に収まる範囲で人物の容姿テキストを埋め込む。
    base = f"{style} {scene.visual}{dialogue_part}"
    appearance = ""
    if scene_chars and config.EMBED_CHARACTER_APPEARANCE:
        app_budget = config.MAX_PROMPT_CHARS - len(base)
        if app_budget > 100:
            full = " Character appearance — " + " ".join(
                f"{c.name}: {c.description}" for c in scene_chars
            )
            appearance = full[:app_budget].rstrip()  # 予算ぴったりにクランプ

    return f"{style} {scene.visual}{appearance}{dialogue_part}"


def soften_prompt(prompt: str) -> str:
    """セーフティでブロックされたプロンプトを穏当に書き換える。"""
    client = _client()  # GC で httpx が閉じないよう参照を保持する
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=(
                "次の動画生成プロンプトを、利用規約に触れうる要素を全て取り除いて書き換えてください。"
                "対象: 暴力・死・流血・武器・苦痛、喫煙/タバコ/煙、飲酒の強調、薬物、"
                "性的・扇情的表現、危険/違法行為、恐怖や緊張の生々しい描写。"
                "これらは穏やか・上品・一般向けの表現に置き換える。"
                "「」で囲まれたセリフ部分はそのまま保持し、映像の感情・雰囲気は極力維持します。"
                "出力は書き換えたプロンプト文字列のみ。"
            ),
            temperature=0.4,
        ),
    )
    return (resp.text or prompt).strip()


def load_saved_storyboard() -> Storyboard:
    """保存済み output/storyboard.json を読み込む（再現用）。"""
    data = json.loads(
        (Path(config.OUTPUT_DIR) / "storyboard.json").read_text(encoding="utf-8")
    )
    return Storyboard(**data)


def _report(sb: Storyboard) -> None:
    print("=== 作風 (style) ===")
    print(f"  {sb.style}")
    print(f"=== 登場人物 ({len(sb.characters)}名) ===")
    for c in sb.characters:
        print(f"  - {c.name}: {c.description[:60]}...")
    total = sum(s.duration_seconds for s in sb.scenes)
    print(f"=== 絵コンテ（{len(sb.scenes)}シーン / 合計 {total}秒）===")
    for i, s in enumerate(sb.scenes):
        print(
            f"[シーン{i + 1}] {s.duration_seconds}秒 / 登場: {s.characters} / "
            f"セリフ: 「{s.dialogue}」"
        )


def extract_and_save(novel_path: str | Path | None = None) -> Storyboard:
    """小説ファイル → Storyboard。output/storyboard.json に保存する。"""
    path = Path(novel_path or config.NOVEL_PATH)
    if path.suffix.lower() in (".html", ".htm"):
        from aozora import load_text

        novel_text = load_text(path)
    else:
        novel_text = path.read_text(encoding="utf-8")

    sb = extract_storyboard(novel_text)

    out_dir = Path(config.OUTPUT_DIR)
    out_dir.mkdir(exist_ok=True)
    (out_dir / "storyboard.json").write_text(
        json.dumps(sb.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _report(sb)
    return sb
