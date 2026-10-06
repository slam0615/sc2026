"""TANITA MC-780 (GMON 匯出) 前後測身體組成 — 總體統計分析。

用法：
    python analyze.py <GMON匯出.xls> [輸出資料夾]

產出：
    results.json   供 HTML / PDF 報告使用（僅含彙總統計，不含個人資料）
    其餘 Excel 驗算檔由 build_excel.py 產生（會讀取本模組的 load_data / run）

統計設定盡量對齊 SPSS 預設：
    配對 t 檢定（雙尾）、Wilcoxon 符號等級檢定（漸近、無連續性校正、捨棄差值為 0 者）、
    Mann-Whitney U（漸近、無連續性校正）、Welch t、單因子 ANOVA、Kruskal-Wallis、
    McNemar（精確二項）、Pearson 卡方 + Fisher 精確檢定（2×k 以 Freeman-Halton 完整列舉）。
"""
from __future__ import annotations

import json
import math
import sys
import warnings
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

warnings.filterwarnings("ignore")

MIN_N = 10         # 分層人數低於此值不呈現（避免小群體可推測個人）
ALPHA = 0.05
KJ_PER_KCAL = 4.184

# ---------------------------------------------------------------- 欄位定義
# code: (中文名稱, 單位, 小數位, 期望方向 -1=下降有利 / +1=上升有利 / 0=不判定, 說明)
MAIN = {
    "WEIGHT":     ("體重", "kg", 1, -1, "含衣重扣除 0.2 kg"),
    "BMI":        ("身體質量指數 BMI", "kg/m²", 1, -1, "體重(kg) ÷ 身高(m)²"),
    "FATP":       ("體脂肪率", "%", 1, -1, "脂肪量占體重百分比"),
    "FATM":       ("脂肪量", "kg", 1, -1, ""),
    "FFM":        ("除脂肪量", "kg", 1, +1, "體重扣除脂肪量"),
    "PMM":        ("肌肉量", "kg", 1, +1, "推定肌肉量（含骨骼肌、平滑肌及其水分）"),
    "BONEM":      ("推定骨量", "kg", 1, 0, "骨骼中礦物質推定值"),
    "TBW":        ("體水分量", "kg", 1, 0, ""),
    "ICW":        ("細胞內液", "kg", 1, 0, ""),
    "ECW":        ("細胞外液", "kg", 1, 0, ""),
    "ECWR":       ("細胞外液比 (ECW/TBW)", "%", 1, 0, "衍生指標：細胞外液 ÷ 體水分量 × 100"),
    "BMR":        ("基礎代謝量", "kcal/日", 0, 0, "原始資料為 kJ，已 ÷ 4.184 換算為 kcal"),
    "METAAGE":    ("體內年齡", "歲", 0, -1, "TANITA 依基礎代謝推估之年齡"),
    "VFATL":      ("內臟脂肪等級", "等級", 0, -1, "TANITA 原廠等級（1–59）"),
    "PHASEANGLE": ("相位角", "°", 2, +1, "50 kHz 全身相位角，反映細胞完整性"),
    "IMP":        ("全身阻抗", "Ω", 1, 0, "全身生物電阻抗值"),
}
SEGMENTS = {"RL": "右腳", "LL": "左腳", "RA": "右手", "LA": "左手", "TR": "軀幹"}
SEG_METRICS = {
    "FATP": ("體脂肪率", "%", 1, -1),
    "FATM": ("脂肪量", "kg", 1, -1),
    "FFM":  ("除脂肪量", "kg", 1, +1),
    "PMM":  ("肌肉量", "kg", 1, +1),
    "IMP":  ("阻抗", "Ω", 1, 0),
}
SEG = {}
for s, sname in SEGMENTS.items():
    for m, (mname, unit, dec, good) in SEG_METRICS.items():
        if s == "TR" and m == "IMP":
            continue  # MC-780 不輸出軀幹阻抗
        SEG[f"{s}{m}"] = (f"{sname}{mname}", unit, dec, good, "")

