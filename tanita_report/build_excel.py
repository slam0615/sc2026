"""產生 Excel 驗算檔與 SPSS 資料檔（.sav）、語法檔（.sps）。

Excel：主要統計量以 Excel 內建公式重算，並列出 Python 計算值與差異。
只用 Excel 2007 起即有的函數（TDIST、TINV、FDIST、CHIDIST、BETADIST、COUNTIFS、AVERAGEIFS、SUMPRODUCT…），
LibreOffice 也能計算。非整數自由度的 p 值以 BETADIST 計算（TDIST／FDIST 會把自由度截成整數）。
"""
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


def head(ws, row, labels, widths=None, height=36):
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


def mark(ws, r0, r1, headers):
    """依表頭把 Python 參考值欄設為灰底、差異欄設為黃底。"""
    for j, h in enumerate(headers, 1):
        if str(h).startswith("Python"):
            style(ws, r0, r1, j, j, font=F_PY, fmt="0.000000", fill=FILL_PY)
        elif h == "差異":
            style(ws, r0, r1, j, j, fmt="0.0E+00", fill=FILL_CHK)


def build(D, res, out_path):
    K, people = D["K"], D["people"]
    W = D["names"]
    codes = list(A.MAIN)
    info, allst = res["info"], res["strata"]["all"]
    wb = Workbook()

    # ------------------------------------------------------------ 說明
    ws = wb.active
    ws.title = "說明"
    rows = [
        (f"{info['title']} — Excel 驗算檔", None),
        (f"單位：{info['workplace']}　" + "　".join(f"{w['label']} {w['date']}（第 {w['week']} 週，{w['n']} 人）" for w in info["waves"])
         + f"　參加 {info['n_people']} 人、三次皆參加 {info['n_complete']} 人", None),
        ("", None), ("工作表", "內容"),
        ("欄位對照", "TANITA MC-780 欄位代碼、中文名稱、單位"),
        ("寬格式資料", "每人一列（序號取代編號）；空白＝該次未量測。風險分類旗標與交互作用用的對比分數為公式"),
        ("各次描述統計", "每次量測全部參加者的 n、平均、標準差、95% 信賴區間"),
        ("重複測量ANOVA", "三次皆參加者：平方和拆解、F、p、Mauchly 球形檢定、Greenhouse-Geisser 校正、偏 η²"),
        ("兩兩比較", "三次皆參加者的配對 t 檢定與 Bonferroni 校正（＝ SPSS GLM 的 Bonferroni 事後比較）"),
        ("與前測配對", "前測→後測、前測→追蹤測：兩次皆有量測者（含只參加兩次者）的配對 t 檢定"),
        ("交互作用", "時間 × 性別、時間 × 年齡層（混合設計 ANOVA，三次皆參加者）"),
        ("分層ANOVA", "性別、年齡層各分層的重複測量 ANOVA（Python 值，以 SPSS 語法第 5 段驗證）"),
        ("CochranQ_McNemar", "風險分類變化：Cochran's Q、McNemar 精確檢定"),
        ("卡方檢定", "各次量測：風險分類 × 性別／年齡層；Fisher 精確檢定為 Python 值"),
        ("流失分析", "前測參加者中三次皆參加 vs 未完成者的前測值比較"),
        ("", None), ("顏色說明", ""),
        ("藍色字", "原始資料（直接輸入的數值）"), ("黑色字", "Excel 公式計算結果"),
        ("灰色斜體（灰底）", "Python（SciPy）計算的參考值"), ("黃底", "Excel − Python 差異，應接近 0"),
        ("", None),
        ("無法用公式的項目", "Wilcoxon、Friedman、Fisher 精確檢定為 Python 值，可用同名 .sps 在 SPSS 重跑驗證。"),
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
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 24, 100

    # ------------------------------------------------------------ 欄位對照
    ws = wb.create_sheet("欄位對照")
    head(ws, 1, ["原始欄位", "中文名稱", "單位", "說明"], [14, 22, 10, 70])
    r = 2
    for code, (name, unit, note) in A.OTHER_FIELDS.items():
        for j, v in enumerate([code, name, unit, note], 1):
            ws.cell(r, j, v).font = F_BASE
        r += 1
    for code, meta in A.MAIN.items():
        for j, v in enumerate([code, meta[0], meta[1], meta[4]], 1):
            ws.cell(r, j, v).font = F_BASE
        r += 1

    # ------------------------------------------------------------ 寬格式資料
    ws = wb.create_sheet("寬格式資料")
    ids = people.sort_values(["COMPLETE", "SEX", "AGE0"], ascending=[False, True, True]).index
    h1 = ["序號", "性別", "首次年齡", "年齡層", "三次皆參加(1=是)"] + [f"有{w}" for w in W]
    h2 = ["ID", "SEX", "AGE0", "AGEGRP", "COMPLETE"] + [f"HAS{w}" for w in range(1, K + 1)]
    col, fcol, zcol = {}, {}, {}
    c = len(h1) + 1
    for code in codes:
        col[code] = list(range(c, c + K))
        h1 += [f"{A.MAIN[code][0]}\n{w}" for w in W]
        h2 += [f"{code}_T{w}" for w in range(1, K + 1)]
        c += K
    for bc in A.BINARY:
        fcol[bc] = list(range(c, c + K))
        h1 += [f"{A.BINARY[bc][0]}\n{w}" for w in W]
        h2 += [f"{bc}_T{w}" for w in range(1, K + 1)]
        c += K
    if K == 3:
        for code in codes:
            zcol[code] = [c, c + 1]
            h1 += [f"{A.MAIN[code][0]}\n對比1=(前−後)/√2", f"{A.MAIN[code][0]}\n對比2=(前+後−2追)/√6"]
            h2 += [f"{code}_Z1", f"{code}_Z2"]
            c += 2
    head(ws, 1, h1, height=48)
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
        if K == 3 and p.COMPLETE == 1:
            for code in codes:
                y = [f"{L(cc)}{rr}" for cc in col[code]]
                ws.cell(rr, zcol[code][0], f"=({y[0]}-{y[1]})/SQRT(2)").font = F_BASE
                ws.cell(rr, zcol[code][1], f"=({y[0]}+{y[1]}-2*{y[2]})/SQRT(6)").font = F_BASE
    for j in range(1, len(h1) + 1):
        ws.column_dimensions[L(j)].width = 10
    ws.freeze_panes = "F3"
    S = "寬格式資料"
    rng = lambda cc: f"{S}!${L(cc)}${R0}:${L(cc)}${R1}"
    COMP, SEXR, AGER = rng(5), rng(2), rng(4)
    HAS = [rng(6 + w) for w in range(K)]

    # ------------------------------------------------------------ 各次描述統計
    ws = wb.create_sheet("各次描述統計")
    title(ws, "各次量測描述統計（全部參加者）", "95% CI = 平均 ± TINV(0.05, n−1) × SD/√n。")
    hd = ["指標", "單位"]
    for w in W:
        hd += [f"{w} n", f"{w} 平均", f"{w} SD", f"{w} 95%CI 下", f"{w} 95%CI 上", f"Python {w} 平均", "差異"]
    head(ws, 4, hd, [16, 8] + [7, 10, 9, 10, 10, 10, 8] * K)
    for i, code in enumerate(codes):
        r = 5 + i
        ws.cell(r, 1, A.MAIN[code][0])
        ws.cell(r, 2, A.MAIN[code][1])
        for w in range(K):
            c0 = 3 + w * 7
            X = rng(col[code][w])
            n_, m_, s_ = f"{L(c0)}{r}", f"{L(c0 + 1)}{r}", f"{L(c0 + 2)}{r}"
            vals = [f"=COUNT({X})", f"=AVERAGE({X})", f"=STDEV({X})", f"={m_}-TINV(0.05,{n_}-1)*{s_}/SQRT({n_})",
                    f"={m_}+TINV(0.05,{n_}-1)*{s_}/SQRT({n_})", allst["desc"][code][w].get("mean"), f"={m_}-{L(c0 + 5)}{r}"]
            for j, v in enumerate(vals):
                ws.cell(r, c0 + j, v)
    style(ws, 5, 4 + len(codes), 1, len(hd), fmt="0.0000")
    mark(ws, 5, 4 + len(codes), hd)

    # ------------------------------------------------------------ 重複測量 ANOVA
    ws = wb.create_sheet("重複測量ANOVA")
    title(ws, "重複測量 ANOVA（三次皆參加者）",
          "SS時間 = nΣ(各次平均−總平均)²；SS受試者 = kΣ(個人平均−總平均)²；SS誤差 = SS總 − SS時間 − SS受試者。球形：C = M'SM（M 為標準正交對比，S 為各次共變異數矩陣）。")
    hd = ["指標", "單位", "n"] + [f"{w} 平均" for w in W] + ["總平均", "SS 時間", "SS 受試者", "SS 總", "SS 誤差", "df1", "df2", "F", "p（假設球形）"]
    nb = len(hd)
    if K == 3:
        hd += ["S11", "S22", "S33", "S12", "S13", "S23", "C11", "C22", "C12", "Mauchly W", "χ²", "Mauchly p", "GG ε", "GG df1", "GG df2", "p（GG）"]
    hd += ["判定 p", "偏 η²", "Python 判定 p", "差異", "Python Friedman p"]
    head(ws, 4, hd, [16, 8, 6] + [10] * (len(hd) - 3), height=40)
    for i, code in enumerate(codes):
        r = 5 + i
        Ys = [rng(cc) for cc in col[code]]
        mc = [f"{L(4 + j)}{r}" for j in range(K)]
        gm, n_ = f"{L(4 + K)}{r}", f"C{r}"
        cT, cS, cTot, cE, cD1, cD2, cF, cP = (L(5 + K + j) for j in range(8))
        cells = [A.MAIN[code][0], A.MAIN[code][1], f"=COUNTIF({COMP},1)"] + [f"=AVERAGEIF({COMP},1,{y})" for y in Ys]
        cells += [f"=AVERAGE({mc[0]}:{mc[-1]})", f"={n_}*SUMPRODUCT(({mc[0]}:{mc[-1]}-{gm})^2)",
                  f"={K}*SUMPRODUCT({COMP}*(({'+'.join(Ys)})/{K}-{gm})^2)",
                  "=SUMPRODUCT(" + f"{COMP}*(" + "+".join(f"({y}-{gm})^2" for y in Ys) + "))",
                  f"={cTot}{r}-{cT}{r}-{cS}{r}", K - 1, f"=({K}-1)*({n_}-1)",
                  f"=({cT}{r}/{cD1}{r})/({cE}{r}/{cD2}{r})", f"=FDIST({cF}{r},{cD1}{r},{cD2}{r})"]
        if K == 3:
            cov = lambda a, b: f"=SUMPRODUCT({COMP}*({Ys[a]}-{mc[a]})*({Ys[b]}-{mc[b]}))/({n_}-1)"
            cells += [cov(0, 0), cov(1, 1), cov(2, 2), cov(0, 1), cov(0, 2), cov(1, 2)]
            s11, s22, s33, s12, s13, s23 = (f"{L(nb + 1 + j)}{r}" for j in range(6))
            cells += [f"=({s11}-2*{s12}+{s22})/2", f"=({s11}+{s22}+4*{s33}+2*{s12}-4*{s13}-4*{s23})/6",
                      f"=({s11}-{s22}-2*{s13}+2*{s23})/SQRT(12)"]
            c11, c22, c12 = (f"{L(nb + 7 + j)}{r}" for j in range(3))
            cW, cX, cMp, cEps, cG1, cG2, cPg = (L(nb + 10 + j) for j in range(7))
            cells += [f"=({c11}*{c22}-{c12}^2)/(({c11}+{c22})/2)^2", f"=-({n_}-1-1)*LN({cW}{r})", f"=CHIDIST({cX}{r},2)",
                      f"=({c11}+{c22})^2/(2*({c11}^2+2*{c12}^2+{c22}^2))", f"={cD1}{r}*{cEps}{r}", f"={cD2}{r}*{cEps}{r}",
                      f"=BETADIST({cG2}{r}/({cG2}{r}+{cG1}{r}*{cF}{r}),{cG2}{r}/2,{cG1}{r}/2)", f"=IF({cMp}{r}<0.05,{cPg}{r},{cP}{r})"]
        else:
            cells.append(f"={cP}{r}")
        cFinal = L(len(cells))
        cells.append(f"={cT}{r}/({cT}{r}+{cE}{r})")
        s_py = allst["rm"][code]
        cells += [s_py.get("p_final"), f"={cFinal}{r}-{L(len(cells) + 1)}{r}", s_py.get("friedman_p")]
        for j, v in enumerate(cells, 1):
            ws.cell(r, j, v)
    style(ws, 5, 4 + len(codes), 1, len(hd), fmt="0.0000")
    mark(ws, 5, 4 + len(codes), hd)
    ws.cell(6 + len(codes), 1, "判定：Mauchly p < 0.05 時採 Greenhouse-Geisser 校正之 p，否則採假設球形之 p（同 SPSS 報表慣例）。").font = F_SUB

    # ------------------------------------------------------------ 兩兩比較（三次皆參加者）
    nbf = K * (K - 1) // 2
    PH = ["指標", "比較", "n", "平均差", "差值 SD", "SE", "t", "df", "p（未校正）", "p（校正）", "CI 下限", "CI 上限", "Python p", "差異"]

    def pair_sheet(name, ttl, sub, pairs, cond, pyget, bonf):
        ws = wb.create_sheet(name)
        title(ws, ttl, sub)
        head(ws, 4, PH, [16, 14, 6, 10, 10, 10, 9, 6, 11, 11, 11, 11, 12, 9])
        r = 5
        for code in codes:
            for k, (a, b) in enumerate(pairs):
                Ya, Yb = rng(col[code][a]), rng(col[code][b])
                cd = cond(a, b)
                cells = [A.MAIN[code][0], f"{W[a]}→{W[b]}", f"=SUMPRODUCT({cd})",
                         f"=SUMPRODUCT({cd}*({Yb}-{Ya}))/C{r}",
                         f"=SQRT((SUMPRODUCT({cd}*({Yb}-{Ya})^2)-C{r}*D{r}^2)/(C{r}-1))", f"=E{r}/SQRT(C{r})",
                         f"=IFERROR(D{r}/F{r},0)", f"=C{r}-1", f"=IFERROR(TDIST(ABS(G{r}),H{r},2),1)", f"=MIN(1,I{r}*{bonf})",
                         f"=D{r}-TINV(0.05/{bonf},H{r})*F{r}", f"=D{r}+TINV(0.05/{bonf},H{r})*F{r}", pyget(code, k), f"=J{r}-M{r}"]
                for j, v in enumerate(cells, 1):
                    ws.cell(r, j, v)
                r += 1
        style(ws, 5, r - 1, 1, len(PH), fmt="0.0000")
        mark(ws, 5, r - 1, PH)

    pair_sheet("兩兩比較", f"兩兩比較：三次皆參加者配對 t 檢定（Bonferroni × {nbf}）",
               "等同 SPSS GLM Repeated Measures 的 EMMEANS COMPARE ADJ(BONFERRONI)；CI 為 Bonferroni 校正信賴區間。",
               list(combinations(range(K), 2)), lambda a, b: f"({COMP}=1)", lambda code, k: allst["rm"][code]["pairs"][k]["p_bonf"], nbf)
    pair_sheet("與前測配對", "與前測的配對 t 檢定（前測與該次皆有量測者，含只參加兩次者）",
               "n = 前測與該次皆有數值的人數；未做多重比較校正（p 校正欄＝未校正 p）。Wilcoxon 為 Python 值，見下表最右欄說明。",
               [(0, w) for w in range(1, K)], lambda a, b: f"({HAS[a]}=1)*({HAS[b]}=1)",
               lambda code, k: allst["avail"][code][k].get("p"), 1)

    # ------------------------------------------------------------ 交互作用（混合設計 ANOVA）
    if K == 3:
        ws = wb.create_sheet("交互作用")
        title(ws, "時間 × 分組 交互作用（混合設計 ANOVA，三次皆參加者）",
              "以對比分數 Z1、Z2（寬格式資料）計算：H = Σ n_g (z̄_g − z̄)(z̄_g − z̄)'，E = 組內平方和交乘積；F = [tr(H)/(2(G−1))] / [tr(E)/(2(N−G))]；GG ε 與 Mauchly 由 E 計算。")
        hd = ["指標", "分組", "N", "z̄1", "z̄2"]
        maxg = len(A.AGE_GROUPS)
        for gi in range(maxg):
            hd += [f"組{gi + 1}", f"組{gi + 1} n", f"組{gi + 1} z̄1", f"組{gi + 1} z̄2", f"組{gi + 1} E11", f"組{gi + 1} E22", f"組{gi + 1} E12"]
        tail = ["G", "tr(H)", "E11", "E22", "E12", "F", "df1", "df2", "p（假設球形）", "Mauchly W", "Mauchly p", "GG ε", "p（GG）", "判定 p", "Python 判定 p", "差異"]
        hd += tail
        head(ws, 4, hd, [14, 8, 6, 9, 9] + [9] * (len(hd) - 5), height=40)
        r = 5
        for code in codes:
            Z1, Z2 = rng(zcol[code][0]), rng(zcol[code][1])
            for by, grng, levels in (("性別", SEXR, ["M", "F"]), ("年齡層", AGER, A.AGE_GROUPS)):
                cells = [A.MAIN[code][0], by, f"=COUNTIF({COMP},1)", f"=AVERAGEIF({COMP},1,{Z1})", f"=AVERAGEIF({COMP},1,{Z2})"]
                gcells = []
                for gi in range(maxg):
                    c0 = 6 + gi * 7
                    if gi < len(levels):
                        lv = levels[gi]
                        cnd = f"({COMP}=1)*({grng}=\"{lv}\")"
                        nref, z1r, z2r = f"{L(c0 + 1)}{r}", f"{L(c0 + 2)}{r}", f"{L(c0 + 3)}{r}"
                        cells += [lv, f"=SUMPRODUCT({cnd})",
                                  f"=IF({nref}=0,0,SUMPRODUCT({cnd}*{Z1})/{nref})", f"=IF({nref}=0,0,SUMPRODUCT({cnd}*{Z2})/{nref})",
                                  f"=SUMPRODUCT({cnd}*({Z1}-{z1r})^2)", f"=SUMPRODUCT({cnd}*({Z2}-{z2r})^2)",
                                  f"=SUMPRODUCT({cnd}*({Z1}-{z1r})*({Z2}-{z2r}))"]
                        gcells.append(c0)
                    else:
                        cells += ["", 0, 0, 0, 0, 0, 0]
                t0 = len(cells) + 1
                cG, cH, cE11, cE22, cE12, cF, cD1, cD2, cP, cW, cMp, cEps, cPg, cFin = (L(t0 + j) for j in range(14))
                cells += ["=" + "+".join(f"IF({L(c0 + 1)}{r}>0,1,0)" for c0 in gcells),
                          "=" + "+".join(f"{L(c0 + 1)}{r}*(({L(c0 + 2)}{r}-D{r})^2+({L(c0 + 3)}{r}-E{r})^2)" for c0 in gcells),
                          "=" + "+".join(f"{L(c0 + 4)}{r}" for c0 in gcells),
                          "=" + "+".join(f"{L(c0 + 5)}{r}" for c0 in gcells),
                          "=" + "+".join(f"{L(c0 + 6)}{r}" for c0 in gcells),
                          f"=({cH}{r}/(2*({cG}{r}-1)))/(({cE11}{r}+{cE22}{r})/(2*(C{r}-{cG}{r})))",
                          f"=2*({cG}{r}-1)", f"=2*(C{r}-{cG}{r})", f"=FDIST({cF}{r},{cD1}{r},{cD2}{r})",
                          f"=({cE11}{r}*{cE22}{r}-{cE12}{r}^2)/(({cE11}{r}+{cE22}{r})/2)^2",
                          f"=CHIDIST(-((C{r}-{cG}{r})-1)*LN({cW}{r}),2)",
                          f"=({cE11}{r}+{cE22}{r})^2/(2*({cE11}{r}^2+2*{cE12}{r}^2+{cE22}{r}^2))",
                          f"=BETADIST({cD2}{r}*{cEps}{r}/({cD2}{r}*{cEps}{r}+{cD1}{r}*{cEps}{r}*{cF}{r}),{cD2}{r}*{cEps}{r}/2,{cD1}{r}*{cEps}{r}/2)",
                          f"=IF({cMp}{r}<0.05,{cPg}{r},{cP}{r})"]
                it = res["interaction"][code]["sex" if by == "性別" else "age"]
                cells += [it["p_final"] if it else None, f"={cFin}{r}-{L(t0 + 14)}{r}"]
                for j, v in enumerate(cells, 1):
                    ws.cell(r, j, v)
                r += 1
        style(ws, 5, r - 1, 1, len(hd), fmt="0.0000")
        mark(ws, 5, r - 1, hd)

    # ------------------------------------------------------------ 分層 ANOVA（Python 值）
    ws = wb.create_sheet("分層ANOVA")
    title(ws, "分層重複測量 ANOVA（三次皆參加者；Python 值）", "以 SPSS 語法第 5 段（SPLIT FILE）驗證。三次皆參加者少於 %d 人的分層不分析。" % A.MIN_N)
    hd = ["分層", "人數", "指標"] + [f"{w} 平均" for w in W] + ["F", "df1", "df2", "GG 校正", "判定 p", "偏 η²", "Friedman p"]
    head(ws, 4, hd, [14, 8, 16] + [10] * (len(hd) - 3))
    r = 5
    for key, st in res["strata"].items():
        if key == "all" or "|" in key or "rm" not in st:
            continue
        for code in codes:
            s = st["rm"][code]
            vals = [st["label"], st["n_complete"], A.MAIN[code][0], *s["means"], s["F"],
                    s["df1_gg"] if s["use_gg"] else s["df1"], s["df2_gg"] if s["use_gg"] else s["df2"],
                    "是" if s["use_gg"] else "否", s["p_final"], s["pes"], s["friedman_p"]]
            for j, v in enumerate(vals, 1):
                ws.cell(r, j, v)
            r += 1
    style(ws, 5, max(r - 1, 5), 1, len(hd), font=F_PY, fmt="0.0000")

    # ------------------------------------------------------------ Cochran's Q / McNemar
    ws = wb.create_sheet("CochranQ_McNemar")
    title(ws, "風險分類變化",
          "Cochran's Q（三次皆參加者）= (k−1)[kΣCj² − T²] / (kT − ΣRi²)；McNemar 精確 p = min(1, 2×BINOMDIST(min(b,c), b+c, 0.5, TRUE))。"
          "三次皆參加者的兩兩比較採 Bonferroni × %d；與前測配對（兩次皆有量測者）不校正。" % nbf)
    hd = ["風險分類", "n"] + [f"{w} 人數" for w in W] + ["T", "ΣRi²", "Q", "df", "p", "Python p", "差異"]
    for a, b in combinations(range(K), 2):
        hd += [f"{W[a]}→{W[b]} 改善", f"{W[a]}→{W[b]} 惡化", f"{W[a]}→{W[b]} p（Bonferroni）", "Python p", "差異"]
    for w in range(1, K):
        hd += [f"配對 {W[0]}→{W[w]} n", "改善", "惡化", "McNemar p", "Python p", "差異"]
    head(ws, 4, hd, [28, 6] + [10] * (len(hd) - 2), height=44)
    for i, bc in enumerate(A.BINARY):
        r = 5 + i
        Fs = [rng(cc) for cc in fcol[bc]]
        it = allst["binary"][bc]
        cC = [f"{L(3 + j)}{r}" for j in range(K)]
        cT, cR, cQ = L(3 + K), L(4 + K), L(5 + K)
        cells = [A.BINARY[bc][0], f"=COUNTIF({COMP},1)"] + [f"=SUMIF({COMP},1,{f})" for f in Fs]
        cells += ["=" + "+".join(cC), f"=SUMPRODUCT({COMP}*(" + "+".join(Fs) + ")^2)",
                  f"=IF({K}*{cT}{r}-{cR}{r}=0,0,({K}-1)*({K}*SUMPRODUCT(({cC[0]}:{cC[-1]})^2)-{cT}{r}^2)/({K}*{cT}{r}-{cR}{r}))",
                  K - 1, f"=CHIDIST({cQ}{r},{K - 1})", it.get("p"), f"={L(7 + K)}{r}-{L(8 + K)}{r}"]
        mcn = lambda bb, cc, mult: f"=IF({bb}+{cc}=0,1,MIN(1,{mult}*MIN(1,2*BINOMDIST(MIN({bb},{cc}),{bb}+{cc},0.5,TRUE))))"
        for k, (a, b) in enumerate(combinations(range(K), 2)):
            c0 = len(cells) + 1
            bb, cc = f"{L(c0)}{r}", f"{L(c0 + 1)}{r}"
            cells += [f"=SUMPRODUCT({COMP}*({Fs[a]}=1)*({Fs[b]}=0))", f"=SUMPRODUCT({COMP}*({Fs[a]}=0)*({Fs[b]}=1))",
                      mcn(bb, cc, nbf), it["pairs"][k]["p_bonf"], f"={L(c0 + 2)}{r}-{L(c0 + 3)}{r}"]
        for w in range(1, K):
            c0 = len(cells) + 1
            both = f"({HAS[0]}=1)*({HAS[w]}=1)"
            bb, cc = f"{L(c0 + 1)}{r}", f"{L(c0 + 2)}{r}"
            av = it["avail"][w - 1]
            cells += [f"=SUMPRODUCT({both})", f"=SUMPRODUCT({both}*({Fs[0]}=1)*({Fs[w]}=0))", f"=SUMPRODUCT({both}*({Fs[0]}=0)*({Fs[w]}=1))",
                      mcn(bb, cc, 1), av.get("p"), f"={L(c0 + 3)}{r}-{L(c0 + 4)}{r}"]
        for j, v in enumerate(cells, 1):
            ws.cell(r, j, v)
    style(ws, 5, 4 + len(A.BINARY), 1, len(hd), fmt="0.0000")
    mark(ws, 5, 4 + len(A.BINARY), hd)

    # ------------------------------------------------------------ 卡方檢定
    ws = wb.create_sheet("卡方檢定")
    title(ws, "各次量測：風險分類 × 性別／年齡層（Pearson 卡方）",
          "期望次數 = 列合計 × 欄合計 ÷ 總數；χ² = Σ(O−E)²/E；p = CHIDIST(χ², df)。期望次數 < 5 的格子超過 20% 時參考 Fisher（Python）。")
    ws.column_dimensions["A"].width = 36
    for j in range(2, 12):
        ws.column_dimensions[L(j)].width = 12
    r = 4
    for x in res["chisq"]:
        w, bc = x["wave"], x["outcome"]
        grp = SEXR if x["by"] == "性別" else AGER
        keys = ["M", "F"] if x["by"] == "性別" else x["rows"]
        Fw = rng(fcol[bc][w - 1])
        ws.cell(r, 1, f"{W[w - 1]}｜{x['outcome_name']} × {x['by']}").font = F_BOLD
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

    # ------------------------------------------------------------ 流失分析
    ws = wb.create_sheet("流失分析")
    title(ws, "前測參加者：三次皆參加 vs 未完成（前測值）", "Welch t：p = BETADIST(df/(df+t²), df/2, 0.5)，保留小數自由度。")
    hd = ["變項", "完成 n", "完成 平均", "完成 SD", "未完成 n", "未完成 平均", "未完成 SD", "Welch t", "df", "p", "Python p", "差異"]
    head(ws, 4, hd, [16, 8, 11, 10, 9, 11, 10, 9, 9, 10, 10, 9])
    r = 5
    for v in res["attrition"]["vars"]:
        X = rng(3) if v["code"] == "AGE" else rng(col[v["code"]][0])
        c1, c0 = f"({HAS[0]}=1)*({COMP}=1)", f"({HAS[0]}=1)*({COMP}=0)"
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
    mark(ws, 5, r - 1, hd)

    for wsx in wb.worksheets:
        wsx.sheet_view.showGridLines = wsx.title != "說明"
    out_path = Path(out_path)
    wb.save(out_path)
    write_spss(D, res, out_path, ids)
    return out_path


# ---------------------------------------------------------------- SPSS
def write_spss(D, res, xlsx_path, ids):
    import pandas as pd
    import pyreadstat

    K, people, long = D["K"], D["people"], D["long"]
    W = D["names"]
    ages = A.AGE_GROUPS
    idmap = {pid: i + 1 for i, pid in enumerate(ids)}
    wide = pd.DataFrame({"ID": [idmap[p] for p in ids], "SEX": [1 if people.loc[p, "SEX"] == "M" else 2 for p in ids],
                         "AGE0": [int(people.loc[p, "AGE0"]) for p in ids],
                         "AGEGRP": [ages.index(people.loc[p, "AGEGRP"]) + 1 for p in ids],
                         "COMPLETE": [int(people.loc[p, "COMPLETE"]) for p in ids]})
    labels = {"ID": "序號", "SEX": "性別", "AGE0": "首次量測年齡", "AGEGRP": "年齡層", "COMPLETE": "三次皆參加"}
    for w in range(1, K + 1):
        wide[f"HAS{w}"] = [int(people.loc[p, f"HAS{w}"]) for p in ids]
        labels[f"HAS{w}"] = f"有{W[w - 1]}"
    for code, meta in A.MAIN.items():
        for w in range(1, K + 1):
            bw = D["by_wave"][w]
            wide[f"{code}_T{w}"] = [float(bw.loc[p, code]) if p in bw.index else None for p in ids]
            labels[f"{code}_T{w}"] = f"{meta[0]}（{meta[1]}）{W[w - 1]}"
    for bc, (bname, _) in A.BINARY.items():
        for w in range(1, K + 1):
            bw = D["by_wave"][w]
            wide[f"{bc}_T{w}"] = [float(bw.loc[p, bc]) if p in bw.index else None for p in ids]
            labels[f"{bc}_T{w}"] = f"{bname} {W[w - 1]}"
    age_lab = {i + 1: (f"{g[1:]}歲(含)以下" if g.startswith("≤") else f"{g[1:]}歲以上" if g.startswith("≥") else f"{g}歲") for i, g in enumerate(ages)}
    vlab = {"SEX": {1: "男性", 2: "女性"}, "AGEGRP": age_lab, "COMPLETE": {0: "否", 1: "是"}}
    for bc in A.BINARY:
        for w in range(1, K + 1):
            vlab[f"{bc}_T{w}"] = {0: "否", 1: "是"}
    stem = str(xlsx_path.with_suffix(""))
    pyreadstat.write_sav(wide, f"{stem}_寬格式.sav", column_labels=labels, variable_value_labels=vlab)
    lg = long[long.CUSTOMERID.isin(ids)]
    lgo = pd.DataFrame({"ID": lg.CUSTOMERID.map(idmap).values, "TIME": lg.WAVE.values, "SEX": lg.SEX.map({"M": 1, "F": 2}).values,
                        "AGEGRP": lg.AGEGRP.map(lambda g: ages.index(g) + 1).values, "COMPLETE": lg.CUSTOMERID.map(people.COMPLETE).values})
    llab = {"ID": "序號", "TIME": "量測次別", "SEX": "性別", "AGEGRP": "年齡層", "COMPLETE": "三次皆參加"}
    for code, meta in A.MAIN.items():
        lgo[code] = lg[code].values
        llab[code] = f"{meta[0]}（{meta[1]}）"
    for bc, (bname, _) in A.BINARY.items():
        lgo[bc] = lg[bc].values
        llab[bc] = bname
    lvl = {k: v for k, v in vlab.items() if k in ("SEX", "AGEGRP", "COMPLETE")}
    lvl["TIME"] = {w: W[w - 1] for w in range(1, K + 1)}
    for bc in A.BINARY:
        lvl[bc] = {0: "否", 1: "是"}
    pyreadstat.write_sav(lgo.sort_values(["ID", "TIME"]), f"{stem}_長格式.sav", column_labels=llab, variable_value_labels=lvl)
    write_sps(res, Path(f"{stem}_寬格式.sav").name, Path(f"{stem}_長格式.sav").name, Path(f"{stem}.sps"), K, W)


def write_sps(res, wide_name, long_name, path, K, W):
    main = list(A.MAIN)
    T = lambda c: " ".join(f"{c}_T{w}" for w in range(1, K + 1))
    pre_pairs = [(1, w) for w in range(2, K + 1)]
    all_pairs = list(combinations(range(1, K + 1), 2))
    left = lambda c, prs: " ".join(f"{c}_T{a}" for a, b in prs)
    right = lambda c, prs: " ".join(f"{c}_T{b}" for a, b in prs)
    flags = list(A.BINARY)
    glm = lambda c, extra="": (f"GLM {T(c)}{extra}\n  /WSFACTOR=time {K} Polynomial\n  /METHOD=SSTYPE(3)\n"
                               f"  /EMMEANS=TABLES(time) COMPARE ADJ(BONFERRONI)\n  /PRINT=DESCRIPTIVE ETASQ\n  /CRITERIA=ALPHA(.05)\n  /WSDESIGN=time.")
    out = [f"""* =====================================================================.
* {res['info']['title']}（{res['info']['workplace']}）— SPSS 驗證語法.
* 量測次別：{'、'.join(f'T{i + 1}={w}' for i, w in enumerate(W))}.
* 使用前請以 CD 指令切換到 .sav 所在資料夾，例如：CD 'C:\\報告\\{res['info']['workplace']}'.
* 需要模組：GLM 重複測量需 Advanced Statistics；/METHOD=EXACT 需 Exact Tests.
* =====================================================================.
SET UNICODE=ON.

* ---------- 1. 各次描述統計與 95% 信賴區間（全部參加者）.
GET FILE='{wide_name}'.
DATASET NAME wide WINDOW=FRONT.
EXAMINE VARIABLES={' '.join(T(c) for c in main)}
  /PLOT NONE /STATISTICS DESCRIPTIVES /CINTERVAL 95 /MISSING PAIRWISE /NOTOTAL.

* ---------- 2. 三次皆參加者：重複測量 ANOVA（GLM 自動排除缺測者）.
* 報表：Mauchly 球形檢定、Greenhouse-Geisser、偏 η²、Bonferroni 兩兩比較；PROFILE 為趨勢圖.
"""]
    out += [glm(c) + "" for c in main]
    out.append("\n* ---------- 3. Friedman 檢定（無母數參考）.")
    out.append("NPAR TESTS\n" + "\n".join(f"  /FRIEDMAN={T(c)}" for c in main) + "\n  /MISSING ANALYSIS.")
    out.append(f"""
* ---------- 4. 與前測配對（前測與該次皆有量測者，含只參加兩次者）.
T-TEST PAIRS={' '.join(left(c, pre_pairs) for c in main)}
  WITH {' '.join(right(c, pre_pairs) for c in main)} (PAIRED)
  /CRITERIA=CI(.9500) /MISSING=ANALYSIS.
NPAR TESTS /WILCOXON={' '.join(left(c, pre_pairs) for c in main)}
  WITH {' '.join(right(c, pre_pairs) for c in main)} (PAIRED) /MISSING ANALYSIS.

* ---------- 5. 分層：性別、年齡層各自的重複測量 ANOVA.
SORT CASES BY SEX.
SPLIT FILE LAYERED BY SEX.""")
    out += [f"GLM {T(c)} /WSFACTOR=time {K} Polynomial /METHOD=SSTYPE(3) /PRINT=DESCRIPTIVE ETASQ /WSDESIGN=time." for c in main]
    out.append("SPLIT FILE OFF.\nSORT CASES BY AGEGRP.\nSPLIT FILE LAYERED BY AGEGRP.")
    out += [f"GLM {T(c)} /WSFACTOR=time {K} Polynomial /METHOD=SSTYPE(3) /PRINT=DESCRIPTIVE ETASQ /WSDESIGN=time." for c in main]
    out.append("SPLIT FILE OFF.")
    out.append("\n* ---------- 6. 時間 × 性別、時間 × 年齡層 交互作用（混合設計 ANOVA）；PLOT 為分層趨勢圖.")
    for c in main:
        for g in ("SEX", "AGEGRP"):
            out.append(f"GLM {T(c)} BY {g}\n  /WSFACTOR=time {K} Polynomial /METHOD=SSTYPE(3)\n  /PLOT=PROFILE(time*{g})\n  /PRINT=DESCRIPTIVE ETASQ /WSDESIGN=time /DESIGN={g}.")
    out.append(f"""
* ---------- 7. 風險分類變化.
* 7a 三次皆參加者：Cochran's Q 與兩兩 McNemar（p 請自行 × {len(all_pairs)} 做 Bonferroni）.
TEMPORARY.
SELECT IF COMPLETE = 1.
NPAR TESTS
{chr(10).join(f"  /COCHRAN={T(f)}" for f in flags)}
  /MCNEMAR={' '.join(left(f, all_pairs) for f in flags)} WITH {' '.join(right(f, all_pairs) for f in flags)} (PAIRED)
  /MISSING ANALYSIS.
* 7b 與前測配對（前測與該次皆有量測者）.
NPAR TESTS
  /MCNEMAR={' '.join(left(f, pre_pairs) for f in flags)} WITH {' '.join(right(f, pre_pairs) for f in flags)} (PAIRED)
  /MISSING ANALYSIS.

* ---------- 8. 代表性：前測參加者中，三次皆參加 vs 未完成（前測值）.
TEMPORARY.
SELECT IF HAS1 = 1.
T-TEST GROUPS=COMPLETE(1 0) /VARIABLES=AGE0 {' '.join(f'{c}_T1' for c in main)} /CRITERIA=CI(.95).
TEMPORARY.
SELECT IF HAS1 = 1.
CROSSTABS /TABLES=SEX BY COMPLETE /STATISTICS=CHISQ /CELLS=COUNT EXPECTED ROW.

* ---------- 9. 各次量測：風險分類 × 性別／年齡層 卡方與 Fisher 精確檢定（長格式）.
GET FILE='{long_name}'.
DATASET NAME long WINDOW=FRONT.
SORT CASES BY TIME.
SPLIT FILE LAYERED BY TIME.
CROSSTABS /TABLES={' '.join(flags)} BY SEX AGEGRP
  /STATISTICS=CHISQ /CELLS=COUNT EXPECTED ROW /METHOD=EXACT TIMER(5).
SPLIT FILE OFF.
""")
    path.write_text("\n".join(out), encoding="utf-8")
