"""產生互動式 HTML 報告（以及 A4 PDF、Excel 驗算檔）。

用法：
    python build_report.py <GMON匯出.xls> [輸出資料夾] [--no-pdf] [--no-excel]
"""
import json
import subprocess
import sys
from pathlib import Path

import analyze

HERE = Path(__file__).parent


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    src = args[0]
    outdir = Path(args[1]) if len(args) > 1 else HERE / "output"
    outdir.mkdir(parents=True, exist_ok=True)
    D, res = analyze.run(src)
    embed = json.loads(json.dumps(res, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    for st in embed["strata"].values():
        if st["suppressed"]:
            st["n"] = None  # 小分層連人數都不寫入網頁
    data = json.dumps(embed, ensure_ascii=False, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    data = data.replace("</", "<\\/")
    name = res["info"]["workplace"] or "報告"
    html = (HERE / "report_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/", data)
    html_path = outdir / f"{name}_身體組成總體報告.html"
    html_path.write_text(html, encoding="utf-8")
    (outdir / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)), encoding="utf-8")
    print("HTML :", html_path)
    if "--no-excel" not in flags:
        import build_excel
        xlsx = build_excel.build(D, res, outdir / f"{name}_驗算.xlsx")
        print("Excel:", xlsx)
    if "--no-pdf" not in flags:
        pdf = outdir / f"{name}_身體組成總體報告_A4.pdf"
        subprocess.run(["node", str(HERE / "render_pdf.mjs"), str(html_path), str(pdf), name], check=True)
        print("PDF  :", pdf)


if __name__ == "__main__":
    main()