OTHER_FIELDS = {  # 僅作欄位對照、不進入統計
    "CUSTOMERID": ("受測者編號", "", "已於報告中移除"),
    "LASTNAME": ("姓", "", "空白"), "FIRSTNAME": ("名", "", "空白"),
    "SEX": ("性別", "M/F", "M=男、F=女"),
    "GROUP1": ("群組一（職場）", "", ""), "GROUP2": ("群組二", "", "空白"),
    "PATNR": ("系統序號", "", "已於報告中移除"),
    "DATETIME": ("測量日期時間", "", ""), "MODEL": ("機型", "", "MC-780"),
    "FLAG": ("資料旗標", "", "系統內部碼"), "CONDITION": ("測量狀況", "", "空白"),
    "AGE": ("年齡", "歲", ""), "BTYP": ("體型模式", "", "0=標準、1=運動員"),
    "HEIGHT": ("身高", "cm", ""), "CLOTHES": ("衣重", "kg", ""),
    "DCI": ("每日建議攝取熱量", "kcal", "空白（未設定活動量）"),
    "PAL": ("身體活動等級", "", "空白"),
    "BLOB_DATA": ("原始量測二進位資料", "", "不使用"),
    "PHYSRATE": ("體型判定代碼", "", "TANITA 內部編碼，匯出檔無對照表，不納入統計"),
}

AGE_BINS = [(0, 29, "<30"), (30, 39, "30-39"), (40, 200, "≥40")]
SEX_LABEL = {"M": "男性", "F": "女性"}


def age_group(a):
    for lo, hi, lab in AGE_BINS:
        if lo <= a <= hi:
            return lab
    return None


def bmi_cat(b):
    if b < 18.5:
        return "過輕"
    if b < 24:
        return "正常"
    if b < 27:
        return "過重"
    return "肥胖"


BMI_CATS = ["過輕", "正常", "過重", "肥胖"]
VFAT_CATS = ["標準 (1–9)", "偏高 (10–14)", "過高 (≥15)"]


def vfat_cat(v):
    return VFAT_CATS[0] if v < 10 else VFAT_CATS[1] if v < 15 else VFAT_CATS[2]


def fat_over(sex, p):  # 國健署：男性 ≥25%、女性 ≥30% 屬肥胖
    return int(p >= (25 if sex == "M" else 30))


BINARY = {
    "ow":   ("過重或肥胖 (BMI ≥ 24)", lambda r: int(r["BMI"] >= 24)),
    "ob":   ("肥胖 (BMI ≥ 27)", lambda r: int(r["BMI"] >= 27)),
    "fat":  ("體脂肪率超標 (男 ≥25%、女 ≥30%)", lambda r: fat_over(r["SEX"], r["FATP"])),
    "vfat": ("內臟脂肪偏高 (等級 ≥ 10)", lambda r: int(r["VFATL"] >= 10)),
}


