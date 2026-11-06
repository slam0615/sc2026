"""TANITA MC-780 多次測量（固定測量日）身體組成 — 總體統計分析。

用法：
    python analyze.py <GMON匯出.xls> [輸出資料夾] [--name 職場名稱]

輸入可為 GMON 原始英文欄位（CUSTOMERID、DATETIME…），或已翻成中文欄名的版本（受測者編號、測量日期與時間…）。
測量波次依日期分群：相鄰測量日相隔超過 WAVE_GAP_DAYS 天視為新的一波（T1、T2、T3…）。

分析方法皆為 SPSS 可重現的程序：
    各波描述統計與 95% CI（EXAMINE）
    主分析：完成全部波次者之重複測量 ANOVA（GLM REPEATED；Mauchly 球形檢定、Greenhouse-Geisser 校正、
           Bonferroni 事後比較、偏 η²）與 Friedman 檢定（NPAR TESTS /FRIEDMAN）
    補充分析：全部可用資料之線性混合模型（MIXED；REML、個人隨機截距、Satterthwaite 自由度、Bonferroni）
             及各配對可用資料之配對 t 檢定（T-TEST PAIRS）
    分類變項：Cochran's Q 與 McNemar 精確檢定（NPAR TESTS）；各波 Pearson 卡方與 Fisher 精確檢定（CROSSTABS）
    分層：性別、年齡層各自的重複測量 ANOVA，以及 時間 × 分組 交互作用（MIXED）
"""
from __future__ import annotations

import json
import math
import sys
import warnings
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

warnings.filterwarnings("ignore")

MIN_N = 10          # 分析人數低於此值不呈現（避免小群體可推測個人）
ALPHA = 0.05
KJ_PER_KCAL = 4.184
WAVE_GAP_DAYS = 7   # 測量日相隔超過此天數才算新的一波（同一波可跨數天）

# ---------------------------------------------------------------- 欄位定義
# code: (中文名稱, 單位, 小數位, 期望方向 -1=下降有利 / +1=上升有利 / 0=不判定, 說明)
MAIN = {
    "WEIGHT":     ("體重", "kg", 1, -1, "已扣除衣物重量"),
    "BMI":        ("身體質量指數 BMI", "kg/m²", 1, -1, "體重(kg) ÷ 身高(m)²"),
    "FATP":       ("體脂肪率", "%", 1, -1, "脂肪量占體重百分比"),
    "FATM":       ("脂肪量", "kg", 1, -1, ""),
    "FFM":        ("除脂肪量", "kg", 1, +1, "體重扣除脂肪量（去脂體重）"),
    "PMM":        ("肌肉量", "kg", 1, +1, "推定肌肉量（含骨骼肌、平滑肌及其水分）"),
    "BONEM":      ("推定骨量", "kg", 1, 0, "骨骼中礦物質推定值"),
    "TBW":        ("體水分量", "kg", 1, 0, "身體總水分量"),
    "ICW":        ("細胞內液", "kg", 1, 0, "細胞內水分量"),
    "ECW":        ("細胞外液", "kg", 1, 0, "細胞外水分量"),
    "ECWR":       ("細胞外液比 (ECW/TBW)", "%", 1, 0, "衍生指標：細胞外液 ÷ 體水分量 × 100"),
    "BMR":        ("基礎代謝量", "kcal/日", 0, 0, "原始資料為 kJ，已 ÷ 4.184 換算為 kcal"),
    "METAAGE":    ("體內年齡", "歲", 0, -1, "TANITA 依基礎代謝推估之年齡（代謝年齡）"),
    "VFATL":      ("內臟脂肪等級", "等級", 0, -1, "TANITA 原廠等級（1–59）"),
    "PHASEANGLE": ("相位角", "°", 2, +1, "50 kHz 全身相位角，反映細胞完整性"),
    "IMP":        ("全身阻抗", "Ω", 1, 0, "50 kHz 全身生物電阻抗"),
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
    "GROUP1": ("群組一（職場）", "", ""), "GROUP2": ("群組二", "", ""),
    "PATNR": ("系統序號", "", "已於報告中移除"),
    "DATETIME": ("測量日期時間", "", ""), "MODEL": ("機型", "", "MC-780"),
    "FLAG": ("資料旗標", "", "系統內部碼"), "CONDITION": ("接觸狀態", "", "空白"),
    "AGE": ("年齡", "歲", ""), "BTYP": ("體型模式", "", "0=標準、2=運動員"),
    "HEIGHT": ("身高", "cm", ""), "CLOTHES": ("衣物重量扣除值", "kg", ""),
    "DCI": ("每日建議攝取熱量", "kcal", "空白（未設定活動量）"),
    "PAL": ("身體活動等級", "", "空白"),
    "BLOB_DATA": ("原始量測二進位資料", "", "不使用"),
    "PHYSRATE": ("體型評分代碼", "", "TANITA 內部編碼，匯出檔無對照表，不納入統計"),
}

# 中文欄名版本 → GMON 欄位代碼
ZH_COLUMNS = {
    "受測者編號": "CUSTOMERID", "姓氏": "LASTNAME", "名字": "FIRSTNAME", "性別": "SEX",
    "受測者內部編號": "PATNR", "測量日期與時間": "DATETIME", "儀器型號": "MODEL", "資料類型旗標": "FLAG",
    "接觸狀態": "CONDITION", "年齡": "AGE", "體型模式": "BTYP", "身高(cm)": "HEIGHT", "體重(kg)": "WEIGHT",
    "衣物重量扣除值(kg)": "CLOTHES", "身體質量指數(BMI)": "BMI", "體脂肪率(%)": "FATP", "脂肪量(kg)": "FATM",
    "預測肌肉量(kg)": "PMM", "內臟脂肪等級": "VFATL", "推定骨量(kg)": "BONEM", "去脂體重(kg)": "FFM",
    "身體總水分量(kg)": "TBW", "細胞外水分量(kg)": "ECW", "細胞內水分量(kg)": "ICW",
    "基礎代謝率(kJ/日)": "BMR", "每日熱量攝取量": "DCI", "身體活動程度": "PAL", "代謝年齡": "METAAGE",
    "全身生物電阻抗(Ω)": "IMP", "全身相位角(°)": "PHASEANGLE", "二進位原始資料": "BLOB_DATA",
    "體型評分代碼": "PHYSRATE", "群組1": "GROUP1", "群組2": "GROUP2",
}
for _p, _zh in [("RL", "右腿"), ("LL", "左腿"), ("RA", "右臂"), ("LA", "左臂"), ("TR", "軀幹")]:
    ZH_COLUMNS.update({f"{_zh}體脂肪率(%)": f"{_p}FATP", f"{_zh}脂肪量(kg)": f"{_p}FATM",
                       f"{_zh}去脂體重(kg)": f"{_p}FFM", f"{_zh}預測肌肉量(kg)": f"{_p}PMM",
                       f"{_zh}生物電阻抗(Ω)": f"{_p}IMP"})

