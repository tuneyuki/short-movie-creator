"""特定シーンだけを小説から抽出し直して storyboard.json を差し替える。

作風・登場人物は既存の storyboard.json を流用し、SCENE_GUIDANCE で指定した
条件に合うシーンを Gemini に選び直させる（ネタバレ回避）。
差し替えたシーンの番号の clip(scene_NN.mp4) は削除して再生成を促す。

  uv run python reextract.py
"""

from __future__ import annotations

import json
from pathlib import Path

import config
from aozora import load_text
from extract import extract_replacement_scene, load_saved_storyboard

# {シーン番号(0始まり): そのシーンに採用したい内容の指示}
SCENE_GUIDANCE: dict[int, str] = {
    1: "探偵・明智小五郎（Akechi Kogoro）が【一人で】手がかりの品"
       "（写真・名刺・宝石・書付など小道具）をランプの灯りにかざして調べ、"
       "ハッと推理のひらめきを得る緊迫した中盤のシーン。"
       "人物（特に女性）をじっと見つめる構図は避け、手元の手がかりと明智の表情に焦点を当てる。"
       "結末・真相・犯人には触れない。",
}


def main() -> None:
    sb = load_saved_storyboard()
    novel_text = load_text(config.NOVEL_PATH)

    for idx, guidance in SCENE_GUIDANCE.items():
        print(f"--- シーン{idx + 1} を再抽出中 ---")
        scene = extract_replacement_scene(novel_text, sb, guidance)
        sb.scenes[idx] = scene
        print(f"  登場: {scene.characters} / セリフ: 「{scene.dialogue}」")
        print(f"  visual: {scene.visual[:120]}...")
        # 該当 clip を消して再生成させる
        clip = Path(config.OUTPUT_DIR) / f"scene_{idx:02d}.mp4"
        if clip.exists():
            clip.unlink()
            print(f"  既存クリップ削除: {clip}")

    (Path(config.OUTPUT_DIR) / "storyboard.json").write_text(
        json.dumps(sb.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("storyboard.json を更新しました。")


if __name__ == "__main__":
    main()