# ---------------------------------------------------------------- 資料
def load_data(path):
    raw = pd.read_excel(path)
    d = raw.copy()
    d["DATETIME"] = pd.to_datetime(d["DATETIME"])
    d["DATE"] = d["DATETIME"].dt.normalize()
    d["BMR"] = d["BMR"] / KJ_PER_KCAL
    d["ECWR"] = d["ECW"] / d["TBW"] * 100
    for code, meta in {**MAIN, **SEG}.items():
        d[code] = d[code].astype(float).round(meta[2] if code != "ECWR" else 2)
    dates = sorted(d["DATE"].unique())
    if len(dates) < 2:
        raise SystemExit("資料只有一個測量日期，無法進行前後測比較")
    log = []
    pre_date, post_date = dates[0], dates[-1]
    if len(dates) > 2:
        log.append(f"共有 {len(dates)} 個測量日期，以最早日期為前測、最晚日期為後測，其餘日期不納入")
    d["PHASE"] = np.where(d["DATE"] == pre_date, "pre", np.where(d["DATE"] == post_date, "post", None))
    d = d[d["PHASE"].notna()]
    # 同一人同一時期多次量測：保留最後一次
    dup = d.duplicated(["CUSTOMERID", "PHASE"], keep=False)
    if dup.any():
        n_dup = d[dup].groupby(["CUSTOMERID", "PHASE"]).ngroups
        log.append(f"{n_dup} 人次於同一時期重複量測，保留該時期最後一筆")
    d = d.sort_values("DATETIME").drop_duplicates(["CUSTOMERID", "PHASE"], keep="last")
    pre = d[d.PHASE == "pre"].set_index("CUSTOMERID")
    post = d[d.PHASE == "post"].set_index("CUSTOMERID")
    ids = pre.index.intersection(post.index).sort_values()
    # 基線年齡＝前測年齡（只有後測者用後測年齡）
    base_age = pd.concat([pre["AGE"], post["AGE"][~post.index.isin(pre.index)]])
    d["AGEGRP"] = d["CUSTOMERID"].map(base_age).map(age_group)
    pre = d[d.PHASE == "pre"].set_index("CUSTOMERID")
    post = d[d.PHASE == "post"].set_index("CUSTOMERID")
    info = dict(
        workplace=str(raw["GROUP1"].dropna().iloc[0]) if raw["GROUP1"].notna().any() else "",
        model=str(raw["MODEL"].dropna().iloc[0]),
        pre_date=str(pd.Timestamp(pre_date).date()), post_date=str(pd.Timestamp(post_date).date()),
        interval_days=int((pd.Timestamp(post_date) - pd.Timestamp(pre_date)).days),
        n_records=int(len(raw)), n_people=int(raw["CUSTOMERID"].nunique()),
        n_pre=int(len(pre)), n_post=int(len(post)), n_paired=int(len(ids)),
        n_pre_only=int(len(pre.index.difference(post.index))),
        n_post_only=int(len(post.index.difference(pre.index))),
        cleaning_log=log,
    )
    return dict(raw=raw, all=d, pre=pre, post=post, ids=ids, info=info)


# ---------------------------------------------------------------- 統計工具
def r(x, k=4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), k)


def paired_stats(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    diff = b - a
    n = len(diff)
    out = dict(n=n)
    if n < 2:
        return out
    md, sd = diff.mean(), diff.std(ddof=1)
    se = sd / math.sqrt(n)
    tcrit = stats.t.ppf(0.975, n - 1)
    out.update(pre_mean=a.mean(), pre_sd=a.std(ddof=1), post_mean=b.mean(), post_sd=b.std(ddof=1),
               diff_mean=md, diff_sd=sd, se=se, ci_lo=md - tcrit * se, ci_hi=md + tcrit * se,
               pct=md / a.mean() * 100 if a.mean() else None,
               n_up=int((diff > 0).sum()), n_down=int((diff < 0).sum()), n_same=int((diff == 0).sum()))
    if sd > 0:
        t = md / se
        out.update(t=t, df=n - 1, p_t=2 * stats.t.sf(abs(t), n - 1), dz=md / sd)
    else:
        out.update(t=None, df=n - 1, p_t=1.0, dz=0.0)
    nz = diff[diff != 0]
    if len(nz) >= 1 and np.ptp(nz) >= 0:
        try:
            w = stats.wilcoxon(a, b, zero_method="wilcox", correction=False, method="approx")
            out["p_w"] = float(w.pvalue)
            out["z_w"] = float(getattr(w, "zstatistic", np.nan)) if hasattr(w, "zstatistic") else None
        except ValueError:
            out["p_w"] = 1.0
    else:
        out["p_w"] = 1.0
    out["p_sw"] = float(stats.shapiro(diff).pvalue) if n >= 3 and sd > 0 else None
    # 判定依據：差值常態（Shapiro-Wilk p ≥ .05）用配對 t，否則用 Wilcoxon
    normal = out["p_sw"] is None or out["p_sw"] >= ALPHA
    out["test"] = "配對t" if normal else "Wilcoxon"
    out["p"] = out["p_t"] if normal else out["p_w"]
    return {k: (r(v, 6) if isinstance(v, (float, np.floating)) else v) for k, v in out.items()}


def holm(ps):
    idx = [i for i, p in enumerate(ps) if p is not None]
    adj = [None] * len(ps)
    if idx:
        res = multipletests([ps[i] for i in idx], method="holm")[1]
        for i, v in zip(idx, res):
            adj[i] = r(v, 6)
    return adj


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * stats.binom.cdf(min(b, c), n, 0.5))


