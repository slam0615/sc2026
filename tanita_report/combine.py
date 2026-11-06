"""合併各職場的「<職場>_跨職場摘要.csv」為一份跨職場比較表。

用法：
    python combine.py <資料夾或 csv 檔> [...] [-o 跨職場比較.xlsx]
"""
import sys
from pathlib import Path

import pandas as pd


def main():
    argv = sys.argv[1:]
    out = Path("跨職場比較.xlsx")
    if "-o" in argv:
        i = argv.index("-o")
        out = Path(argv[i + 1])
        del argv[i:i + 2]
    files = []
    for a in argv or ["output"]:
        p = Path(a)
        files += sorted(p.glob("*_跨職場摘要.csv")) if p.is_dir() else [p]
    if not files:
        raise SystemExit("找不到 *_跨職場摘要.csv")
    df = pd.concat([pd.read_csv(f, encoding="utf-8-sig") for f in files], ignore_index=True)
    # 各職場的量測日期欄名相同（前測日期、後測日期…），直接合併
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="跨職場比較", index=False)
        ws = xw.sheets["跨職場比較"]
        ws.freeze_panes = "B2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = max(10, min(28, len(str(col[0].value)) * 1.6))
    print(f"{len(df)} 家 → {out}")


if __name__ == "__main__":
    main()
