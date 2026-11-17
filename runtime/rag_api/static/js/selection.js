// 選択を受けて保持する（話題のボタンを押すたびに選択・解除を切り替える）

// 経路（見出しの配列）を1つの文字列にする（同じ範囲かどうかの比較に使う）
export const pathKey = (path) => path.join(" > ");

// 選択の入れ物
// 使い方: const sel = new Selection(onChange);  sel.toggle(path, value);  sel.values()
// onChange: 選択が変わるたびに呼ばれる（件数表示やボタンの有効・無効の更新に使う）
export class Selection {
  constructor(onChange) {
    this.map = new Map(); // 経路のキー → 選んだもの（話題や見出しの情報）
    this.onChange = onChange || (() => {});
  }

  // 入力: 経路・覚えておく値 / 出力: なし（選ばれていなければ選択、選ばれていれば解除）
  toggle(path, value) {
    const k = pathKey(path);
    if (this.map.has(k)) this.map.delete(k);
    else this.map.set(k, value);
    this.onChange(this);
  }

  has(key) { return this.map.has(key); }
  get size() { return this.map.size; }
  values() { return [...this.map.values()]; }
}

// 入力: 選んだ話題（{path, chunk_count}）のリスト
// 出力: チャンク数の合計（ほかの選択の配下に入っている話題は数えない＝重なりを除く）
export function chunkTotal(topics) {
  return topics
    .filter((t) => !topics.some((o) => o !== t && pathKey(t.path).startsWith(pathKey(o.path) + " > ")))
    .reduce((a, t) => a + t.chunk_count, 0);
}