def bowker(tab):
    tab = np.asarray(tab, float)
    k = tab.shape[0]
    chi, df = 0.0, 0
    for i in range(k):
        for j in range(i + 1, k):
            s = tab[i, j] + tab[j, i]
            if s > 0:
                chi += (tab[i, j] - tab[j, i]) ** 2 / s
                df += 1
    return chi, df, (stats.chi2.sf(chi, df) if df else 1.0)


def fisher_2xk(tab):
    """Fisher-Freeman-Halton 精確檢定（2×k，完整列舉）。"""
    tab = np.asarray(tab, int)
    if tab.shape[0] != 2:
        tab = tab.T
    r1 = tab[0].sum()
    cols = tab.sum(0)
    N = cols.sum()

    def logp(row1):
        return (sum(math.lgamma(c + 1) - math.lgamma(x + 1) - math.lgamma(c - x + 1) for x, c in zip(row1, cols))
                - (math.lgamma(N + 1) - math.lgamma(r1 + 1) - math.lgamma(N - r1 + 1)))

    p_obs = logp(tab[0])
    total = 0.0
    k = len(cols)

    def rec(i, remaining, acc):
        nonlocal total
        if i == k - 1:
            if 0 <= remaining <= cols[i]:
                lp = logp(acc + [remaining])
                if lp <= p_obs + 1e-7:
                    total += math.exp(lp)
            return
        for x in range(0, min(cols[i], remaining) + 1):
            rec(i + 1, remaining - x, acc + [x])

    rec(0, r1, [])
    return min(1.0, total)


def chisq_table(tab, row_labels, col_labels):
    tab = np.asarray(tab, float)
    keep_r, keep_c = tab.sum(1) > 0, tab.sum(0) > 0
    t2 = tab[keep_r][:, keep_c]
    res = dict(rows=row_labels, cols=col_labels, observed=tab.astype(int).tolist(), n=int(tab.sum()))
    if t2.shape[0] < 2 or t2.shape[1] < 2:
        res.update(chi2=None, df=None, p=None, p_fisher=None, min_expected=None, n_exp_lt5=None)
        return res
    chi, p, df, exp = stats.chi2_contingency(t2, correction=False)
    res.update(chi2=r(chi), df=int(df), p=r(p, 6), min_expected=r(exp.min(), 2),
               n_exp_lt5=int((exp < 5).sum()), n_cells=int(exp.size))
    if t2.shape == (2, 2):
        res["p_fisher"] = r(stats.fisher_exact(t2)[1], 6)
    elif 2 in t2.shape:
        res["p_fisher"] = r(fisher_2xk(t2), 6)
    else:
        res["p_fisher"] = None
    return res


# ---------------------------------------------------------------- 分析
def strata_keys(pre):
    keys = [("all", "全體", None, None)]
    for s in ["M", "F"]:
        keys.append((f"sex:{s}", SEX_LABEL[s], s, None))
    for _, _, g in AGE_BINS:
        keys.append((f"age:{g}", f"{g} 歲", None, g))
    for s in ["M", "F"]:
        for _, _, g in AGE_BINS:
            keys.append((f"sex:{s}|age:{g}", f"{SEX_LABEL[s]}・{g} 歲", s, g))
    return keys


def subset_ids(df, ids, sex, grp):
    m = df.loc[ids]
    if sex:
        m = m[m.SEX == sex]
    if grp:
        m = m[m.AGEGRP == grp]
    return m.index


