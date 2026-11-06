"""產生互動式 HTML 報告（以及 A4 PDF、Excel 驗算檔）。

用法：
    python build_report.py <GMON匯出.xls> [輸出資料夾] [--name 職場名稱] [--no-pdf] [--no-excel] [--no-sex]
"""
import json
import subprocess
import sys
from pathlib import Path

import analyze

HERE = Path(__file__).parent


def summary_table(res):
    """跨職場比較用的一列彙總（僅彙總統計，人數少於 MIN_N 的項目留空）。用 combine.py 合併各家。"""
    import pandas as pd
    info, st = res["info"], res["strata"]["all"]
    W = [w["label"] for w in info["waves"]]
    K = info["k"]
    row = {"職場": info["workplace"], **{f"{w['label']}日期": w["date"] for w in info["waves"]},
           "參加人數": info["n_total"], "納入分析": info["n_people"], "三次皆參加": info["n_complete"], "參加兩次": info["n_two"],
           "不納入": info["n_excluded"], "三次皆參加率(%)": round(100 * info["n_complete"] / info["n_total"], 1)}
    b0 = res["status"][0]
    for f in res["fields"]["binary"]:
        row[f"前測 {f['name']}(%)"] = round(100 * b0["binary"][f["code"]] / b0["n"], 1) if b0["n"] else None
    for f in res["fields"]["main"]:
        c, nm = f["code"], f["name"]
        rm = (st.get("rm") or {}).get(c)
        for j, w in enumerate(W):
            row[f"{nm} {w}平均"] = round(rm["means"][j], 2) if rm else None
        pr = next((p for p in rm["pairs"] if p["a"] == 1 and p["b"] == K), None) if rm else None
        row[f"{nm} {W[0]}→{W[-1]}變化"] = round(pr["diff"], 2) if pr else None
        row[f"{nm} 效果量d"] = round(pr["dz"], 2) if pr else None
        row[f"{nm} 主分析p"] = rm["p_final"] if rm else None
        lv = res["lmm"]["vars"].get(c, {})
        row[f"{nm} 混合模型{W[0]}→{W[-1]}變化"] = round(lv["diffs"][-1]["diff"], 2) if lv.get("diffs") else None
        row[f"{nm} 混合模型p"] = lv.get("p")
    last = (st.get("indiv") or {}).get("last") or {}
    for t in ("3", "5"):
        row[f"體重減少≥{t}%(%)"] = round(100 * last["weight_loss"][t] / last["n"], 1) if last.get("weight_loss") else None
    return pd.DataFrame([row])


def main():
    argv = sys.argv[1:]
    name = None
    if "--name" in argv:
        i = argv.index("--name")
        name = argv[i + 1]
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    src = args[0]
    outdir = Path(args[1]) if len(args) > 1 else HERE / "output"
    outdir.mkdir(parents=True, exist_ok=True)
    D, res = analyze.run(src, name, by_sex="--no-sex" not in flags)
    embed = json.loads(json.dumps(res, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    for st in embed["strata"].values():
        if st["suppressed"]:
            st["n"] = None  # 小分層連人數都不寫入網頁
            st.pop("n_wave", None)
        if (st.get("n_complete") or 0) < analyze.MIN_N:
            st["n_complete"] = None
        if (st.get("n_two") or 0) < analyze.MIN_N:
            st["n_two"] = None
        for c in (st.get("indiv") or {}).values():
            if c["n"] < analyze.MIN_N:
                c["n"] = None
    data = json.dumps(embed, ensure_ascii=False, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    data = data.replace("</", "<\\/")
    name = res["info"]["workplace"] or "報告"
    html = (HERE / "report_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/", data)
    html_path = outdir / f"{name}_成果報告.html"
    html_path.write_text(html, encoding="utf-8")
    (outdir / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)), encoding="utf-8")
    print("HTML :", html_path)
    summ = outdir / f"{name}_跨職場摘要.csv"
    summary_table(res).to_csv(summ, index=False, encoding="utf-8-sig")
    print("摘要 :", summ)
    if "--no-excel" not in flags:
        import build_excel
        xlsx = build_excel.build(D, res, outdir / f"{name}_驗算.xlsx")
        print("Excel:", xlsx)
    if "--no-pdf" not in flags:
        pdf = outdir / f"{name}_成果報告_A4.pdf"
        subprocess.run(["node", str(HERE / "render_pdf.mjs"), str(html_path), str(pdf), name], check=True)
        print("PDF  :", pdf)


if __name__ == "__main__":
    main()
