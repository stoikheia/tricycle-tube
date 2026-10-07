<p align="center"><img src="logo/tricycle-tube.svg" width="360" alt="tricycle-tube"></p>

# tricycle-tube

NTSC のファミコンの映像がブラウン管でどう見えたか — コンポジット信号による色のにじみ、回り続ける偽色、走査線、蛍光体の残光 — を再現する描画仕様です。**AI エージェント（あるいは人）が仕様だけから作り直せる**ように書いてあります。新規のエミュレータでも、既存エミュレータの改造でも、シェーダでも構いません。

**tricycle-tube** は、この技術要素の集合に付けた名前です。*tri* + *cycle* は、色の位相が 3 つの状態を巡ること、*tube* は再現対象のブラウン管を指します。ロゴが「ブラウン管を乗せた三輪車」なのはそのためです。

- **[spec/SPEC.md](spec/SPEC.md)** — 仕様（英語が正）。[日本語版](spec/SPEC.ja.md)
- **[conformance/vectors.json](conformance/vectors.json)** — 参照実装が生成した期待出力と許容差
- **[reference/crt_reference.py](reference/crt_reference.py)** — 純 Python の参照実装（依存なし）
- **[prompts/REPRODUCE.ja.md](prompts/REPRODUCE.ja.md)** — 仕様とベクタと一緒にエージェントへ渡すプロンプト

盲検再現試験を 2 回通しています。試作を見たことのないエージェントが仕様だけから全段を実装し、最初の実行で適合項目 38 件すべてに一致しました。仕様から別チームが書いた GPU（WGSL）実装も許容差内で一致しています。

## 何をするか

```
パレット番号（256×240）＋ フレーム位相
  → 信号段     : 12 位相のコンポジット符号化 → ノッチで輝度、帯域制限した色差、YIQ→RGB（2048×240）
  → ブラウン管段: 縦 12 倍、ビームスポット、ガウス形の走査線、蛍光体ストライプ、ブルーム（2048×2880）
  → 残光       : 直近 3 フレームを 6:3:1 で合成。同位相のフレームと比べて静止している画素だけ
  → 縮小       : 面積平均で窓の大きさへ
```

見え方は忠実さより意図を優先しています。副搬送波の位相を毎フレーム 120° 進める（3 フレーム周期）ので偽色の色相が回り続け、細かい模様が流れて見える一方、残光が静止部分を落ち着かせます。実機の通常動作は 2 フレーム周期で、仕様は両方と実機追従モードを定義しています。

## サンプル

参照実装で 60fps にレンダリングしたもの（APNG。ブラウザで再生されます）。サンプルの絵はすべて自作で、ゲームの画像は使っていません。

<p align="center"><img src="samples/testcard_cycle3_60fps.png" width="512" alt="テストカード・3 フレーム周期・60fps"></p>

`samples/` には比較用の 2 フレーム周期（実機追従）もあります。30fps の GIF は 1 フレームおきの提示になり、位相の周期と干渉します。3 フレーム周期は回り続けますが速さが半分になり（ちらつきの間隔が 2 倍）、2 フレーム周期は 1 つの位相で止まってちらつきが消えます。見え方は 60fps のファイルで判断してください。

## エージェントで再現する

[spec/SPEC.md](spec/SPEC.md)、[conformance/vectors.json](conformance/vectors.json)、[prompts/REPRODUCE.ja.md](prompts/REPRODUCE.ja.md) のプロンプトをエージェントに渡します。ベクタが完成の判定になります。`python3 conformance/gen_vectors.py out.json` で参照実装からベクタを作り直せます。

## 何が新しくて、何が新しくないか

個々の技術はすべて公開済みの先行技術です。NES の 12 位相カラーのコンポジット符号化・復号（blargg 氏の nes_ntsc、Bisqwit 氏の記事、NESdev Wiki、RetroArch のシェーダ群）、走査線・マスク・ブルームの CRT シェーダ、残光（phosphor persistence）のシェーダ、動き適応の時間処理（3 次元くし形フィルタの考え方）。このプロジェクトが足したものは控えめです。残光を NES の位相周期に合わせた同位相比較で制御したこと、実機のブラウン管写真と比べて調整したこと、そして何より、別の実装で検証できる適合ベクタ付きの仕様として書いたことです。

## ライセンス

- 仕様と文書（`spec/`、`prompts/`、この README）: [CC BY 4.0](LICENSE-SPEC.md)
- コードとデータ（`reference/`、JSON のベクタを含む `conformance/`、`samples/*.py`、`.githooks/`）: [MIT](LICENSE)
- サンプル画像（`samples/*.png`。自作の絵から `samples/make_samples.py` で生成）: CC BY 4.0
- ロゴ: CC BY 4.0。ワードマークは Inter（SIL Open Font License 1.1）をアウトライン化したもので、フォントファイルは配布していません。

出典は仕様の §11 にあります。信号の電圧は NESdev Wiki に公開された実測値です。nes_ntsc、GTU-famicom、patchy-ntsc、fami-rf などのコードは使っていません。
