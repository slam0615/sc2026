"""產生 Excel 驗算檔（多次量測版）與 SPSS 資料檔（.sav）、語法檔（.sps）。

Excel：主要統計量以 Excel 內建公式重算，並列出 Python 計算值與差異。
公式只用 Excel 2007 起即有的函數（TDIST、TINV、FDIST、CHIDIST、BETADIST、COUNTIFS、SUMPRODUCT…），
LibreOffice 亦可計算。非整數自由度的 p 值以 BETADIST 計算（TDIST／FDIST 會把自由度截成整數）。
"""
import math
from itertools import combinations
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

import analyze as A

FONT = "Microsoft JhengHei"
F_BASE = Font(name=FONT, size=10)
F_INPUT = Font(name=FONT, size=10, color="0000FF")
F_PY = Font(name=FONT, size=10, color="7F7F7F", italic=True)
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_SUB = Font(name=FONT, size=9, color="595959")
F_TITLE = Font(name=FONT, size=14, bold=True, color="04706F")
F_BOLD = Font(name=FONT, size=10, bold=True)
FILL_HEAD = PatternFill("solid", fgColor="069494")
FILL_SUB = PatternFill("solid", fgColor="E4F4F3")
FILL_PY = PatternFill("solid", fgColor="F2F2F2")
FILL_CHK = PatternFill("solid", fgColor="FFFBE2")
THIN = Border(bottom=Side(style="thin", color="D9D9D9"))
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
FLAG_F = {
    "ow": "=IF({bmi}>=24,1,0)", "ob": "=IF({bmi}>=27,1,0)",
    "fat": '=IF(OR(AND({sex}="M",{fat}>=25),AND({sex}="F",{fat}>=30)),1,0)', "vfat": "=IF({vf}>=10,1,0)",
}


def head(ws, row, labels, widths=None, height=34):
    for j, lab in enumerate(labels, 1):
        c = ws.cell(row, j, lab)
        c.font, c.fill, c.alignment = F_HEAD, FILL_HEAD, CENTER
    ws.row_dimensions[row].height = height
    for j, w in enumerate(widths or [], 1):
        ws.column_dimensions[L(j)].width = w


def title(ws, text, sub=None):
    ws["A1"], ws["A1"].font = text, F_TITLE
    if sub:
        ws["A2"], ws["A2"].font = sub, F_SUB


def style(ws, r0, r1, c0, c1, font=F_BASE, fmt=None, fill=None):
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            cell = ws.cell(r, c)
            cell.font, cell.border = font, THIN
            if fmt:
                cell.number_format = fmt
            if fill:
                cell.fill = fill


def py(ws, r, c, v, fmt="0.000000"):
    cell = ws.cell(r, c, v)
    cell.font, cell.fill, cell.number_format = F_PY, FILL_PY, fmt


def chk(ws, r, c, formula):
    cell = ws.cell(r, c, formula)
    cell.fill, cell.number_format, cell.font = FILL_CHK, "0.0E+00", F_BASE


