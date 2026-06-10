"""絵コンテ: 各シーンのプロンプト（1シーン=約8秒）。

15秒 = 8秒クリップ × 2本を連結してトリム。
題材が決まったら SCENES の文字列を書き換えるだけでよい。
プロンプトは英語の方が Veo の追従性が高い。
"""

SCENES: list[str] = [
    # シーン1（0-8秒）: プレースホルダ
    (
        "Cinematic establishing shot, slow camera push-in. "
        "Placeholder scene 1: describe the opening here. "
        "Dramatic lighting, film grain, 16:9, high detail."
    ),
    # シーン2（8-15秒）: プレースホルダ
    (
        "Cinematic continuation, dynamic camera move. "
        "Placeholder scene 2: describe the climax here. "
        "Dramatic lighting, film grain, 16:9, high detail."
    ),
]