AGE_BINS = [(0, 29, "<30"), (30, 39, "30-39"), (40, 200, "≥40")]
SEX_LABEL = {"M": "男性", "F": "女性"}
BMI_CATS = ["過輕", "正常", "過重", "肥胖"]
VFAT_CATS = ["標準 (1–9)", "偏高 (10–14)", "過高 (≥15)"]


def age_label(lo, hi):
    return f"<{hi + 1}" if lo == 0 else f"≥{lo}" if hi >= 200 else f"{lo}-{hi}"


def make_age_bins(ages):
    """預設 <30、30-39、≥40；任一組人數 < MIN_N 時與較小的相鄰組合併（至少保留 2 組）。"""
    bins = [[lo, hi] for lo, hi, _ in AGE_BINS]
    while len(bins) > 2:
        counts = [int(((ages >= lo) & (ages <= hi)).sum()) for lo, hi in bins]
        i = int(np.argmin(counts))
        if counts[i] >= MIN_N:
            break
        j = i + 1 if i == 0 else i - 1 if i == len(bins) - 1 else (i - 1 if counts[i - 1] <= counts[i + 1] else i + 1)
        a, b = sorted((i, j))
        bins[a:b + 1] = [[bins[a][0], bins[b][1]]]
    return [(lo, hi, age_label(lo, hi)) for lo, hi in bins]


def age_group(a, bins=AGE_BINS):
    for lo, hi, lab in bins:
        if lo <= a <= hi:
            return lab
    return None


def bmi_cat(b):
    return "過輕" if b < 18.5 else "正常" if b < 24 else "過重" if b < 27 else "肥胖"


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
def load_data(path, name=None):
    raw = pd.read_excel(path)
    raw = raw.rename(columns={c: ZH_COLUMNS.get(str(c).strip(), c) for c in raw.columns})
    missing = [c for c in ["CUSTOMERID", "DATETIME", "SEX", "AGE", *MAIN.keys() - {"ECWR"}] if c not in raw.columns]
    if missing:
        raise SystemExit(f"找不到必要欄位：{missing}")
    d = raw.copy()
    d["DATETIME"] = pd.to_datetime(d["DATETIME"])
    d["DATE"] = d["DATETIME"].dt.normalize()
    d["BMR"] = d["BMR"] / KJ_PER_KCAL
    d["ECWR"] = d["ECW"] / d["TBW"] * 100
    for code, meta in {**MAIN, **SEG}.items():
        if code in d:
            d[code] = d[code].astype(float).round(2 if code == "ECWR" else meta[2])
    log = []
    # 波次：依測量日分群
    dates = sorted(d["DATE"].unique())
    wave_of, w, waves = {}, 0, [[dates[0]]]
    wave_of[dates[0]] = 1
    for prev, cur in zip(dates, dates[1:]):
        if (pd.Timestamp(cur) - pd.Timestamp(prev)).days > WAVE_GAP_DAYS:
            waves.append([])
        waves[-1].append(cur)
        wave_of[cur] = len(waves)
    d["WAVE"] = d["DATE"].map(wave_of)
    K = len(waves)
    if K < 2:
        raise SystemExit("只有一個測量波次，無法比較變化")
    for i, ws in enumerate(waves, 1):
        if len(ws) > 1:
            log.append(f"T{i} 包含 {len(ws)} 個測量日（{pd.Timestamp(ws[0]).date()}～{pd.Timestamp(ws[-1]).date()}），合併為同一波")
    dup = d.duplicated(["CUSTOMERID", "WAVE"], keep=False)
    if dup.any():
        log.append(f"{d[dup].groupby(['CUSTOMERID', 'WAVE']).ngroups} 人次於同一波重複量測，保留該波最後一筆")
    d = d.sort_values("DATETIME").drop_duplicates(["CUSTOMERID", "WAVE"], keep="last")
    # 一致性檢查
    g = d.groupby("CUSTOMERID")
    if (g["SEX"].nunique() > 1).any():
        log.append(f"警告：{int((g['SEX'].nunique() > 1).sum())} 人性別前後不一致，請檢查編號")
    if (g["HEIGHT"].agg(lambda s: s.max() - s.min()) > 2).any():
        log.append(f"警告：{int((g['HEIGHT'].agg(lambda s: s.max() - s.min()) > 2).sum())} 人身高差異超過 2 cm，請檢查編號")
    first = d.sort_values("DATETIME").groupby("CUSTOMERID").first()
    age_bins = make_age_bins(first["AGE"])
    if len(age_bins) < len(AGE_BINS):
        log.append("部分年齡層人數不足 %d 人，合併為：%s" % (MIN_N, "、".join(f"{b[2]} 歲" for b in age_bins)))
    d["AGE0"] = d["CUSTOMERID"].map(first["AGE"])
    d["AGEGRP"] = d["AGE0"].map(lambda a: age_group(a, age_bins))
    d["SEX"] = d["CUSTOMERID"].map(first["SEX"])
    for bc, (_, fn) in BINARY.items():
        d[bc] = d.apply(fn, axis=1)
    d["BMICAT"] = d["BMI"].map(bmi_cat)
    d["VFCAT"] = d["VFATL"].map(vfat_cat)
    # 寬格式
    people = first[["SEX"]].copy()
    people["AGE0"] = first["AGE"]
    people["AGEGRP"] = people["AGE0"].map(lambda a: age_group(a, age_bins))
    present = d.pivot_table(index="CUSTOMERID", columns="WAVE", values="WEIGHT", aggfunc="size").reindex(columns=range(1, K + 1)).notna()
    people["PATTERN"] = present.apply(lambda r: "-".join(f"T{w}" for w in range(1, K + 1) if r[w]), axis=1)
    people["COMPLETE"] = present.all(axis=1).astype(int)
    for w in range(1, K + 1):
        people[f"HAS{w}"] = present[w].astype(int)
    by_wave = {w: d[d.WAVE == w].set_index("CUSTOMERID") for w in range(1, K + 1)}
    workplace = name or (str(raw["GROUP1"].dropna().iloc[0]) if "GROUP1" in raw and raw["GROUP1"].notna().any() else Path(path).stem)
    info = dict(
        workplace=workplace, model=str(raw["MODEL"].dropna().iloc[0]) if "MODEL" in raw else "MC-780",
        k=K, waves=[dict(label=f"T{i}", date=str(pd.Timestamp(ws[0]).date()),
                         date_end=str(pd.Timestamp(ws[-1]).date()), n=int(len(by_wave[i]))) for i, ws in enumerate(waves, 1)],
        intervals=[int((pd.Timestamp(waves[i][0]) - pd.Timestamp(waves[i - 1][0])).days) for i in range(1, K)],
        n_records=int(len(raw)), n_people=int(raw["CUSTOMERID"].nunique()), n_complete=int(people.COMPLETE.sum()),
        patterns=[dict(pattern=p, n=int(n)) for p, n in people.PATTERN.value_counts().items()],
        cleaning_log=log, age_groups=[b[2] for b in age_bins],
    )
    info["patterns"].sort(key=lambda x: (-len(x["pattern"]), x["pattern"]))
    return dict(raw=raw, long=d, people=people, by_wave=by_wave, info=info, K=K, age_groups=[b[2] for b in age_bins])