def build(D, res, out_path):
    K, people, long = D["K"], D["people"], D["long"]
    W = [f"T{w}" for w in range(1, K + 1)]
    fields = {**A.MAIN, **A.SEG}
    codes = list(fields)
    wb = Workbook()
    info = res["info"]

    # ------------------------------------------------------------ 說明
    ws = wb.active
    ws.title = "說明"
    rows = [
        ("TANITA 身體組成多次量測 — Excel 驗算檔", None),
        (f"職場：{info['workplace']}　" + "　".join(f"{w['label']} {w['date']}（{w['n']} 人）" for w in info["waves"])
         + f"　受測 {info['n_people']} 人、完成全部 {info['n_complete']} 人", None),
        ("", None), ("工作表", "內容"),
        ("欄位對照", "TANITA MC-780 欄位代碼、中文名稱、單位"),
        ("寬格式資料", "每人一列（序號取代編號），各次量測值；空白＝該次未量測。風險分類旗標為公式"),
        ("各次描述統計", "每次量測全部受測者的 n、平均、標準差、95% 信賴區間（公式）"),
        ("重複測量ANOVA", "完成全部量測者：平方和拆解、F、p、Mauchly 球形檢定、Greenhouse-Geisser 校正、偏 η²（公式）；Friedman 為 Python 值"),
        ("兩兩比較", "完成全部量測者的配對 t 檢定與 Bonferroni 校正（公式）＝ SPSS GLM 的 Bonferroni 事後比較"),
        ("可用配對", "每兩次量測以兩次皆有量測者進行配對 t 檢定（公式）"),
        ("分層ANOVA", "性別、年齡層各分層完成者的重複測量 ANOVA（Python 值，可用 SPSS 語法第 4 段驗證）"),
        ("CochranQ_McNemar", "風險分類變化：Cochran's Q 與 McNemar 精確檢定（公式）"),
        ("卡方檢定", "各次量測：風險分類 × 性別／年齡層（公式）；Fisher 精確檢定為 Python 值"),
        ("混合模型", "全部可用資料之線性混合模型與交互作用（Python 值，請以 SPSS MIXED 語法驗證）"),
        ("流失分析", "T1 受測者中完成 vs 未完成者的 T1 值比較（Welch t 公式、卡方公式）"),
        ("", None), ("顏色說明", ""),
        ("藍色字", "原始資料（直接輸入的數值）"), ("黑色字", "Excel 公式計算結果"),
        ("灰色斜體（灰底）", "Python（SciPy）計算的參考值"), ("黃底", "Excel − Python 差異，應接近 0"),
        ("", None),
        ("單位換算", "基礎代謝量原始資料為 kJ，已 ÷ 4.184 換算為 kcal 並取整數。"),
        ("資料處理", "；".join(info["cleaning_log"]) or "無"),
        ("隱私", "本檔含個人層級（去識別化）資料，僅供分析人員驗算使用，請勿提供給職場或公開。"),
    ]
    for i, (a, b) in enumerate(rows, 1):
        ws.cell(i, 1, a).font = F_BASE
        if b is not None:
            ws.cell(i, 2, b).font = F_BASE
            ws.cell(i, 2).alignment = Alignment(wrap_text=True, vertical="top")
    ws["A1"].font, ws["A2"].font = F_TITLE, F_SUB
    for r in (4, 17):
        ws.cell(r, 1).font = ws.cell(r, 2).font = F_BOLD
    ws["A18"].font = F_INPUT
    ws["A20"].font, ws["A20"].fill = F_PY, FILL_PY
    ws["A21"].fill = FILL_CHK
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 26, 100

    # ------------------------------------------------------------ 欄位對照
    ws = wb.create_sheet("欄位對照")
    head(ws, 1, ["原始欄位", "中文名稱", "單位", "說明", "納入統計"], [14, 26, 10, 60, 10])
    r = 2
    for code, (name, unit, note) in A.OTHER_FIELDS.items():
        for j, v in enumerate([code, name, unit, note, "否"], 1):
            ws.cell(r, j, v).font = F_BASE
        r += 1
    for code, meta in fields.items():
        for j, v in enumerate([code, meta[0], meta[1], meta[4], "是"], 1):
            ws.cell(r, j, v).font = F_BASE
        r += 1

    # ------------------------------------------------------------ 寬格式資料
    ws = wb.create_sheet("寬格式資料")
    ids = people.sort_values(["PATTERN", "SEX"]).index
    base_h1 = ["序號", "性別", "首次年齡", "年齡層", "完成全部(1=是)"] + [f"有{w}" for w in W]
    base_h2 = ["ID", "SEX", "AGE0", "AGEGRP", "COMPLETE"] + [f"HAS{w}" for w in range(1, K + 1)]
    col = {}
    c = len(base_h1) + 1
    h1, h2 = list(base_h1), list(base_h2)
    for code in codes:
        col[code] = list(range(c, c + K))
        h1 += [f"{fields[code][0]}\n{w}" for w in W]
        h2 += [f"{code}_T{w}" for w in range(1, K + 1)]
        c += K
    fcol = {}
    for bc in A.BINARY:
        fcol[bc] = list(range(c, c + K))
        h1 += [f"{A.BINARY[bc][0]}\n{w}" for w in W]
        h2 += [f"{bc}_T{w}" for w in range(1, K + 1)]
        c += K
    head(ws, 1, h1, height=46)
    for j, v in enumerate(h2, 1):
        ws.cell(2, j, v).font, ws.cell(2, j).fill = F_SUB, FILL_SUB
    R0 = 3
    R1 = R0 + len(ids) - 1
    for i, pid in enumerate(ids):
        rr = R0 + i
        p = people.loc[pid]
        for j, v in enumerate([i + 1, p.SEX, int(p.AGE0), p.AGEGRP, int(p.COMPLETE)] + [int(p[f"HAS{w}"]) for w in range(1, K + 1)], 1):
            ws.cell(rr, j, v).font = F_INPUT
        for w in range(1, K + 1):
            bw = D["by_wave"][w]
            if pid not in bw.index:
                continue
            row = bw.loc[pid]
            for code in codes:
                ws.cell(rr, col[code][w - 1], float(row[code])).font = F_INPUT
            ref = {"bmi": f"{L(col['BMI'][w - 1])}{rr}", "fat": f"{L(col['FATP'][w - 1])}{rr}",
                   "vf": f"{L(col['VFATL'][w - 1])}{rr}", "sex": f"$B{rr}"}
            for bc in A.BINARY:
                ws.cell(rr, fcol[bc][w - 1], FLAG_F[bc].format(**ref)).font = F_BASE
    for j in range(1, len(h1) + 1):
        ws.column_dimensions[L(j)].width = 10
    ws.freeze_panes = "F3"
    S = "寬格式資料"
    rng = lambda cc: f"{S}!${L(cc)}${R0}:${L(cc)}${R1}"
    COMP, SEXR, AGER = rng(5), rng(2), rng(4)
    HAS = [rng(6 + w) for w in range(K)]

    # ------------------------------------------------------------ 各次描述統計
    ws = wb.create_sheet("各次描述統計")
    title(ws, "各次量測描述統計（全部受測者）", "95% CI = 平均 ± TINV(0.05, n−1) × SD/√n。")
    hd = ["指標", "單位"]
    for w in W:
        hd += [f"{w} n", f"{w} 平均", f"{w} SD", f"{w} 95%CI 下", f"{w} 95%CI 上", f"{w} Python 平均", "差異"]
    head(ws, 4, hd, [24, 8] + [7, 10, 9, 10, 10, 10, 8] * K)
    allst = res["strata"]["all"]
    r = 5
    for code in A.MAIN:
        ws.cell(r, 1, fields[code][0])
        ws.cell(r, 2, fields[code][1])
        for w in range(K):
            c0 = 3 + w * 7
            X = rng(col[code][w])
            n_, m_, s_ = (f"{L(c0)}{r}", f"{L(c0 + 1)}{r}", f"{L(c0 + 2)}{r}")
            ws.cell(r, c0, f"=COUNT({X})")
            ws.cell(r, c0 + 1, f"=AVERAGE({X})")
            ws.cell(r, c0 + 2, f"=STDEV({X})")
            ws.cell(r, c0 + 3, f"={m_}-TINV(0.05,{n_}-1)*{s_}/SQRT({n_})")
            ws.cell(r, c0 + 4, f"={m_}+TINV(0.05,{n_}-1)*{s_}/SQRT({n_})")
        r += 1
    style(ws, 5, r - 1, 1, 2 + 7 * K, fmt="0.0000")
    for i, code in enumerate(A.MAIN):
        for w in range(K):
            c0 = 3 + w * 7
            ws.cell(5 + i, c0).number_format = "0"
            py(ws, 5 + i, c0 + 5, allst["desc"][code][w].get("mean"), "0.0000")
            chk(ws, 5 + i, c0 + 6, f"={L(c0 + 1)}{5 + i}-{L(c0 + 5)}{5 + i}")

    # ------------------------------------------------------------ 重複測量 ANOVA
    ws = wb.create_sheet("重複測量ANOVA")
    title(ws, "重複測量 ANOVA（完成全部量測者）",
          "SS 拆解：SS時間 = nΣ(各次平均−總平均)²；SS受試者 = kΣ(個人平均−總平均)²；SS誤差 = SS總 − SS時間 − SS受試者。"
          "球形：以標準正交對比矩陣 M 計算 C = M'SM（S 為各次共變異數矩陣）。")
    hd = ["指標", "單位", "n"] + [f"{w} 平均" for w in W] + ["總平均", "SS 時間", "SS 受試者", "SS 總", "SS 誤差", "df1", "df2", "F", "p（假設球形）"]
    nb = len(hd)
    if K == 3:
        hd += ["S11", "S22", "S33", "S12", "S13", "S23", "C11", "C22", "C12", "Mauchly W", "χ²", "Mauchly p", "GG ε", "GG df1", "GG df2", "p（GG）"]
    hd += ["判定 p", "偏 η²", "Python 判定 p", "差異", "Python Friedman p"]
    head(ws, 4, hd, [24, 8, 6] + [10] * K + [10] * (len(hd) - 3 - K), height=40)
    r = 5
    for code in codes:
        Ys = [rng(cc) for cc in col[code]]
        s_py = allst["rm"][code]
        cells = [fields[code][0], fields[code][1], f"=COUNTIF({COMP},1)"]
        cells += [f"=AVERAGEIF({COMP},1,{y})" for y in Ys]
        mc = [f"{L(4 + j)}{r}" for j in range(K)]
        gm = f"{L(4 + K)}{r}"
        n_ = f"C{r}"
        cells.append(f"=AVERAGE({mc[0]}:{mc[-1]})")
        cells.append(f"={n_}*SUMPRODUCT(({mc[0]}:{mc[-1]}-{gm})^2)")
        cells.append(f"={K}*SUMPRODUCT({COMP}*(({'+'.join(Ys)})/{K}-{gm})^2)")
        cells.append("=SUMPRODUCT(" + f"{COMP}*(" + "+".join(f"({y}-{gm})^2" for y in Ys) + "))")
        cT, cS, cTot = (L(5 + K + i) for i in range(3))
        cells.append(f"={cTot}{r}-{cT}{r}-{cS}{r}")
        cE = L(8 + K)
        cells += [K - 1, f"=({K}-1)*({n_}-1)"]
        cD1, cD2 = L(9 + K), L(10 + K)
        cells.append(f"=({cT}{r}/{cD1}{r})/({cE}{r}/{cD2}{r})")
        cF = L(11 + K)
        cells.append(f"=FDIST({cF}{r},{cD1}{r},{cD2}{r})")
        cP = L(12 + K)
        if K == 3:
            cov = lambda a, b: f"=SUMPRODUCT({COMP}*({Ys[a]}-{mc[a]})*({Ys[b]}-{mc[b]}))/({n_}-1)"
            cells += [cov(0, 0), cov(1, 1), cov(2, 2), cov(0, 1), cov(0, 2), cov(1, 2)]
            s11, s22, s33, s12, s13, s23 = (f"{L(nb + 1 + i)}{r}" for i in range(6))
            cells.append(f"=({s11}-2*{s12}+{s22})/2")
            cells.append(f"=({s11}+{s22}+4*{s33}+2*{s12}-4*{s13}-4*{s23})/6")
            cells.append(f"=({s11}-{s22}-2*{s13}+2*{s23})/SQRT(12)")
            c11, c22, c12 = (f"{L(nb + 7 + i)}{r}" for i in range(3))
            cW, cX, cMp, cEps, cG1, cG2, cPg = (L(nb + 10 + i) for i in range(7))
            cells.append(f"=({c11}*{c22}-{c12}^2)/(({c11}+{c22})/2)^2")
            cells.append(f"=-({n_}-1-(2*2^2+2+2)/(6*2))*LN({cW}{r})")
            cells.append(f"=CHIDIST({cX}{r},2)")
            cells.append(f"=({c11}+{c22})^2/(2*({c11}^2+2*{c12}^2+{c22}^2))")
            cells.append(f"={cD1}{r}*{cEps}{r}")
            cells.append(f"={cD2}{r}*{cEps}{r}")
            cells.append(f"=BETADIST({cG2}{r}/({cG2}{r}+{cG1}{r}*{cF}{r}),{cG2}{r}/2,{cG1}{r}/2)")
            cells.append(f"=IF({cMp}{r}<0.05,{cPg}{r},{cP}{r})")
        else:
            cells.append(f"={cP}{r}")
        cFinal = L(len(cells))
        cells.append(f"={cT}{r}/({cT}{r}+{cE}{r})")
        cells += [s_py.get("p_final"), f"={cFinal}{r}-{L(len(cells) + 1)}{r}", s_py.get("friedman_p")]
        for j, v in enumerate(cells, 1):
            ws.cell(r, j, v)
        r += 1
    R_end = r - 1
    ncol = len(hd)
    style(ws, 5, R_end, 1, ncol, fmt="0.0000")
    style(ws, 5, R_end, ncol - 2, ncol - 2, font=F_PY, fmt="0.000000", fill=FILL_PY)
    style(ws, 5, R_end, ncol, ncol, font=F_PY, fmt="0.000000", fill=FILL_PY)
    style(ws, 5, R_end, ncol - 1, ncol - 1, fmt="0.0E+00", fill=FILL_CHK)
    ws.cell(R_end + 2, 1, "判定：Mauchly p < 0.05 時採 Greenhouse-Geisser 校正之 p，否則採假設球形之 p（同 SPSS 報表慣例）。GG 校正 p 以 BETADIST 計算以保留小數自由度。").font = F_SUB
    ws.freeze_panes = "D5"

    # ------------------------------------------------------------ 兩兩比較（完成者）
    ws = wb.create_sheet("兩兩比較")
    nbf = K * (K - 1) // 2
    title(ws, f"兩兩比較：完成全部量測者配對 t 檢定（Bonferroni × {nbf}）",
          "等同 SPSS GLM Repeated Measures 的 EMMEANS COMPARE ADJ(BONFERRONI)。差值＝後一次 − 前一次。")
    hd = ["指標", "比較", "n", "平均差", "差值 SD", "SE", "t", "df", "p（未校正）", "p（Bonferroni）", "CI 下限（校正）", "CI 上限（校正）", "Python p（Bonferroni）", "差異"]
    head(ws, 4, hd, [24, 10, 6, 10, 10, 10, 9, 6, 11, 11, 11, 11, 12, 9])
    r = 5
    for code in A.MAIN:
        for k, (a, b) in enumerate(combinations(range(K), 2)):
            Ya, Yb = rng(col[code][a]), rng(col[code][b])
            pr = allst["rm"][code]["pairs"][k]
            cells = [fields[code][0], f"{W[a]}→{W[b]}", f"=COUNTIF({COMP},1)",
                     f"=(SUMIF({COMP},1,{Yb})-SUMIF({COMP},1,{Ya}))/C{r}",
                     f"=SQRT((SUMPRODUCT({COMP}*({Yb}-{Ya})^2)-C{r}*D{r}^2)/(C{r}-1))", f"=E{r}/SQRT(C{r})",
                     f"=IFERROR(D{r}/F{r},0)", f"=C{r}-1", f"=IFERROR(TDIST(ABS(G{r}),H{r},2),1)", f"=MIN(1,I{r}*{nbf})",
                     f"=D{r}-TINV(0.05/{nbf},H{r})*F{r}", f"=D{r}+TINV(0.05/{nbf},H{r})*F{r}", pr.get("p_bonf"), f"=J{r}-M{r}"]
            for j, v in enumerate(cells, 1):
                ws.cell(r, j, v)
            r += 1
    style(ws, 5, r - 1, 1, 14, fmt="0.0000")
    style(ws, 5, r - 1, 13, 13, font=F_PY, fmt="0.000000", fill=FILL_PY)
    style(ws, 5, r - 1, 14, 14, fmt="0.0E+00", fill=FILL_CHK)

    # ------------------------------------------------------------ 可用配對
    ws = wb.create_sheet("可用配對")
    title(ws, f"每兩次量測：兩次皆有量測者的配對 t 檢定（Bonferroni × {nbf}）", "n = 兩次皆有數值的人數。")
    head(ws, 4, hd, [24, 10, 6, 10, 10, 10, 9, 6, 11, 11, 11, 11, 12, 9])
    r = 5
    for code in A.MAIN:
        for k, (a, b) in enumerate(combinations(range(K), 2)):
            Ya, Yb = rng(col[code][a]), rng(col[code][b])
            both = f"({HAS[a]}=1)*({HAS[b]}=1)"
            pr = allst["avail"][code][k]
            cells = [fields[code][0], f"{W[a]}→{W[b]}", f"=SUMPRODUCT({both})",
                     f"=SUMPRODUCT({both}*({Yb}-{Ya}))/C{r}",
                     f"=SQRT((SUMPRODUCT({both}*({Yb}-{Ya})^2)-C{r}*D{r}^2)/(C{r}-1))", f"=E{r}/SQRT(C{r})",
                     f"=IFERROR(D{r}/F{r},0)", f"=C{r}-1", f"=IFERROR(TDIST(ABS(G{r}),H{r},2),1)", f"=MIN(1,I{r}*{nbf})",
                     f"=D{r}-TINV(0.05/{nbf},H{r})*F{r}", f"=D{r}+TINV(0.05/{nbf},H{r})*F{r}", pr.get("p_bonf"), f"=J{r}-M{r}"]
            for j, v in enumerate(cells, 1):
                ws.cell(r, j, v)
            r += 1
    style(ws, 5, r - 1, 1, 14, fmt="0.0000")
    style(ws, 5, r - 1, 13, 13, font=F_PY, fmt="0.000000", fill=FILL_PY)
    style(ws, 5, r - 1, 14, 14, fmt="0.0E+00", fill=FILL_CHK)

    # ------------------------------------------------------------ 分層 ANOVA（Python 值）
    ws = wb.create_sheet("分層ANOVA")
    title(ws, "分層重複測量 ANOVA（完成全部量測者；Python 值）", "請以 SPSS 語法第 4 段（SPLIT FILE）驗證。人數不足 %d 人的分層不分析。" % A.MIN_N)
    hd = ["分層", "完成人數", "指標"] + [f"{w} 平均" for w in W] + ["F", "df1", "df2", "GG 校正", "判定 p", "偏 η²", "Friedman p"]
    head(ws, 4, hd, [14, 9, 24] + [10] * (len(hd) - 3))
    r = 5
    for key, st in res["strata"].items():
        if key == "all" or "|" in key or "rm" not in st:
            continue
        for code in A.MAIN:
            s = st["rm"][code]
            vals = [st["label"], st["n_complete"], fields[code][0], *s["means"], s["F"],
                    s["df1_gg"] if s["use_gg"] else s["df1"], s["df2_gg"] if s["use_gg"] else s["df2"],
                    "是" if s["use_gg"] else "否", s["p_final"], s["pes"], s["friedman_p"]]
            for j, v in enumerate(vals, 1):
                ws.cell(r, j, v)
            r += 1
    style(ws, 5, r - 1, 1, len(hd), font=F_PY, fmt="0.0000")

    # ------------------------------------------------------------ Cochran's Q / McNemar
    ws = wb.create_sheet("CochranQ_McNemar")
    title(ws, "風險分類變化（完成全部量測者）",
          "Cochran's Q = (k−1)[kΣCj² − T²] / (kT − ΣRi²)；McNemar 精確 p = min(1, 2×BINOMDIST(min(b,c), b+c, 0.5, TRUE))，Bonferroni × %d。" % nbf)
    hd = ["風險分類", "n"] + [f"{w} 人數" for w in W] + ["T", "ΣRi²", "Q", "df", "p", "Python p", "差異"]
    for a, b in combinations(range(K), 2):
        hd += [f"{W[a]}→{W[b]} 改善 b", f"{W[a]}→{W[b]} 惡化 c", f"{W[a]}→{W[b]} p（校正）", "Python", "差異"]
    head(ws, 4, hd, [30, 6] + [10] * (len(hd) - 2), height=40)
    r = 5
    for bc in A.BINARY:
        Fs = [rng(cc) for cc in fcol[bc]]
        it = allst["binary"][bc]
        cells = [A.BINARY[bc][0], f"=COUNTIF({COMP},1)"] + [f"=SUMIF({COMP},1,{f})" for f in Fs]
        cC = [f"{L(3 + j)}{r}" for j in range(K)]
        cT = L(3 + K)
        cells.append("=" + "+".join(cC))
        cells.append(f"=SUMPRODUCT({COMP}*(" + "+".join(Fs) + ")^2)")
        cR = L(4 + K)
        cells.append(f"=IF({K}*{cT}{r}-{cR}{r}=0,0,({K}-1)*({K}*SUMPRODUCT(({cC[0]}:{cC[-1]})^2)-{cT}{r}^2)/({K}*{cT}{r}-{cR}{r}))")
        cQ = L(5 + K)
        cells += [K - 1, f"=CHIDIST({cQ}{r},{K - 1})", it.get("p"), f"={L(7 + K)}{r}-{L(8 + K)}{r}"]
        for k, (a, b) in enumerate(combinations(range(K), 2)):
            c0 = len(cells) + 1
            cells += [f"=SUMPRODUCT({COMP}*({Fs[a]}=1)*({Fs[b]}=0))", f"=SUMPRODUCT({COMP}*({Fs[a]}=0)*({Fs[b]}=1))",
                      f"=IF({L(c0)}{r}+{L(c0 + 1)}{r}=0,1,MIN(1,{nbf}*MIN(1,2*BINOMDIST(MIN({L(c0)}{r},{L(c0 + 1)}{r}),{L(c0)}{r}+{L(c0 + 1)}{r},0.5,TRUE))))",
                      it["pairs"][k]["p_bonf"], f"={L(c0 + 2)}{r}-{L(c0 + 3)}{r}"]
        for j, v in enumerate(cells, 1):
            ws.cell(r, j, v)
        r += 1
    style(ws, 5, r - 1, 1, len(hd), fmt="0.0000")
    for j, h in enumerate(hd, 1):
        if h.startswith("Python") or h == "Python":
            style(ws, 5, r - 1, j, j, font=F_PY, fmt="0.000000", fill=FILL_PY)
        if h == "差異":
            style(ws, 5, r - 1, j, j, fmt="0.0E+00", fill=FILL_CHK)

    # ------------------------------------------------------------ 卡方檢定
    ws = wb.create_sheet("卡方檢定")
    title(ws, "各次量測：風險分類 × 性別／年齡層（Pearson 卡方）",
          "期望次數 = 列合計 × 欄合計 ÷ 總數；χ² = Σ(O−E)²/E；p = CHIDIST(χ², df)。期望次數 < 5 的格子超過 20% 時參考 Fisher（Python）。")
    ws.column_dimensions["A"].width = 34
    for j in range(2, 12):
        ws.column_dimensions[L(j)].width = 12
    r = 4
    for x in res["chisq"]:
        w, bc = x["wave"], x["outcome"]
        grp = SEXR if x["by"] == "性別" else AGER
        keys = ["M", "F"] if x["by"] == "性別" else info["age_groups"]
        Fw = rng(fcol[bc][w - 1])
        ws.cell(r, 1, f"T{w}｜{x['outcome_name']} × {x['by']}").font = F_BOLD
        r += 1
        for j, v in enumerate(["觀察次數 O", "是", "否", "合計", "", "期望次數 E", "是", "否"], 1):
            ws.cell(r, j, v).font, ws.cell(r, j).fill = F_HEAD, FILL_HEAD
        top = r + 1
        for i, (lab, kk) in enumerate(zip(x["rows"], keys)):
            rr = top + i
            ws.cell(rr, 1, lab).font = F_BOLD
            ws.cell(rr, 2, f'=COUNTIFS({grp},"={kk}",{Fw},1)')
            ws.cell(rr, 3, f'=COUNTIFS({grp},"={kk}",{Fw},0)')
            ws.cell(rr, 4, f"=B{rr}+C{rr}")
            ws.cell(rr, 6, lab).font = F_BOLD
        last = top + len(keys) - 1
        tot = last + 1
        ws.cell(tot, 1, "合計").font = F_BOLD
        for cc in (2, 3, 4):
            ws.cell(tot, cc, f"=SUM({L(cc)}{top}:{L(cc)}{last})")
        for i in range(len(keys)):
            for cc, oc in ((7, 2), (8, 3)):
                ws.cell(top + i, cc, f"=$D{top + i}*{L(oc)}${tot}/$D${tot}").number_format = "0.00"
        O, E = f"B{top}:C{last}", f"G{top}:H{last}"
        sr = tot + 1
        labs = ["χ²", "df", "p 值", "p 驗證 (CHITEST)", "Python p", "差異", "最小期望次數", "期望 < 5 格數", "Python Fisher p"]
        fml = [f"=SUMPRODUCT(({O}-{E})^2/{E})", f"=({len(keys)}-1)*(2-1)", f"=CHIDIST(B{sr + 1},C{sr + 1})", f"=CHITEST({O},{E})",
               x["p"], f"=D{sr + 1}-F{sr + 1}", f"=MIN({E})", f'=COUNTIF({E},"<5")', x["p_fisher"]]
        for j, (lab, v) in enumerate(zip(labs, fml)):
            ws.cell(sr, 2 + j, lab).font = F_SUB
            cell = ws.cell(sr + 1, 2 + j, v)
            cell.number_format = "0.000000" if "p" in lab else "0.0000"
            if lab.startswith("Python"):
                cell.font, cell.fill = F_PY, FILL_PY
            if lab == "差異":
                cell.fill, cell.number_format = FILL_CHK, "0.0E+00"
        r = sr + 3

    # ------------------------------------------------------------ 混合模型（Python 值）
    ws = wb.create_sheet("混合模型")
    title(ws, "線性混合模型（全部可用資料；Python 值）",
          "時間為固定效果、個人隨機截距、REML、Satterthwaite 自由度。請以 SPSS 語法第 6 段（MIXED）驗證；自由度為近似值，SPSS 結果可能於小數第三位有些微差異。")
    hd = ["指標", "人數", "筆數", "σ² 個人", "σ² 殘差", "F", "df1", "df2", "p"] + [f"{w} 估計值" for w in W] + \
         [f"{W[a]}→{W[b]} p（Bonferroni）" for a, b in combinations(range(K), 2)] + ["時間×性別 p", "時間×年齡層 p"]
    head(ws, 4, hd, [24] + [10] * (len(hd) - 1), height=40)
    r = 5
    for code in A.MAIN:
        m = allst["mixed"].get(code)
        if not m:
            continue
        it = res["interaction"][code]
        vals = [fields[code][0], m["n"], m["n_obs"], m["var_subject"], m["var_resid"], m["F"], m["df1"], m["df2"], m["p"]] + \
               [e["mean"] for e in m["emm"]] + [p["p_bonf"] for p in m["pairs"]] + \
               [(it.get("sex") or {}).get("p"), (it.get("age") or {}).get("p")]
        for j, v in enumerate(vals, 1):
            ws.cell(r, j, v)
        r += 1
    style(ws, 5, r - 1, 1, len(hd), font=F_PY, fmt="0.0000")

    # ------------------------------------------------------------ 流失分析
    ws = wb.create_sheet("流失分析")
    title(ws, "T1 受測者：完成全部量測 vs 未完成（T1 值）",
          "Welch t：p = BETADIST(df/(df+t²), df/2, 0.5)，保留小數自由度。")
    hd = ["變項", "完成 n", "完成 平均", "完成 SD", "未完成 n", "未完成 平均", "未完成 SD", "Welch t", "df", "p", "Python p", "差異"]
    head(ws, 4, hd, [22, 8, 11, 10, 9, 11, 10, 9, 9, 10, 10, 9])
    H1 = HAS[0]
    r = 5
    for v in res["attrition"]["vars"]:
        X = rng(3) if v["code"] == "AGE" else rng(col[v["code"]][0])
        if v["code"] == "AGE":  # T1 年齡＝首次年齡（T1 受測者的首次量測即 T1）
            X = rng(3)
        c1, c0 = f"({H1}=1)*({COMP}=1)", f"({H1}=1)*({COMP}=0)"
        sd = lambda cnd, nn, mm: f"=SQRT((SUMPRODUCT({cnd}*({X})^2)-{nn}*{mm}^2)/({nn}-1))"
        cells = [v["name"], f"=SUMPRODUCT({c1})", f"=SUMPRODUCT({c1}*{X})/B{r}", sd(c1, f"B{r}", f"C{r}"),
                 f"=SUMPRODUCT({c0})", f"=SUMPRODUCT({c0}*{X})/E{r}", sd(c0, f"E{r}", f"F{r}"),
                 f"=(C{r}-F{r})/SQRT(D{r}^2/B{r}+G{r}^2/E{r})",
                 f"=(D{r}^2/B{r}+G{r}^2/E{r})^2/((D{r}^2/B{r})^2/(B{r}-1)+(G{r}^2/E{r})^2/(E{r}-1))",
                 f"=BETADIST(I{r}/(I{r}+H{r}^2),I{r}/2,0.5)", v["p"], f"=J{r}-K{r}"]
        for j, val in enumerate(cells, 1):
            ws.cell(r, j, val)
        r += 1
    style(ws, 5, r - 1, 1, 12, fmt="0.0000")
    style(ws, 5, r - 1, 11, 11, font=F_PY, fmt="0.000000", fill=FILL_PY)
    style(ws, 5, r - 1, 12, 12, fmt="0.0E+00", fill=FILL_CHK)

    for wsx in wb.worksheets:
        wsx.sheet_view.showGridLines = wsx.title != "說明"
    out_path = Path(out_path)
    wb.save(out_path)
    write_spss(D, res, out_path)
    return out_path