def run(path):
    D = load_data(path)
    pre, post, ids, info = D["pre"], D["post"], D["ids"], D["info"]
    out = dict(info=info, fields={}, strata={}, compare={}, baseline_chisq=[], attrition={}, segments={})
    out["fields"]["main"] = [dict(code=k, name=v[0], unit=v[1], dec=v[2], good=v[3], note=v[4]) for k, v in MAIN.items()]
    out["fields"]["seg"] = [dict(code=k, name=v[0], unit=v[1], dec=v[2], good=v[3]) for k, v in SEG.items()]
    out["fields"]["binary"] = [dict(code=k, name=v[0]) for k, v in BINARY.items()]
    out["min_n"] = MIN_N

    # 基線（前測）組成
    comp = pd.crosstab(pre.SEX.map(SEX_LABEL), pre.AGEGRP)
    out["composition"] = dict(
        pre={"sex": pre.SEX.map(SEX_LABEL).value_counts().to_dict(), "age": pre.AGEGRP.value_counts().to_dict()},
        paired={"sex": pre.loc[ids].SEX.map(SEX_LABEL).value_counts().to_dict(),
                "age": pre.loc[ids].AGEGRP.value_counts().to_dict()},
        age_mean=r(pre.loc[ids].AGE.mean(), 1), age_sd=r(pre.loc[ids].AGE.std(), 1),
        age_min=int(pre.loc[ids].AGE.min()), age_max=int(pre.loc[ids].AGE.max()),
    )

    for key, label, sex, grp in strata_keys(pre):
        sid = subset_ids(pre, ids, sex, grp)
        n = len(sid)
        st = dict(label=label, n=n, suppressed=n < MIN_N)
        if n >= MIN_N:
            a, b = pre.loc[sid], post.loc[sid]
            mains = {c: paired_stats(a[c], b[c]) for c in MAIN}
            adj = holm([mains[c].get("p") for c in MAIN])
            for c, h in zip(MAIN, adj):
                mains[c]["p_holm"] = h
            st["main"] = mains
            st["seg"] = {c: paired_stats(a[c], b[c]) for c in SEG}
            # 分級變化
            cats = {}
            for bc, (bname, fn) in BINARY.items():
                x0 = a.apply(fn, axis=1).values
                x1 = b.apply(fn, axis=1).values
                bb = int(((x0 == 1) & (x1 == 0)).sum())
                cc = int(((x0 == 0) & (x1 == 1)).sum())
                cats[bc] = dict(n=n, pre=int(x0.sum()), post=int(x1.sum()), both=int(((x0 == 1) & (x1 == 1)).sum()),
                                neither=int(((x0 == 0) & (x1 == 0)).sum()), improved=bb, worsened=cc,
                                p=r(mcnemar_exact(bb, cc), 6))
            st["binary"] = cats
            c0, c1 = a.BMI.map(bmi_cat), b.BMI.map(bmi_cat)
            tab = pd.crosstab(c0, c1).reindex(index=BMI_CATS, columns=BMI_CATS, fill_value=0)
            chi, df, p = bowker(tab.values)
            v0, v1 = a.VFATL.map(vfat_cat), b.VFATL.map(vfat_cat)
            tabv = pd.crosstab(v0, v1).reindex(index=VFAT_CATS, columns=VFAT_CATS, fill_value=0)
            chiv, dfv, pv = bowker(tabv.values)
            st["bmi_cat"] = dict(cats=BMI_CATS, pre=[int((c0 == k).sum()) for k in BMI_CATS],
                                 post=[int((c1 == k).sum()) for k in BMI_CATS], table=tab.values.tolist(),
                                 bowker=r(chi), df=df, p=r(p, 6))
            st["vfat_cat"] = dict(cats=VFAT_CATS, pre=[int((v0 == k).sum()) for k in VFAT_CATS],
                                  post=[int((v1 == k).sum()) for k in VFAT_CATS], table=tabv.values.tolist(),
                                  bowker=r(chiv), df=dfv, p=r(pv, 6))
        out["strata"][key] = st

    # 組間比較變化量（性別、年齡層）
    diff = post.loc[ids, list(MAIN)] - pre.loc[ids, list(MAIN)]
    sexv, agev = pre.loc[ids].SEX, pre.loc[ids].AGEGRP
    for c in MAIN:
        dm, df_ = diff.loc[sexv == "M", c], diff.loc[sexv == "F", c]
        wt = stats.ttest_ind(dm, df_, equal_var=False)
        mw = stats.mannwhitneyu(dm, df_, alternative="two-sided", use_continuity=False, method="asymptotic")
        groups = [diff.loc[agev == g, c] for _, _, g in AGE_BINS if (agev == g).sum() > 0]
        an = stats.f_oneway(*groups)
        kw = stats.kruskal(*groups)
        out["compare"][c] = dict(sex_welch_t=r(wt.statistic), sex_welch_df=r(wt.df, 3), sex_p_welch=r(wt.pvalue, 6),
                                 sex_p_mw=r(mw.pvalue, 6), age_F=r(an.statistic), age_p_anova=r(an.pvalue, 6),
                                 age_H=r(kw.statistic), age_p_kw=r(kw.pvalue, 6))

    # 基線卡方（前測全部受測者）
    base = pre.copy()
    for bc, (bname, fn) in BINARY.items():
        base[bc] = base.apply(fn, axis=1)
        for var, labels, vals in [("SEX", ["男性", "女性"], ["M", "F"]),
                                  ("AGEGRP", [g for *_, g in AGE_BINS], [g for *_, g in AGE_BINS])]:
            tab = [[int(((base[var] == v) & (base[bc] == 1)).sum()), int(((base[var] == v) & (base[bc] == 0)).sum())]
                   for v in vals]
            res = chisq_table(tab, labels, ["是", "否"])
            res.update(outcome=bc, outcome_name=bname, by="性別" if var == "SEX" else "年齡層")
            out["baseline_chisq"].append(res)

    # 流失分析：完成前後測者 vs 僅前測者（基線比較）
    comp_flag = base.index.isin(ids)
    att = []
    for c in ["AGE", "WEIGHT", "BMI", "FATP", "PMM", "VFATL"]:
        x, y = base.loc[comp_flag, c], base.loc[~comp_flag, c]
        t = stats.ttest_ind(x, y, equal_var=False) if len(y) >= 2 else None
        att.append(dict(code=c, name={"AGE": "年齡", **{k: v[0] for k, v in MAIN.items()}}[c],
                        unit={"AGE": "歲", **{k: v[1] for k, v in MAIN.items()}}[c],
                        n1=int(len(x)), m1=r(x.mean(), 3), s1=r(x.std(), 3),
                        n0=int(len(y)), m0=r(y.mean(), 3) if len(y) else None, s0=r(y.std(), 3) if len(y) > 1 else None,
                        p=r(t.pvalue, 6) if t is not None else None))
    tab = [[int(((base.SEX == s) & comp_flag).sum()), int(((base.SEX == s) & ~comp_flag).sum())] for s in ["M", "F"]]
    sx = chisq_table(tab, ["男性", "女性"], ["完成前後測", "僅前測"])
    out["attrition"] = dict(n_completed=int(comp_flag.sum()), n_dropped=int((~comp_flag).sum()), vars=att, sex=sx)

    # 基線現況（前測全部受測者，作總體評價用）
    out["baseline"] = dict(
        n=int(len(base)),
        bmi_cat=[int((base.BMI.map(bmi_cat) == k).sum()) for k in BMI_CATS],
        vfat_cat=[int((base.VFATL.map(vfat_cat) == k).sum()) for k in VFAT_CATS],
        binary={bc: int(base[bc].sum()) for bc in BINARY},
        binary_by_sex={bc: {s: [int(base.loc[base.SEX == s, bc].sum()), int((base.SEX == s).sum())] for s in ["M", "F"]}
                       for bc in BINARY},
        means={c: r(base[c].mean(), 3) for c in MAIN},
        means_by_sex={c: {s: r(base.loc[base.SEX == s, c].mean(), 3) for s in ["M", "F"]} for c in MAIN},
        metaage_over=int((base.METAAGE > base.AGE).sum()),
        hidden_fat=int(((base.BMI < 24) & (base.fat == 1)).sum()),
    )
    out["evaluation"] = build_evaluation(out)
    return D, out