# ---------------------------------------------------------------- 統計工具
def r(x, k=6):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    return None if (math.isnan(x) or math.isinf(x)) else round(x, k)


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return r(o)
    return o


def desc(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 2:
        return dict(n=n)
    m, sd = x.mean(), x.std(ddof=1)
    h = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)
    return dict(n=n, mean=m, sd=sd, ci_lo=m - h, ci_hi=m + h)


def paired(a, b, bonf=1):
    """配對 t（b − a）＋ Wilcoxon（SPSS 設定）；bonf = Bonferroni 比較次數。"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    diff = b - a
    n = len(diff)
    out = dict(n=n)
    if n < 2:
        return out
    md, sd = diff.mean(), diff.std(ddof=1)
    se = sd / math.sqrt(n)
    tc = stats.t.ppf(1 - ALPHA / (2 * bonf), n - 1)
    p = 2 * stats.t.sf(abs(md / se), n - 1) if sd > 0 else 1.0
    out.update(diff=md, sd=sd, se=se, t=md / se if sd > 0 else 0.0, df=n - 1, p=p, p_bonf=min(1.0, p * bonf),
               ci_lo=md - tc * se, ci_hi=md + tc * se, pct=md / a.mean() * 100 if a.mean() else None)
    try:
        out["p_w"] = float(stats.wilcoxon(a, b, zero_method="wilcox", correction=False, method="approx").pvalue)
    except ValueError:
        out["p_w"] = 1.0
    out["p_w_bonf"] = min(1.0, out["p_w"] * bonf)
    return out


def helmert(k):
    """k 水準的正交化（標準正交）對比矩陣 k×(k−1)。"""
    M = np.zeros((k, k - 1))
    for j in range(1, k):
        M[:j, j - 1] = 1
        M[j, j - 1] = -j
        M[:, j - 1] /= np.linalg.norm(M[:, j - 1])
    return M


def rm_anova(Y):
    """單因子重複測量 ANOVA（SPSS GLM REPEATED）。Y：n×k 完整資料。"""
    Y = np.asarray(Y, float)
    n, k = Y.shape
    out = dict(n=n)
    if n < 3:
        return out
    gm = Y.mean()
    ss_t = n * ((Y.mean(0) - gm) ** 2).sum()
    ss_s = k * ((Y.mean(1) - gm) ** 2).sum()
    ss_e = ((Y - gm) ** 2).sum() - ss_t - ss_s
    df1, df2 = k - 1, (k - 1) * (n - 1)
    F = (ss_t / df1) / (ss_e / df2) if ss_e > 0 else float("nan")
    p = stats.f.sf(F, df1, df2) if ss_e > 0 else 1.0
    C = helmert(k).T @ np.cov(Y, rowvar=False) @ helmert(k)
    pdim = k - 1
    tr = np.trace(C)
    eps = tr ** 2 / (pdim * np.trace(C @ C)) if tr > 0 else 1.0
    if pdim > 1 and tr > 0:
        W = np.linalg.det(C) / (tr / pdim) ** pdim
        chi = -(n - 1 - (2 * pdim ** 2 + pdim + 2) / (6 * pdim)) * math.log(W) if W > 0 else float("nan")
        mdf = pdim * (pdim + 1) / 2 - 1
        p_m = stats.chi2.sf(chi, mdf)
    else:
        W, chi, mdf, p_m = 1.0, None, 0, None
    p_gg = stats.f.sf(F, df1 * eps, df2 * eps) if ss_e > 0 else 1.0
    use_gg = p_m is not None and p_m < ALPHA
    out.update(means=Y.mean(0).tolist(), sds=Y.std(0, ddof=1).tolist(), ss_time=ss_t, ss_subj=ss_s, ss_err=ss_e,
               df1=df1, df2=df2, F=F, p=p, mauchly_W=W, mauchly_chi2=chi, mauchly_df=mdf, mauchly_p=p_m,
               eps_gg=eps, df1_gg=df1 * eps, df2_gg=df2 * eps, p_gg=p_gg, use_gg=use_gg,
               p_final=p_gg if use_gg else p, pes=ss_t / (ss_t + ss_e) if ss_t + ss_e > 0 else 0.0)
    try:
        fr = stats.friedmanchisquare(*[Y[:, j] for j in range(k)])
        out.update(friedman_chi2=fr.statistic, friedman_p=fr.pvalue, kendall_w=fr.statistic / (n * (k - 1)))
    except ValueError:
        out.update(friedman_chi2=0.0, friedman_p=1.0, kendall_w=0.0)
    if not np.isfinite(out.get("friedman_p", 1.0)):
        out.update(friedman_chi2=0.0, friedman_p=1.0, kendall_w=0.0)
    nb = k * (k - 1) // 2
    out["pairs"] = [dict(a=i + 1, b=j + 1, **paired(Y[:, i], Y[:, j], bonf=nb)) for i, j in combinations(range(k), 2)]
    return out


# ---- 線性混合模型（個人隨機截距；REML；Satterthwaite 自由度）— 對應 SPSS MIXED
class Mixed:
    """隨機截距模型 V_i = σe²·I + σu²·J；以群組彙總量計算（封閉解），不需建立整個 V 矩陣。"""

    def __init__(self, y, X, groups):
        self.y, self.X = np.asarray(y, float), np.asarray(X, float)
        _, g = np.unique(groups, return_inverse=True)
        G = np.eye(g.max() + 1)[g]                  # 觀測 × 群組
        self.ni = G.sum(0)                          # 各人觀測數
        self.S = G.T @ self.X                       # 各人 X 欄合計（群組 × p）
        self.t = G.T @ self.y                       # 各人 y 合計
        self.XtX, self.Xty, self.yty = self.X.T @ self.X, self.X.T @ self.y, self.y @ self.y
        self.n, self.p = self.X.shape

    def parts(self, th):
        su, se = th
        w = su / (se + self.ni * su)
        XtViX = (self.XtX - (self.S * w[:, None]).T @ self.S) / se
        XtViy = (self.Xty - self.S.T @ (w * self.t)) / se
        ytViy = (self.yty - (w * self.t ** 2).sum()) / se
        C = np.linalg.inv(XtViX)
        beta = C @ XtViy
        logdetV = ((self.ni - 1) * math.log(se) + np.log(se + self.ni * su)).sum()
        return logdetV, XtViX, C, beta, ytViy - beta @ XtViy

    def nll(self, th):  # REML 負對數概似（省略常數）
        if th[0] < 0 or th[1] <= 0:
            return 1e30
        try:
            logdetV, XtViX, _, _, rVr = self.parts(th)
        except np.linalg.LinAlgError:
            return 1e30
        val = 0.5 * (logdetV + np.linalg.slogdet(XtViX)[1] + rVr)
        return val if np.isfinite(val) else 1e30

    def fit(self):
        # 以對數尺度最佳化（σ² 跨數個數量級時較穩定）；σu² 可趨近 0（邊界）
        f = lambda a: self.nll(np.exp(a))
        v = np.var(self.y) or 1.0
        best = None
        for start in ([v * 0.9, v * 0.1], [v * 0.1, v * 0.9], [v * 1e-4, v]):
            res = optimize.minimize(f, np.log(start), method="L-BFGS-B", bounds=[(math.log(v) - 25, math.log(v) + 5)] * 2,
                                    options=dict(ftol=1e-15, gtol=1e-12, maxiter=5000))
            if best is None or res.fun < best.fun:
                best = res
        best = optimize.minimize(f, best.x, method="Nelder-Mead", options=dict(xatol=1e-10, fatol=1e-14, maxiter=5000))
        best.x = np.exp(best.x)
        self.th = best.x
        _, _, self.C, self.beta, _ = self.parts(self.th)
        # 共變異數參數的漸近共變異矩陣（觀察資訊矩陣之反矩陣，數值 Hessian）
        h = np.maximum(np.abs(self.th) * 1e-4, 1e-8)
        H = np.zeros((2, 2))
        for i in range(2):
            for j in range(2):
                def f(di, dj):
                    t = self.th.copy()
                    t[i] += di
                    t[j] += dj
                    return self.nll(t)
                H[i, j] = (f(h[i], h[j]) - f(h[i], -h[j]) - f(-h[i], h[j]) + f(-h[i], -h[j])) / (4 * h[i] * h[j])
        self.boundary = self.th[0] < 1e-6 * max(self.th[1], 1e-12)
        if self.boundary:  # 隨機截距變異數落在邊界：只對殘差變異估計
            self.A = np.diag([0.0, 1 / H[1, 1]])
        else:
            self.A = np.linalg.inv(H)
        return self

    def _grad(self, fn):
        g = np.zeros(2)
        for i in range(2):
            h = max(abs(self.th[i]) * 1e-4, 1e-8)
            t1, t2 = self.th.copy(), self.th.copy()
            t1[i] += h
            t2[i] = max(t2[i] - h, 0)
            g[i] = (fn(t1) - fn(t2)) / (t1[i] - t2[i])
        return g

    def contrast(self, L):
        """檢定 Lβ = 0；回傳 F、df1、df2（Satterthwaite）、p，以及單列時的估計值與 SE。"""
        L = np.atleast_2d(np.asarray(L, float))
        q = L.shape[0]
        LCL = L @ self.C @ L.T
        est = L @ self.beta
        F = float(est @ np.linalg.solve(LCL, est)) / q
        D, P = np.linalg.eigh(LCL)
        nus = []
        for m in range(q):
            pm = P[:, m]
            g = self._grad(lambda t: float(pm @ L @ self.parts(t)[2] @ L.T @ pm))
            var = g @ self.A @ g
            nus.append(2 * D[m] ** 2 / var if var > 0 else 1e6)
        if q == 1:
            df = nus[0]
        else:
            E = sum(v / (v - 2) for v in nus if v > 2)
            df = 2 * E / (E - q) if E > q else min(nus)
        p = stats.f.sf(F, q, df)
        return dict(F=F, df1=q, df2=df, p=p, est=est.tolist(), se=np.sqrt(np.diag(LCL)).tolist())


def mixed_time(long, code, K, group=None):
    """time 主效果模型（EMMs、兩兩比較）；group 給定時另回傳 time × group 交互作用。"""
    dd = long[["CUSTOMERID", "WAVE", code] + ([group] if group else [])].dropna()
    if dd.CUSTOMERID.nunique() < MIN_N:
        return None
    T = np.eye(K)[dd.WAVE.values - 1]
    X = np.column_stack([np.ones(len(dd)), T[:, :-1]])  # 參考組＝最後一波（同 SPSS）
    out = {}
    if group:
        levels = sorted(dd[group].unique())
        if len(levels) < 2:
            return None
        G = np.column_stack([(dd[group] == lv).astype(float) for lv in levels[:-1]])
        inter = np.column_stack([T[:, i] * G[:, j] for i in range(K - 1) for j in range(G.shape[1])])
        X = np.column_stack([X, G, inter])
        m = Mixed(dd[code].values, X, dd.CUSTOMERID.values).fit()
        L = np.zeros((inter.shape[1], X.shape[1]))
        L[:, -inter.shape[1]:] = np.eye(inter.shape[1])
        res = m.contrast(L)
        return dict(F=res["F"], df1=res["df1"], df2=res["df2"], p=res["p"], n=int(dd.CUSTOMERID.nunique()), n_obs=int(len(dd)))
    m = Mixed(dd[code].values, X, dd.CUSTOMERID.values).fit()
    L = np.zeros((K - 1, X.shape[1]))
    L[:, 1:K] = np.eye(K - 1)
    out.update(m.contrast(L))
    out.update(n=int(dd.CUSTOMERID.nunique()), n_obs=int(len(dd)), var_subject=m.th[0], var_resid=m.th[1], boundary=bool(m.boundary))
    emm = []
    for w in range(K):
        l = np.zeros(X.shape[1])
        l[0] = 1
        if w < K - 1:
            l[1 + w] = 1
        c = m.contrast(l)
        se = c["se"][0]
        tc = stats.t.ppf(0.975, c["df2"])
        emm.append(dict(mean=c["est"][0], se=se, df=c["df2"], ci_lo=c["est"][0] - tc * se, ci_hi=c["est"][0] + tc * se))
    out["emm"] = emm
    nb = K * (K - 1) // 2
    pairs = []
    for i, j in combinations(range(K), 2):
        l = np.zeros(X.shape[1])
        for w, s in ((j, 1), (i, -1)):
            if w < K - 1:
                l[1 + w] += s
        c = m.contrast(l)
        se, df = c["se"][0], c["df2"]
        tc = stats.t.ppf(1 - ALPHA / (2 * nb), df)
        pairs.append(dict(a=i + 1, b=j + 1, diff=c["est"][0], se=se, df=df, p=c["p"], p_bonf=min(1.0, c["p"] * nb),
                          ci_lo=c["est"][0] - tc * se, ci_hi=c["est"][0] + tc * se))
    out["pairs"] = pairs
    out.pop("est", None)
    out.pop("se", None)
    return out


def mcnemar_exact(b, c):
    return 1.0 if b + c == 0 else min(1.0, 2 * stats.binom.cdf(min(b, c), b + c, 0.5))


def cochran_q(B):
    B = np.asarray(B, int)
    n, k = B.shape
    C, R, T = B.sum(0), B.sum(1), B.sum()
    den = k * T - (R ** 2).sum()
    if den == 0:
        return 0.0, k - 1, 1.0
    Q = (k - 1) * (k * (C ** 2).sum() - T ** 2) / den
    return Q, k - 1, stats.chi2.sf(Q, k - 1)


def fisher_rxc(tab):
    """Fisher(-Freeman-Halton) 精確檢定（2×k 完整列舉）。"""
    tab = np.asarray(tab, int)
    if tab.shape[0] != 2:
        tab = tab.T
    if tab.shape[0] != 2:
        return None
    if tab.shape == (2, 2):
        return stats.fisher_exact(tab)[1]
    r1, cols = tab[0].sum(), tab.sum(0)
    N = cols.sum()

    def logp(row):
        return (sum(math.lgamma(c + 1) - math.lgamma(x + 1) - math.lgamma(c - x + 1) for x, c in zip(row, cols))
                - (math.lgamma(N + 1) - math.lgamma(r1 + 1) - math.lgamma(N - r1 + 1)))

    p_obs, total = logp(tab[0]), 0.0

    def rec(i, rem, acc):
        nonlocal total
        if i == len(cols) - 1:
            if 0 <= rem <= cols[i]:
                lp = logp(acc + [rem])
                if lp <= p_obs + 1e-7:
                    total += math.exp(lp)
            return
        for x in range(0, min(cols[i], rem) + 1):
            rec(i + 1, rem - x, acc + [x])

    rec(0, r1, [])
    return min(1.0, total)


def chisq_table(tab, row_labels, col_labels):
    tab = np.asarray(tab, float)
    t2 = tab[tab.sum(1) > 0][:, tab.sum(0) > 0]
    res = dict(rows=row_labels, cols=col_labels, observed=tab.astype(int).tolist(), n=int(tab.sum()))
    if min(t2.shape) < 2:
        return {**res, "chi2": None, "df": None, "p": None, "p_fisher": None, "min_expected": None, "n_exp_lt5": None, "n_cells": None}
    chi, p, df, exp = stats.chi2_contingency(t2, correction=False)
    res.update(chi2=chi, df=int(df), p=p, min_expected=exp.min(), n_exp_lt5=int((exp < 5).sum()), n_cells=int(exp.size),
               p_fisher=fisher_rxc(t2) if 2 in t2.shape else None)
    res["use_fisher"] = res["n_exp_lt5"] / res["n_cells"] > 0.2
    return res


# ---------------------------------------------------------------- 分析
def strata_keys(ages):
    keys = [("all", "全體", None, None)]
    keys += [(f"sex:{s}", SEX_LABEL[s], s, None) for s in ["M", "F"]]
    keys += [(f"age:{g}", f"{g} 歲", None, g) for g in ages]
    keys += [(f"sex:{s}|age:{g}", f"{SEX_LABEL[s]}・{g} 歲", s, g) for s in ["M", "F"] for g in ages]
    return keys


def stratum_analysis(D, sex, grp, full=True):
    K, people, long = D["K"], D["people"], D["long"]
    ids = people.index
    if sex:
        ids = ids[people.loc[ids, "SEX"] == sex]
    if grp:
        ids = ids[people.loc[ids, "AGEGRP"] == grp]
    comp = ids[people.loc[ids, "COMPLETE"] == 1]
    lg = long[long.CUSTOMERID.isin(ids)]
    st = dict(n=int(len(ids)), n_complete=int(len(comp)), n_wave=[int((lg.WAVE == w).sum()) for w in range(1, K + 1)])
    st["suppressed"] = st["n"] < MIN_N
    if st["suppressed"]:
        return st
    codes = list(MAIN) + (list(SEG) if full else [])
    st["desc"] = {c: [desc(lg.loc[lg.WAVE == w, c]) if (lg.WAVE == w).sum() >= MIN_N else dict(n=int((lg.WAVE == w).sum()))
                      for w in range(1, K + 1)] for c in MAIN}
    wide = {c: lg.pivot(index="CUSTOMERID", columns="WAVE", values=c).reindex(columns=range(1, K + 1)) for c in codes}
    if len(comp) >= MIN_N:
        st["rm"] = {c: rm_anova(wide[c].loc[comp].values) for c in codes}
    if full:
        if not sex and not grp:  # 混合模型只做全體（分層差異以交互作用檢定）
            st["mixed"] = {c: mixed_time(lg, c, K) for c in MAIN}
        st["avail"] = {}
        nb = K * (K - 1) // 2
        for c in MAIN:
            prs = []
            for i, j in combinations(range(1, K + 1), 2):
                sub = wide[c][[i, j]].dropna()
                prs.append(dict(a=i, b=j, **(paired(sub[i], sub[j], bonf=nb) if len(sub) >= MIN_N else dict(n=int(len(sub))))))
            st["avail"][c] = prs
    # 分類：各波分布（可用資料）＋ 完成者 Cochran's Q / McNemar
    cat = {}
    for bc in BINARY:
        wv = [dict(n=int((lg.WAVE == w).sum()), yes=int(lg.loc[lg.WAVE == w, bc].sum())) for w in range(1, K + 1)]
        item = dict(waves=wv)
        if len(comp) >= MIN_N:
            B = lg[lg.CUSTOMERID.isin(comp)].pivot(index="CUSTOMERID", columns="WAVE", values=bc).reindex(columns=range(1, K + 1)).values
            Q, df, p = cochran_q(B)
            nb = K * (K - 1) // 2
            prs = []
            for i, j in combinations(range(K), 2):
                b_ = int(((B[:, i] == 1) & (B[:, j] == 0)).sum())
                c_ = int(((B[:, i] == 0) & (B[:, j] == 1)).sum())
                pm = mcnemar_exact(b_, c_)
                prs.append(dict(a=i + 1, b=j + 1, improved=b_, worsened=c_, p=pm, p_bonf=min(1.0, pm * nb)))
            item.update(n_complete=len(comp), yes_complete=B.sum(0).tolist(), Q=Q, df=df, p=p, pairs=prs)
        cat[bc] = item
    st["binary"] = cat
    st["bmi_cat"] = [[int(((lg.WAVE == w) & (lg.BMICAT == c)).sum()) for c in BMI_CATS] for w in range(1, K + 1)]
    st["vfat_cat"] = [[int(((lg.WAVE == w) & (lg.VFCAT == c)).sum()) for c in VFAT_CATS] for w in range(1, K + 1)]
    return st


def run(path, name=None):
    D = load_data(path, name)
    K, people, long, info, AG = D["K"], D["people"], D["long"], D["info"], D["age_groups"]
    out = dict(info=info, min_n=MIN_N, strata={}, interaction={}, chisq=[], attrition={})
    out["fields"] = dict(
        main=[dict(code=k, name=v[0], unit=v[1], dec=v[2], good=v[3], note=v[4]) for k, v in MAIN.items()],
        seg=[dict(code=k, name=v[0], unit=v[1], dec=v[2], good=v[3]) for k, v in SEG.items()],
        binary=[dict(code=k, name=v[0]) for k, v in BINARY.items()],
        bmi_cats=BMI_CATS, vfat_cats=VFAT_CATS)
    out["composition"] = dict(
        sex={SEX_LABEL[k]: int(v) for k, v in people.SEX.value_counts().items()},
        age={k: int(v) for k, v in people.AGEGRP.value_counts().items()},
        age_mean=people.AGE0.mean(), age_sd=people.AGE0.std(), age_min=int(people.AGE0.min()), age_max=int(people.AGE0.max()),
        complete_by=dict(sex={SEX_LABEL[s]: int(people[(people.SEX == s)].COMPLETE.sum()) for s in ["M", "F"]},
                         age={g: int(people[people.AGEGRP == g].COMPLETE.sum()) for g in AG}))
    for key, label, sex, grp in strata_keys(AG):
        st = stratum_analysis(D, sex, grp, full=(key == "all" or "|" not in key))
        st["label"] = label
        out["strata"][key] = st
    # 交互作用（全部可用資料；MIXED）
    lg = long.copy()
    for c in MAIN:
        out["interaction"][c] = dict(sex=mixed_time(lg, c, K, group="SEX"), age=mixed_time(lg, c, K, group="AGEGRP"))
    # 各波卡方：風險分類 × 性別／年齡層
    for w in range(1, K + 1):
        ww = long[long.WAVE == w]
        for bc, (bname, _) in BINARY.items():
            for var, labels, vals in [("SEX", ["男性", "女性"], ["M", "F"]), ("AGEGRP", AG, AG)]:
                tab = [[int(((ww[var] == v) & (ww[bc] == 1)).sum()), int(((ww[var] == v) & (ww[bc] == 0)).sum())] for v in vals]
                res = chisq_table(tab, labels, ["是", "否"])
                res.update(wave=w, outcome=bc, outcome_name=bname, by="性別" if var == "SEX" else "年齡層")
                out["chisq"].append(res)
    # 流失分析：T1 受測者中，完成全部波次 vs 未完成（比較 T1 值）
    t1 = D["by_wave"][1]
    flag = people.loc[t1.index, "COMPLETE"] == 1
    att = []
    for c in ["AGE", "WEIGHT", "BMI", "FATP", "PMM", "VFATL"]:
        x, y = t1.loc[flag, c], t1.loc[~flag, c]
        t = stats.ttest_ind(x, y, equal_var=False) if len(x) > 1 and len(y) > 1 else None
        att.append(dict(code=c, name={"AGE": "年齡", **{k: v[0] for k, v in MAIN.items()}}[c],
                        unit={"AGE": "歲", **{k: v[1] for k, v in MAIN.items()}}[c],
                        n1=int(len(x)), m1=x.mean(), s1=x.std(), n0=int(len(y)), m0=y.mean() if len(y) else None,
                        s0=y.std() if len(y) > 1 else None, t=t.statistic if t else None, df=t.df if t else None, p=t.pvalue if t else None))
    tab = [[int(((t1.SEX == s) & flag).sum()), int(((t1.SEX == s) & ~flag).sum())] for s in ["M", "F"]]
    out["attrition"] = dict(n_completed=int(flag.sum()), n_dropped=int((~flag).sum()), vars=att,
                            sex=chisq_table(tab, ["男性", "女性"], ["完成全部波次", "未完成"]))
    # 基線（T1）與最近一波現況
    def status(ww):
        n = len(ww)
        return dict(n=n, bmi_cat=[int((ww.BMICAT == c).sum()) for c in BMI_CATS], vfat_cat=[int((ww.VFCAT == c).sum()) for c in VFAT_CATS],
                    binary={bc: int(ww[bc].sum()) for bc in BINARY},
                    binary_by_sex={bc: {s: [int(ww.loc[ww.SEX == s, bc].sum()), int((ww.SEX == s).sum())] for s in ["M", "F"]} for bc in BINARY},
                    hidden_fat=int(((ww.BMI < 24) & (ww.fat == 1)).sum()))
    out["status"] = [status(D["by_wave"][w]) for w in range(1, K + 1)]
    out = clean(out)
    out["evaluation"] = build_evaluation(out)
    return D, out


# ---------------------------------------------------------------- 總體評價（依國民健康署標準）
def pfmt(p):
    return "—" if p is None else "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def sex_gap(o, outcome, wave=1):
    for x in o["chisq"]:
        if x["wave"] == wave and x["outcome"] == outcome and x["by"] == "性別" and x["p"] is not None:
            p = x["p_fisher"] if x.get("use_fisher") else x["p"]
            if p is not None and p < ALPHA:
                (m1, m0), (f1, f0) = x["observed"]
                pm, pf = 100 * m1 / (m1 + m0), 100 * f1 / (f1 + f0)
                hi, lo = (("男性", pm), ("女性", pf)) if pm >= pf else (("女性", pf), ("男性", pm))
                return f"{hi[0]}比例（{hi[1]:.1f}%）顯著高於{lo[0]}（{lo[1]:.1f}%），{pfmt(p)}。"
    return ""


def build_evaluation(o):
    info, K = o["info"], o["info"]["k"]
    b, last = o["status"][0], o["status"][-1]
    n = b["n"]
    pct = lambda k, nn=n: 100 * k / nn if nn else 0
    ow, ob, fat, vf = (b["binary"][k] for k in ("ow", "ob", "fat", "vfat"))
    lastw = f"T{K}"
    trail = lambda k: f"；{lastw}（{last['n']} 人）為 {pct(last['binary'][k], last['n']):.1f}%"
    findings = []
    lvl = "high" if pct(ow) >= 50 else "mid" if pct(ow) >= 30 else "low"
    findings.append(dict(title="體位（BMI）", level=lvl, text=(
        f"T1（{n} 人）BMI ≥ 24（過重或肥胖）{ow} 人（{pct(ow):.1f}%），其中 BMI ≥ 27（肥胖）{ob} 人（{pct(ob):.1f}%）"
        f"{trail('ow')}。" + sex_gap(o, "ow"))))
    bs = b["binary_by_sex"]["fat"]
    lvl = "high" if pct(fat) >= 50 else "mid" if pct(fat) >= 30 else "low"
    findings.append(dict(title="體脂肪率", level=lvl, text=(
        f"依國民健康署標準（男性 ≥ 25%、女性 ≥ 30% 屬肥胖），T1 體脂肪率超標 {fat} 人（{pct(fat):.1f}%；"
        f"男性 {bs['M'][0]}/{bs['M'][1]}、女性 {bs['F'][0]}/{bs['F'][1]}）{trail('fat')}。"
        + (f"T1 有 {b['hidden_fat']} 人 BMI 未達 24 但體脂肪率已超標（俗稱「隱性肥胖」），不宜僅以體重判斷。" if b["hidden_fat"] else ""))))
    lvl = "high" if pct(vf) >= 40 else "mid" if pct(vf) >= 20 else "low"
    findings.append(dict(title="內臟脂肪", level=lvl, text=(
        f"T1 內臟脂肪等級 ≥ 10（TANITA 原廠「偏高」標準）{vf} 人（{pct(vf):.1f}%），其中 ≥ 15 者 {b['vfat_cat'][2]} 人"
        f"{trail('vfat')}。" + sex_gap(o, "vfat")
        + "內臟脂肪與代謝症候群風險相關，國健署建議以腰圍輔助評估（男性 ≥ 90 cm、女性 ≥ 80 cm 為腹部肥胖），本次未測腰圍。")))
    # 變化
    allst = o["strata"]["all"]
    sig, fav_any, unfav_any = [], False, False
    if "rm" in allst:
        for c, (name, unit, dec, good, _) in MAIN.items():
            s = allst["rm"][c]
            if s.get("p_final") is not None and s["p_final"] < ALPHA:
                d = s["means"][-1] - s["means"][0]
                tag = "" if good == 0 else ("（有利）" if np.sign(d) == good else "（不利）")
                fav_any |= tag == "（有利）"
                unfav_any |= tag == "（不利）"
                sig.append(f"{name}（T1 {s['means'][0]:.{max(dec, 1)}f} → {lastw} {s['means'][-1]:.{max(dec, 1)}f} {unit}{tag}，{pfmt(s['p_final'])}）")
        mixed_sig = [MAIN[c][0] for c in MAIN if (allst["mixed"].get(c) or {}).get("p", 1) < ALPHA]
        rm_sig = [MAIN[c][0] for c in MAIN if allst["rm"][c].get("p_final", 1) < ALPHA]
        txt = (f"完成全部 {K} 次量測者 {info['n_complete']} 人（重複測量 ANOVA）。"
               + ("隨時間有顯著變化的指標：" + "；".join(sig) + "。" if sig else "各項指標在三次量測間均未達統計顯著變化。"))
        extra = sorted(set(mixed_sig) - set(rm_sig))
        missing = sorted(set(rm_sig) - set(mixed_sig))
        if extra:
            txt += f"納入全部可用資料的混合模型另顯示{'、'.join(extra)}有顯著變化，可作為補充參考。"
        if missing:
            txt += f"但{'、'.join(missing)}在混合模型中未達顯著，結論宜保守。"
        # 分層：組內顯著變化、時間 × 分組交互作用
        strat = []
        for key, st in o["strata"].items():
            if key == "all" or "|" in key or "rm" not in st:
                continue
            hits = [MAIN[c][0] for c in MAIN if st["rm"][c].get("p_final", 1) < ALPHA]
            if hits:
                strat.append(f"{st['label']}（{st['n_complete']} 人）的{'、'.join(hits)}")
        if strat:
            txt += "分層檢定中，" + "；".join(strat) + "隨時間有顯著變化。"
        inter = []
        for by, lab in (("sex", "性別"), ("age", "年齡層")):
            hits = [MAIN[c][0] for c in MAIN if (o["interaction"][c].get(by) or {}).get("p", 1) < ALPHA]
            if hits:
                inter.append(f"{'、'.join(hits)}的變化趨勢在不同{lab}之間有差異（時間 × {lab}交互作用 p < 0.05）")
        if inter:
            txt += "；".join(inter) + "，詳見分層分析。"
        if info["intervals"] and min(info["intervals"]) < 30:
            short = [f"T{i + 1}→T{i + 2}（{d} 天）" for i, d in enumerate(info["intervals"]) if d < 30]
            txt += f"另{'、'.join(short)}間隔較短，體組成變化有限屬預期。"
    else:
        txt = f"完成全部 {K} 次量測者僅 {info['n_complete']} 人，人數不足，未進行重複測量檢定。"
    lvl = "low" if fav_any and not unfav_any else "high" if unfav_any and not fav_any else "mid"
    findings.append(dict(title="多次量測變化", level=lvl, text=txt))
    score = sum({"high": 2, "mid": 1, "low": 0}[f["level"]] for f in findings[:3])
    overall = "需優先介入" if score >= 4 else "需持續關注" if score >= 2 else "整體良好"
    rule = ("依 T1 三項風險分類盛行率判定：BMI ≥ 24 與體脂肪率超標比例 ≥ 50% 為「需介入」、30–49% 為「需關注」；"
            "內臟脂肪偏高比例 ≥ 40% 為「需介入」、20–39% 為「需關注」。需介入計 2 分、需關注計 1 分，"
            "合計 ≥ 4 分為「需優先介入」、2–3 分為「需持續關注」、0–1 分為「整體良好」。此分級為本報告自訂之彙整方式，非國健署公告分級。")
    recs = [
        dict(title="健康體重管理", text="依國健署「聰明吃、快樂動、天天量體重」原則；BMI ≥ 24 者以每週減重 0.5–1 公斤為目標，避免快速減重造成肌肉流失。"),
        dict(title="均衡飲食", text="依國健署「我的餐盤」六口訣：每天早晚一杯奶、每餐水果拳頭大、菜比水果多一點、飯跟蔬菜一樣多、豆魚蛋肉一掌心、堅果種子一茶匙；減少含糖飲料與高油加工食品。"),
        dict(title="規律身體活動", text="成人每週累積至少 150 分鐘中等費力身體活動（或 75 分鐘費力身體活動），並每週至少 2 天進行肌力訓練，有助於降低體脂並維持肌肉量。"),
        dict(title="職場支持措施", text="建議職場推動減少久坐（每坐 1 小時起身活動）、提供健康餐飲選項及團體運動課程，並將腰圍納入下次量測，以完整評估腹部肥胖。"),
        dict(title="提升追蹤完整度", text=f"本次完成全部 {K} 次量測者占 {100 * info['n_complete'] / info['n_people']:.0f}%。建議固定量測時段（空腹、未運動、排尿後），並提醒員工每次皆參加，以提高追蹤成效的可信度。"),
    ]
    return dict(overall=overall, rule=rule, findings=findings, recommendations=recs,
                sources=["衛生福利部國民健康署「成人健康體位標準」（BMI、腰圍、體脂肪率）",
                         "衛生福利部國民健康署「每日飲食指南」及「我的餐盤」（107 年版）",
                         "衛生福利部國民健康署 身體活動建議（成人每週 150 分鐘中等費力身體活動、每週 2 天肌力訓練）",
                         "內臟脂肪等級分級為 TANITA 原廠標準（非國健署公告）"])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else None
    if name in args:
        args.remove(name)
    outdir = Path(args[1] if len(args) > 1 else Path(__file__).parent / "output")
    outdir.mkdir(parents=True, exist_ok=True)
    _, res = run(args[0], name)
    (outdir / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["info"], ensure_ascii=False))


if __name__ == "__main__":
    main()
