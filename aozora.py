"""青空文庫の HTML から本文プレーンテキストを取り出す（標準ライブラリのみ）。

- Shift_JIS(cp932) で読む
- 本文は <div class="main_text"> 〜 書誌情報の手前まで
- ルビ（<rt>/<rp>）は読みなので除去、ルビ親文字は残す
- <br /> は改行に、画像（外字）は除去
"""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path


def load_text(path: str | Path) -> str:
    raw = Path(path).read_bytes().decode("cp932", errors="replace")

    # 本文ブロックを切り出す
    start = raw.find('<div class="main_text">')
    if start == -1:
        body = raw
    else:
        end = raw.find('<div class="bibliographical_information">', start)
        body = raw[start:end if end != -1 else None]

    # ルビの読み・囲み括弧を除去（親文字 <rb> の中身は残る）
    body = re.sub(r"<rp>.*?</rp>", "", body, flags=re.S)
    body = re.sub(r"<rt>.*?</rt>", "", body, flags=re.S)

    # 改行系タグを改行に
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(r"</(p|div|h\d)>", "\n", body, flags=re.I)

    # 残りのタグ（画像=外字含む）を除去
    body = re.sub(r"<[^>]+>", "", body)

    # HTML エンティティを戻す
    body = html_lib.unescape(body)

    # 空白整理
    body = re.sub(r"[ \t　]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


if __name__ == "__main__":
    import sys

    text = load_text(sys.argv[1])
    print(f"文字数: {len(text)}")
    print(text[:500])