# ---------------------------------------------------------------- SPSS
def write_spss(D, res, xlsx_path):
    import pyreadstat
    import pandas as pd

    K, people, long = D["K"], D["people"], D["long"]
    ages = res["info"]["age_groups"]
    fields = {**A.MAIN, **A.SEG}
    ids = people.sort_values(["PATTERN", "SEX"]).index
    idmap = {pid: i + 1 for i, pid in enumerate(ids)}
    # 寬格式
    wide = pd.DataFrame({"ID": [idmap[p] for p in ids],
                         "SEX": [1 if people.loc[p, "SEX"] == "M" else 2 for p in ids],
                         "AGE0": [int(people.loc[p, "AGE0"]) for p in ids],
                         "AGEGRP": [ages.index(people.loc[p, "AGEGRP"]) + 1 for p in ids],
                         "COMPLETE": [int(people.loc[p, "COMPLETE"]) for p in ids]})
    for w in range(1, K + 1):
        wide[f"HAS{w}"] = [int(people.loc[p, f"HAS{w}"]) for p in ids]
    labels = {"ID": "序號", "SEX": "性別", "AGE0": "首次量測年齡", "AGEGRP": "年齡層", "COMPLETE": "完成全部量測"}
    for w in range(1, K + 1):
        labels[f"HAS{w}"] = f"有 T{w} 量測"
    for code, meta in fields.items():
        for w in range(1, K + 1):
            bw = D["by_wave"][w]
            wide[f"{code}_T{w}"] = [float(bw.loc[p, code]) if p in bw.index else None for p in ids]
            labels[f"{code}_T{w}"] = f"{meta[0]}（{meta[1]}）T{w}"
    for bc, (bname, _) in A.BINARY.items():
        for w in range(1, K + 1):
            bw = D["by_wave"][w]
            wide[f"{bc}_T{w}"] = [float(bw.loc[p, bc]) if p in bw.index else None for p in ids]
            labels[f"{bc}_T{w}"] = f"{bname} T{w}"
    vlab = {"SEX": {1: "男性", 2: "女性"}, "AGEGRP": {i + 1: g for i, g in enumerate(ages)}, "COMPLETE": {0: "否", 1: "是"}}
    for bc in A.BINARY:
        for w in range(1, K + 1):
            vlab[f"{bc}_T{w}"] = {0: "否", 1: "是"}
    stem = xlsx_path.with_suffix("")
    pyreadstat.write_sav(wide, f"{stem}_寬格式.sav", column_labels=labels, variable_value_labels=vlab)
    # 長格式
    lg = long[long.CUSTOMERID.isin(ids)].copy()
    lgo = pd.DataFrame({"ID": lg.CUSTOMERID.map(idmap).values, "TIME": lg.WAVE.values,
                        "SEX": (lg.SEX.map({"M": 1, "F": 2})).values, "AGEGRP": lg.AGEGRP.map(lambda g: ages.index(g) + 1).values,
                        "COMPLETE": lg.CUSTOMERID.map(people.COMPLETE).values})
    llab = {"ID": "序號", "TIME": "量測次別", "SEX": "性別", "AGEGRP": "年齡層", "COMPLETE": "完成全部量測"}
    for code, meta in A.MAIN.items():
        lgo[code] = lg[code].values
        llab[code] = f"{meta[0]}（{meta[1]}）"
    for bc, (bname, _) in A.BINARY.items():
        lgo[bc] = lg[bc].values
        llab[bc] = bname
    lgo = lgo.sort_values(["ID", "TIME"])
    lvl = {k: v for k, v in vlab.items() if k in ("SEX", "AGEGRP", "COMPLETE")}
    lvl["TIME"] = {w: f"T{w}" for w in range(1, K + 1)}
    for bc in A.BINARY:
        lvl[bc] = {0: "否", 1: "是"}
    pyreadstat.write_sav(lgo, f"{stem}_長格式.sav", column_labels=llab, variable_value_labels=lvl)
    write_sps(res, Path(f"{stem}_寬格式.sav").name, Path(f"{stem}_長格式.sav").name, Path(f"{stem}.sps"), K)