# ---------------------------------------------------------------- 總體評價（依國民健康署標準）
def pfmt(p):
    if p is None:
        return "—"
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def sex_gap(o, outcome):
    """基線該指標的性別差異若達顯著，回傳一句說明。"""
    for x in o["baseline_chisq"]:
        if x["outcome"] == outcome and x["by"] == "性別":
            p = x["p_fisher"] if (x.get("n_exp_lt5") or 0) > 0 else x["p"]
            if p is not None and p < ALPHA:
                (m1, m0), (f1, f0) = x["observed"]
                pm, pf = 100 * m1 / (m1 + m0), 100 * f1 / (f1 + f0)
                hi, lo = (("男性", pm), ("女性", pf)) if pm >= pf else (("女性", pf), ("男性", pm))
                return f"{hi[0]}比例（{hi[1]:.1f}%）顯著高於{lo[0]}（{lo[1]:.1f}%），{pfmt(p)}。"
    return ""


def build_evaluation(o):
    b, info = o["baseline"], o["info"]
    n = b["n"]
    allm = o["strata"]["all"]["main"]
    pct = lambda k: 100 * k / n
    ow = b["binary"]["ow"]; ob = b["binary"]["ob"]; fat = b["binary"]["fat"]; vf = b["binary"]["vfat"]
    findings = []
    # 1 體位
    lvl = "high" if pct(ow) >= 50 else "mid" if pct(ow) >= 30 else "low"
    findings.append(dict(
        title="體位（BMI）", level=lvl,
        text=f"前測 {n} 人中，BMI ≥ 24（過重或肥胖）共 {ow} 人（{pct(ow):.1f}%），其中 BMI ≥ 27（肥胖）{ob} 人（{pct(ob):.1f}%）；"
             f"體位正常（18.5 ≤ BMI < 24）{b['bmi_cat'][1]} 人（{pct(b['bmi_cat'][1]):.1f}%）。" + sex_gap(o, "ow")))
    # 2 體脂
    bs = b["binary_by_sex"]["fat"]
    lvl = "high" if pct(fat) >= 50 else "mid" if pct(fat) >= 30 else "low"
    findings.append(dict(
        title="體脂肪率", level=lvl,
        text=f"依國民健康署標準（男性 ≥ 25%、女性 ≥ 30% 屬肥胖），體脂肪率超標 {fat} 人（{pct(fat):.1f}%）；"
             f"男性 {bs['M'][0]}/{bs['M'][1]} 人、女性 {bs['F'][0]}/{bs['F'][1]} 人。"
             + (f"其中 {b['hidden_fat']} 人 BMI 未達 24 但體脂肪率已超標（俗稱「隱性肥胖」），不宜僅以體重判斷。"
                if b["hidden_fat"] else "")))
    # 3 內臟脂肪
    lvl = "high" if pct(vf) >= 40 else "mid" if pct(vf) >= 20 else "low"
    findings.append(dict(
        title="內臟脂肪", level=lvl,
        text=f"內臟脂肪等級 ≥ 10（TANITA 原廠「偏高」標準）{vf} 人（{pct(vf):.1f}%），其中 ≥ 15 者 {b['vfat_cat'][2]} 人。"
             + sex_gap(o, "vfat")
             + "內臟脂肪與代謝症候群風險相關，國健署建議以腰圍輔助評估（男性 ≥ 90 cm、女性 ≥ 80 cm 為腹部肥胖），本次未測腰圍。"))
    # 4 前後變化
    sig = []
    for c, (name, unit, dec, good, _) in MAIN.items():
        s = allm[c]
        if s.get("p") is not None and s["p"] < ALPHA:
            direction = "上升" if s["diff_mean"] > 0 else "下降"
            fav = "" if good == 0 else ("（有利）" if np.sign(s["diff_mean"]) == good else "（不利）")
            sig.append(f"{name}{direction} {abs(s['diff_mean']):.{max(dec,1)}f} {unit}{fav}，{pfmt(s['p'])}")
    nsig = [MAIN[c][0] for c in ["WEIGHT", "FATP", "PMM", "VFATL"] if allm[c].get("p") is None or allm[c]["p"] >= ALPHA]
    txt = (f"完成前後測 {info['n_paired']} 人，間隔 {info['interval_days']} 天。"
           + ("達統計顯著（p < 0.05）的變化：" + "；".join(sig) + "。" if sig else "各項指標前後測均未達統計顯著差異。")
           + (f"{'、'.join(nsig)}未達顯著差異。" if nsig and sig else ""))
    split = [MAIN[c][0] for c in MAIN if allm[c].get("p_t") is not None and allm[c].get("p_w") is not None
             and (allm[c]["p_t"] < ALPHA) != (allm[c]["p_w"] < ALPHA)]
    if split:
        txt += (f"另{'、'.join(split)}的配對 t 檢定與 Wilcoxon 檢定結論不一致（變化量分布偏態），"
                "已依常態性檢定結果擇一判定，宜保守解讀。")
    if sig and all((allm[c].get("p_holm") or 1) >= ALPHA for c in MAIN):
        txt += "若以 Holm 法校正多重比較，所有指標均未達顯著，上述變化屬初步趨勢。"
    lvl = "low" if any("有利" in s for s in sig) and not any("不利" in s for s in sig) else "mid"
    findings.append(dict(title="前後測變化", level=lvl, text=txt))
    # 綜合等級
    score = sum({"high": 2, "mid": 1, "low": 0}[f["level"]] for f in findings[:3])
    overall = "需優先介入" if score >= 4 else "需持續關注" if score >= 2 else "整體良好"
    recs = [
        dict(title="健康體重管理", text="依國健署「聰明吃、快樂動、天天量體重」原則；BMI ≥ 24 者以每週減重 0.5–1 公斤為目標，避免快速減重造成肌肉流失。"),
        dict(title="均衡飲食", text="依國健署「我的餐盤」六口訣：每天早晚一杯奶、每餐水果拳頭大、菜比水果多一點、飯跟蔬菜一樣多、豆魚蛋肉一掌心、堅果種子一茶匙；減少含糖飲料與高油加工食品。"),
        dict(title="規律身體活動", text="成人每週累積至少 150 分鐘中等費力身體活動（或 75 分鐘費力身體活動），並每週至少 2 天進行肌力訓練，有助於降低體脂並維持肌肉量。"),
        dict(title="職場支持措施", text="建議職場推動減少久坐（每坐 1 小時起身活動）、提供健康餐飲選項及團體運動課程，並將腰圍納入下次量測，以完整評估腹部肥胖。"),
        dict(title="持續追蹤", text="建議固定每 3–6 個月以同一機型、同一時段（空腹、未運動、排尿後）量測，以降低測量誤差並追蹤成效。"),
    ]
    rule = ("依三項風險分類盛行率判定：BMI ≥ 24 與體脂肪率超標比例 ≥ 50% 為「需介入」、30–49% 為「需關注」；"
            "內臟脂肪偏高比例 ≥ 40% 為「需介入」、20–39% 為「需關注」。需介入計 2 分、需關注計 1 分，"
            "合計 ≥ 4 分為「需優先介入」、2–3 分為「需持續關注」、0–1 分為「整體良好」。此分級為本報告自訂之彙整方式，非國健署公告分級。")
    return dict(overall=overall, rule=rule, findings=findings, recommendations=recs,
                sources=["衛生福利部國民健康署「成人健康體位標準」（BMI、腰圍、體脂肪率）",
                         "衛生福利部國民健康署「每日飲食指南」及「我的餐盤」（107 年版）",
                         "衛生福利部國民健康署 身體活動建議（成人每週 150 分鐘中等費力身體活動、每週 2 天肌力訓練）",
                         "內臟脂肪等級分級為 TANITA 原廠標準（非國健署公告）"])


def main():
    path = sys.argv[1]
    outdir = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / "output")
    outdir.mkdir(parents=True, exist_ok=True)
    _, res = run(path)
    (outdir / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)), encoding="utf-8")
    print(json.dumps(res["info"], ensure_ascii=False))


if __name__ == "__main__":
    main()
