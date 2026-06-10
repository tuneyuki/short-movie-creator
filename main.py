"""エントリポイント: 小説 → 登場人物画像つき ハイライト動画（約16秒）。

  uv run main.py            # novel から抽出→人物画像→生成
  uv run main.py --resume   # 保存済み storyboard.json を再利用して生成
  uv run main.py --manual   # storyboard.py の SCENES をそのまま使う

事前準備:
  1) gcloud auth application-default login   # ADC 認証
  2) config.py の PROJECT_ID / モデル / DIALOGUE_LANG / NOVEL_PATH を確認
"""

import sys
from pathlib import Path

import config
from pipeline import run


def main() -> None:
    if "--manual" in sys.argv:
        run()  # storyboard.py の SCENES（人物リファレンスなし）
        return

    from extract import extract_and_save, load_saved_storyboard

    if "--resume" in sys.argv and (Path(config.OUTPUT_DIR) / "storyboard.json").exists():
        sb = load_saved_storyboard()
        print("保存済み storyboard.json を再利用します。")
    else:
        novel = Path(config.NOVEL_PATH)
        if not novel.exists():
            print(f"小説ファイルが見つかりません: {novel}")
            sys.exit(1)
        sb = extract_and_save(novel)

    # 主要人物の参照画像を生成（Nano Banana Pro）
    char_images = {}
    if config.USE_CHARACTER_REFS and sb.characters:
        from characters import generate_all

        char_images = generate_all(sb)

    run(sb, char_images)


if __name__ == "__main__":
    main()