def write_sps(res, wide_name, long_name, path, K):
    main = list(A.MAIN)
    T = lambda c: " ".join(f"{c}_T{w}" for w in range(1, K + 1))
    pairs = list(combinations(range(1, K + 1), 2))
    left = lambda c: " ".join(f"{c}_T{a}" for a, b in pairs)
    right = lambda c: " ".join(f"{c}_T{b}" for a, b in pairs)
    flags = list(A.BINARY)
    nb = len(pairs)
    out = [f"""* =====================================================================.
* TANITA 身體組成多次量測 — SPSS 驗證語法（{res['info']['workplace']}）.
* 使用前請將 FILE 路徑改為 .sav 檔實際位置（或先以 CD 指令切換到檔案所在資料夾）.
* 需要模組：GLM 重複測量與 MIXED 需 Advanced Statistics；/METHOD=EXACT 需 Exact Tests.
* =====================================================================.
SET UNICODE=ON.

* ---------- 1. 各次描述統計與 95% 信賴區間（全部受測者）.
GET FILE='{wide_name}'.
DATASET NAME wide WINDOW=FRONT.
EXAMINE VARIABLES={' '.join(T(c) for c in main)}
  /PLOT NONE /STATISTICS DESCRIPTIVES /CINTERVAL 95 /MISSING PAIRWISE /NOTOTAL.

* ---------- 2. 主分析：重複測量 ANOVA（GLM 自動只用完成全部量測者）.
* 報表：Mauchly 球形檢定、Greenhouse-Geisser、偏 η²、Bonferroni 事後比較.
"""]
    for c in list(A.MAIN) + list(A.SEG):
        out.append(f"""GLM {T(c)}
  /WSFACTOR=time {K} Polynomial
  /METHOD=SSTYPE(3)
  /EMMEANS=TABLES(time) COMPARE ADJ(BONFERRONI)
  /PRINT=DESCRIPTIVE ETASQ
  /CRITERIA=ALPHA(.05)
  /WSDESIGN=time.""")
    out.append("\n* ---------- 3. Friedman 檢定（無母數參考；每項單獨排除缺測）.")
    out.append("NPAR TESTS\n" + "\n".join(f"  /FRIEDMAN={T(c)}" for c in main) + "\n  /MISSING ANALYSIS.")
    out.append(f"""
* ---------- 4. 分層：性別、年齡層各自的重複測量 ANOVA.
SORT CASES BY SEX.
SPLIT FILE LAYERED BY SEX.""")
    for c in main:
        out.append(f"GLM {T(c)} /WSFACTOR=time {K} Polynomial /METHOD=SSTYPE(3) /PRINT=DESCRIPTIVE ETASQ /WSDESIGN=time.")
    out.append("SPLIT FILE OFF.\nSORT CASES BY AGEGRP.\nSPLIT FILE LAYERED BY AGEGRP.")
    for c in main:
        out.append(f"GLM {T(c)} /WSFACTOR=time {K} Polynomial /METHOD=SSTYPE(3) /PRINT=DESCRIPTIVE ETASQ /WSDESIGN=time.")
    out.append("SPLIT FILE OFF.")
    out.append(f"""
* ---------- 5. 補充：每兩次量測，以兩次皆有量測者做配對 t 檢定（Bonferroni：p × {nb}）.
T-TEST PAIRS={' '.join(left(c) for c in main)}
  WITH {' '.join(right(c) for c in main)} (PAIRED)
  /CRITERIA=CI(.9500) /MISSING=ANALYSIS.

* ---------- 6. 風險分類：Cochran's Q 與 McNemar（McNemar p 請自行 × {nb} 做 Bonferroni）.
NPAR TESTS
{chr(10).join(f"  /COCHRAN={T(f)}" for f in flags)}
  /MISSING LISTWISE.
NPAR TESTS
  /MCNEMAR={' '.join(left(f) for f in flags)} WITH {' '.join(right(f) for f in flags)} (PAIRED)
  /MISSING ANALYSIS.

* ---------- 7. T1 受測者：完成全部 vs 未完成（T1 值）.
TEMPORARY.
SELECT IF HAS1 = 1.
T-TEST GROUPS=COMPLETE(1 0) /VARIABLES=AGE0 WEIGHT_T1 BMI_T1 FATP_T1 PMM_T1 VFATL_T1 /CRITERIA=CI(.95).
TEMPORARY.
SELECT IF HAS1 = 1.
CROSSTABS /TABLES=SEX BY COMPLETE /STATISTICS=CHISQ /CELLS=COUNT EXPECTED ROW.

* ---------- 8. 線性混合模型（全部可用資料；長格式）.
GET FILE='{long_name}'.
DATASET NAME long WINDOW=FRONT.""")
    for c in main:
        out.append(f"""MIXED {c} BY TIME
  /FIXED=TIME | SSTYPE(3)
  /METHOD=REML
  /RANDOM=INTERCEPT | SUBJECT(ID) COVTYPE(VC)
  /PRINT=SOLUTION TESTCOV
  /EMMEANS=TABLES(TIME) COMPARE ADJ(BONFERRONI).""")
    out.append("\n* ---------- 9. 時間 × 性別、時間 × 年齡層 交互作用（MIXED）.")
    for c in main:
        for g in ("SEX", "AGEGRP"):
            out.append(f"MIXED {c} BY TIME {g} /FIXED=TIME {g} TIME*{g} | SSTYPE(3) /METHOD=REML /RANDOM=INTERCEPT | SUBJECT(ID) COVTYPE(VC).")
    out.append(f"""
* ---------- 10. 各次量測：風險分類 × 性別／年齡層 卡方與 Fisher 精確檢定.
SORT CASES BY TIME.
SPLIT FILE LAYERED BY TIME.
CROSSTABS /TABLES={' '.join(flags)} BY SEX AGEGRP
  /STATISTICS=CHISQ /CELLS=COUNT EXPECTED ROW /METHOD=EXACT TIMER(5).
SPLIT FILE OFF.
""")
    path.write_text("\n".join(out), encoding="utf-8")
