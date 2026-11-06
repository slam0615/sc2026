"""臺北市 12 週健康促進介入計畫 — TANITA MC-780 身體組成成果分析。

用法：
    python analyze.py <GMON匯出.xls> [輸出資料夾] [--name 職場名稱]

輸入可為 GMON 原始英文欄位，或已翻成中文欄名的版本。
量測次別依測量日分群（相隔超過 WAVE_GAP_DAYS 天為新的一次）：第 1 次＝前測、第 2 次＝後測、第 3 次＝追蹤測。

分析（皆為 SPSS 可重現的程序）：
    主分析：三次皆參加者 — 重複測量 ANOVA（GLM REPEATED；Mauchly、Greenhouse-Geisser、Bonferroni、偏 η²）＋ Friedman
    兩次參加者也納入：前測→後測、前測→追蹤測，以兩次皆有量測者做配對 t 檢定（T-TEST PAIRS）＋ Wilcoxon
    分類變項：Cochran's Q、McNemar 精確檢定；各次 Pearson 卡方／Fisher 精確檢定
    分層：性別、年齡層（≤40、41–50、≥51 歲）、前測體位（BMI ≥ 24 / < 24）各自分析；組間趨勢差異以混合設計 ANOVA
          之「時間 × 分組」交互作用檢定（GLM REPEATED … BY 分組）；年齡層的比例另以線性趨勢檢定（linear-by-linear）
    個人變化：前測→最後一次量測的改善／持平／變差人數、體重減少 ≥ 3%／≥ 5% 的比例
    效果量：配對比較的 Cohen's dz
    敏感度分析：線性混合模型（MIXED，隨機截距），納入所有至少量測一次者
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
from scipy import stats

warnings.filterwarnings("ignore")

PROGRAM_TITLE = "臺北市12週健康促進介入計畫-成果報告"
PROGRAM_WEEKS = 12
MIN_N = 10          # 分析人數低於此值不呈現（避免小群體可推測個人）
ALPHA = 0.05
KJ_PER_KCAL = 4.184
WAVE_GAP_DAYS = 7   # 測量日相隔超過此天數才算新的一次（同一次可跨數天）
WAVE_NAMES = {2: ["前測", "後測"], 3: ["前測", "後測", "追蹤測"]}

# ---------------------------------------------------------------- 欄位定義
# code: (中文名稱, 單位, 小數位, 期望方向 -1=下降有利 / +1=上升有利 / 0=不判定, 說明)
MAIN = {
    # BMI、體重只呈現方向（0）：上升可能來自增肌、下降可能來自肌肉流失，好壞改由身體組成（脂肪量、肌肉量）判定
    "BMI":    ("BMI", "kg/m²", 1, 0, "身體質量指數＝體重(kg) ÷ 身高(m)²；變化只看方向，好壞以身體組成判定"),
    "WEIGHT": ("體重", "kg", 1, 0, "已扣除衣物重量；變化只看方向，好壞以身體組成判定"),
    "FATP":   ("體脂率", "%", 1, -1, "體脂肪量占體重的百分比"),
    "PMM":    ("總體肌肉量", "kg", 1, +1, "TANITA 推定肌肉量（含骨骼肌、平滑肌及其水分）"),
    "VFATL":  ("內臟脂肪等級", "等級", 0, -1, "TANITA 原廠等級（1–59）；1–9 標準、10–14 偏高、≥15 過高"),
}
REQUIRED = ["CUSTOMERID", "DATETIME", "SEX", "AGE", "HEIGHT", *MAIN]

OTHER_FIELDS = {  # 僅作欄位對照、不進入統計
    "CUSTOMERID": ("受測者編號", "", "已於報告中移除"),
    "SEX": ("性別", "M/F", "M=男、F=女"),
    "DATETIME": ("測量日期時間", "", "用於判定量測次別"),
    "AGE": ("年齡", "歲", "以首次量測年齡分組"),
    "HEIGHT": ("身高", "cm", "用於檢查編號一致性"),
    "MODEL": ("機型", "", "MC-780"),
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

# 年齡層（以首次量測年齡；固定分組，21 家一致）
AGE_BINS = [(0, 40, "≤40"), (41, 50, "41-50"), (51, 200, "≥51")]
AGE_GROUPS = [b[2] for b in AGE_BINS]
SEX_LABEL = {"M": "男性", "F": "女性"}
RISK_LABEL = {1: "前測 BMI ≥ 24", 0: "前測 BMI < 24"}
BMI_CATS = ["過輕", "正常", "過重", "肥胖"]
# 個人變化的「持平」範圍：rel＝相對前測的比例、abs＝原單位；變化量達門檻才算改善或變差
CHANGE_THRESH = {"BMI": ("rel", 0.01), "WEIGHT": ("rel", 0.01), "FATP": ("abs", 1.0), "PMM": ("rel", 0.01), "VFATL": ("abs", 1.0)}
WEIGHT_LOSS_TARGETS = [3, 5]   # 體重減少 ≥ 3%、≥ 5%
EPS = 1e-9                      # 邊界比較的容許誤差（Excel、SPSS 用同一值）
# 身體組成變化類型：脂肪量（體重 × 體脂率 ÷ 100）與總體肌肉量的變化，各以 ±COMP_THRESH kg 判定增加／持平／減少
COMP_THRESH = 0.5
COMP_TYPES = [  # (代碼, 名稱, 判讀, 說明)
    ("fat_loss", "減脂保肌", "good", "脂肪量減少，肌肉量持平或增加"),
    ("muscle_gain", "增肌", "good", "脂肪量持平，肌肉量增加"),
    ("stable", "持平", "neutral", "脂肪量、肌肉量變化皆小於門檻"),
    ("both_down", "脂肪、肌肉皆減少", "mixed", "減重但伴隨肌肉流失"),
    ("both_up", "脂肪、肌肉皆增加", "mixed", "體重上升，肌肉與脂肪皆增加"),
    ("muscle_loss", "肌肉流失", "bad", "脂肪量持平，肌肉量減少"),
    ("fat_gain", "增脂", "bad", "脂肪量增加，肌肉量持平或減少"),
]


def comp_type(f, m):
    """f、m：脂肪量、肌肉量的變化方向（−1 減少／0 持平／1 增加）。"""
    if f == -1:
        return "both_down" if m == -1 else "fat_loss"
    if f == 1:
        return "both_up" if m == 1 else "fat_gain"
    return "muscle_gain" if m == 1 else "muscle_loss" if m == -1 else "stable"


def tri(d, thr):
    return 1 if d >= thr - EPS else -1 if d <= -thr + EPS else 0
VFAT_CATS = ["標準 (1–9)", "偏高 (10–14)", "過高 (≥15)"]


def age_group(a):
    for lo, hi, lab in AGE_BINS:
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
    "fat":  ("體脂率超標 (男 ≥25%、女 ≥30%)", lambda r: fat_over(r["SEX"], r["FATP"])),
    "vfat": ("內臟脂肪偏高 (等級 ≥ 10)", lambda r: int(r["VFATL"] >= 10)),
}


def wave_names(K):
    return WAVE_NAMES.get(K, [f"第 {i} 次" for i in range(1, K + 1)])


# ---------------------------------------------------------------- 資料
def load_data(path, name=None, by_group=False):
    raw = pd.read_excel(path)
    raw = raw.rename(columns={c: ZH_COLUMNS.get(str(c).strip(), c) for c in raw.columns})
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise SystemExit(f"找不到必要欄位：{missing}")
    d = raw.copy()
    d["DATETIME"] = pd.to_datetime(d["DATETIME"])
    d["DATE"] = d["DATETIME"].dt.normalize()
    for code, meta in MAIN.items():
        d[code] = d[code].astype(float).round(meta[2])
    log = []
    def cluster(dates):
        dates = sorted(dates)
        wave_of, waves = {dates[0]: 1}, [[dates[0]]]
        for prev, cur in zip(dates, dates[1:]):
            if (pd.Timestamp(cur) - pd.Timestamp(prev)).days > WAVE_GAP_DAYS:
                waves.append([])
            waves[-1].append(cur)
            wave_of[cur] = len(waves)
        return wave_of, waves

    if by_group:
        # 整體分析（多職場合併檔）：各職場（GROUP1）分別依測量日分群，再依次別合併
        if "GROUP1" not in d or d["GROUP1"].isna().any():
            raise SystemExit("整體分析需要每筆資料都有 GROUP1（職場）欄位")
        if (d.groupby("CUSTOMERID")["GROUP1"].nunique() > 1).any():
            raise SystemExit("有編號同時出現在不同職場，請檢查 CUSTOMERID")
        gw = {}
        for gname, sub in d.groupby("GROUP1"):
            wo, ws = cluster(sub["DATE"].unique())
            gw[gname] = ws
            d.loc[sub.index, "WAVE"] = sub["DATE"].map(wo)
        d["WAVE"] = d["WAVE"].astype(int)
        Ks = {g: len(ws) for g, ws in gw.items()}
        K = max(Ks.values())
        names = wave_names(K)
        bad = [f"{g}（{k} 次）" for g, k in Ks.items() if k != 3]
        if bad:
            log.append(f"警告：{'、'.join(bad)}量測次數不是 3 次，請確認量測日期")
        for g, ws in gw.items():
            log.append(f"{g}：" + "、".join(f"{names[i]} {pd.Timestamp(w[0]).date()}" + (f"～{pd.Timestamp(w[-1]).date()}" if len(w) > 1 else "")
                                            for i, w in enumerate(ws)))
        waves = [sorted(x for ws in gw.values() if len(ws) > i for x in ws[i]) for i in range(K)]
        days = [round(float(np.mean([(pd.Timestamp(ws[i][0]) - pd.Timestamp(ws[0][0])).days for ws in gw.values() if len(ws) > i]))) for i in range(K)]
        info_extra = dict(pooled=True, n_groups=len(gw), groups={g: [str(pd.Timestamp(w[0]).date()) for w in ws] for g, ws in gw.items()})
    else:
        wave_of, waves = cluster(d["DATE"].unique())
        d["WAVE"] = d["DATE"].map(wave_of)
        K = len(waves)
        names = wave_names(K)
        if K != 3:
            log.append(f"警告：資料共有 {K} 次量測（預期為前測、後測、追蹤測 3 次），請確認量測日期")
        for i, ws in enumerate(waves):
            if len(ws) > 1:
                log.append(f"{names[i]}包含 {len(ws)} 個測量日（{pd.Timestamp(ws[0]).date()}～{pd.Timestamp(ws[-1]).date()}），合併為同一次")
        days = [int((pd.Timestamp(ws[0]) - pd.Timestamp(waves[0][0])).days) for ws in waves]
        info_extra = dict(pooled=False)
    if K < 2:
        raise SystemExit("只有一次量測，無法比較變化")
    dup = d.duplicated(["CUSTOMERID", "WAVE"], keep=False)
    if dup.any():
        log.append(f"{d[dup].groupby(['CUSTOMERID', 'WAVE']).ngroups} 人次於同一次量測重複測量，保留最後一筆")
    d = d.sort_values("DATETIME").drop_duplicates(["CUSTOMERID", "WAVE"], keep="last")
    g = d.groupby("CUSTOMERID")
    if (g["SEX"].nunique() > 1).any():
        log.append(f"警告：{int((g['SEX'].nunique() > 1).sum())} 人性別前後不一致，請檢查編號")
    if (g["HEIGHT"].agg(lambda s: s.max() - s.min()) > 2).any():
        log.append(f"警告：{int((g['HEIGHT'].agg(lambda s: s.max() - s.min()) > 2).sum())} 人身高差異超過 2 cm，請檢查編號")
    first = d.sort_values("DATETIME").groupby("CUSTOMERID").first()
    d["AGE0"] = d["CUSTOMERID"].map(first["AGE"])
    d["AGEGRP"] = d["AGE0"].map(age_group)
    d["SEX"] = d["CUSTOMERID"].map(first["SEX"])
    for bc, (_, fn) in BINARY.items():
        d[bc] = d.apply(fn, axis=1)
    d["BMICAT"] = d["BMI"].map(bmi_cat)
    d["VFCAT"] = d["VFATL"].map(vfat_cat)
    people = first[["SEX"]].copy()
    people["AGE0"] = first["AGE"]
    people["AGEGRP"] = people["AGE0"].map(age_group)
    present = d.pivot_table(index="CUSTOMERID", columns="WAVE", values="WEIGHT", aggfunc="size").reindex(columns=range(1, K + 1)).notna()
    people["PATTERN"] = present.apply(lambda r: "→".join(names[w - 1] for w in range(1, K + 1) if r[w]), axis=1)
    people["COMPLETE"] = present.all(axis=1).astype(int)
    for w in range(1, K + 1):
        people[f"HAS{w}"] = present[w].astype(int)
    # 分析對象：三次皆參加（complete）；前測＋後測或追蹤測其一（two）；其餘不納入分析
    nwaves = present.sum(axis=1)
    people["GROUP"] = np.where(people.COMPLETE == 1, "complete",
                               np.where((people.HAS1 == 1) & (nwaves == 2), "two", "excluded"))
    people["TWO"] = (people.GROUP == "two").astype(int)
    people["POSTWAVE"] = [int(max(w for w in range(2, K + 1) if present.loc[i, w])) if people.loc[i, "GROUP"] == "two" else 0
                          for i in people.index]
    all_patterns = people.PATTERN.value_counts()
    excluded = people[people.GROUP == "excluded"]
    if len(excluded):
        log.append(f"未參加前測或只量測一次者 {len(excluded)} 人（{'、'.join(f'{p} {n} 人' for p, n in excluded.PATTERN.value_counts().items())}）不納入分析")
    people_all, long_all = people.copy(), d.copy()   # 敏感度分析（混合模型）用：所有至少量測一次者
    people = people[people.GROUP != "excluded"]
    d = d[d.CUSTOMERID.isin(people.index)]
    base_ow = d[d.WAVE == 1].set_index("CUSTOMERID")["ow"]
    people["RISK0"] = people.index.map(base_ow).astype(int)   # 前測體位：1＝BMI ≥ 24
    by_wave = {w: d[d.WAVE == w].set_index("CUSTOMERID") for w in range(1, K + 1)}
    workplace = name or (str(raw["GROUP1"].dropna().iloc[0]) if "GROUP1" in raw and raw["GROUP1"].notna().any() else Path(path).stem)
    info = dict(
        title=PROGRAM_TITLE, program_weeks=PROGRAM_WEEKS, workplace=workplace,
        model=str(raw["MODEL"].dropna().iloc[0]) if "MODEL" in raw else "MC-780", k=K,
        waves=[dict(code=f"T{i + 1}", label=names[i], date=str(pd.Timestamp(ws[0]).date()), date_end=str(pd.Timestamp(ws[-1]).date()),
                    day=int(days[i]), week=int(round(days[i] / 7)),
                    n=int(len(by_wave[i + 1]))) for i, ws in enumerate(waves)],
        intervals=[int(days[i] - days[i - 1]) for i in range(1, K)], **info_extra,
        n_records=int(len(raw)), n_total=int(raw["CUSTOMERID"].nunique()), n_people=int(len(people)),
        n_excluded=int(len(excluded)), n_complete=int(people.COMPLETE.sum()), n_two=int(people.TWO.sum()),
        n_two_by_wave={names[w - 1]: int((people.POSTWAVE == w).sum()) for w in range(2, K + 1)},
        patterns=[dict(pattern=p, n=int(n), waves=p.count("→") + 1,
                       group=("complete" if p.count("→") + 1 == K else "two" if p.startswith(names[0]) and p.count("→") == 1 else "excluded"))
                  for p, n in all_patterns.items()],
        cleaning_log=log, age_groups=AGE_GROUPS, age_n={gname: int((people.AGEGRP == gname).sum()) for gname in AGE_GROUPS},
    )
    order = {nm: i for i, nm in enumerate(names)}
    info["patterns"].sort(key=lambda x: (-x["waves"], [order[t] for t in x["pattern"].split("→")]))
    small = [f"{a} 歲（{n} 人）" for a, n in info["age_n"].items() if 0 < n < MIN_N]
    if small:
        log.append(f"年齡層 {'、'.join(small)}人數少於 {MIN_N} 人，不單獨呈現統計結果（仍計入全體）")
    info["risk_n"] = {str(k): int((people.RISK0 == k).sum()) for k in (1, 0)}
    return dict(raw=raw, long=d, people=people, by_wave=by_wave, info=info, K=K, names=names, long_all=long_all, people_all=people_all)


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
    out.update(mean_a=a.mean(), mean_b=b.mean(), diff=md, sd=sd, se=se, t=md / se if sd > 0 else 0.0, df=n - 1, p=p, p_bonf=min(1.0, p * bonf),
               dz=md / sd if sd > 0 else 0.0,
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
    res["p_decide"] = res["p_fisher"] if res["use_fisher"] and res["p_fisher"] is not None else res["p"]
    res["method"] = "Fisher" if res["use_fisher"] and res["p_fisher"] is not None else "卡方"
    return res


def linear_trend(tab, scores):
    """線性趨勢檢定（SPSS CROSSTABS 的 Linear-by-Linear Association）：M² = (N−1)r²，df = 1。
    tab 每列為 [是, 否]，scores 為各列的分組分數（年齡層代碼）。"""
    tab = np.asarray(tab, float)
    x = np.repeat(np.asarray(scores, float), 2)
    y = np.tile([1.0, 0.0], len(tab))
    w = tab.ravel()
    N = w.sum()
    sx, sy, sxx, sxy = (w * x).sum(), (w * y).sum(), (w * x * x).sum(), (w * x * y).sum()
    den = (N * sxx - sx ** 2) * (N * sy - sy ** 2)
    if N < 2 or den <= 0:
        return dict(r=None, m2=None, p_trend=None)
    rr = (N * sxy - sx * sy) / math.sqrt(den)
    m2 = (N - 1) * rr ** 2
    return dict(r=rr, m2=m2, p_trend=stats.chi2.sf(m2, 1))


def mixed_anova_interaction(Y, groups):
    """混合設計 ANOVA 的「時間 × 分組」交互作用（同 SPSS GLM REPEATED … BY 分組；完成全部量測者）。"""
    Y = np.asarray(Y, float)
    groups = np.asarray(groups)
    levels = [g for g in pd.unique(groups)]
    n, k = Y.shape
    G = len(levels)
    if G < 2 or n - G < 2:
        return None
    M = helmert(k)
    Z = Y @ M
    p = k - 1
    zbar = Z.mean(0)
    H = np.zeros((p, p))
    E = np.zeros((p, p))
    for lv in levels:
        Zg = Z[groups == lv]
        dg = Zg.mean(0) - zbar
        H += len(Zg) * np.outer(dg, dg)
        R = Zg - Zg.mean(0)
        E += R.T @ R
    df1, df2 = p * (G - 1), p * (n - G)
    F = (np.trace(H) / df1) / (np.trace(E) / df2)
    pv = stats.f.sf(F, df1, df2)
    eps = np.trace(E) ** 2 / (p * np.trace(E @ E))
    S = E / (n - G)
    if p > 1:
        W = np.linalg.det(S) / (np.trace(S) / p) ** p
        chi = -((n - G) - (2 * p ** 2 + p + 2) / (6 * p)) * math.log(W)
        p_m = stats.chi2.sf(chi, p * (p + 1) / 2 - 1)
    else:
        W, chi, p_m = 1.0, None, None
    p_gg = stats.f.sf(F, df1 * eps, df2 * eps)
    use_gg = p_m is not None and p_m < ALPHA
    return dict(n=n, groups=[str(x) for x in levels], F=F, df1=df1, df2=df2, p=pv, eps_gg=eps, p_gg=p_gg,
                mauchly_p=p_m, use_gg=use_gg, p_final=p_gg if use_gg else pv,
                pes=np.trace(H) / (np.trace(H) + np.trace(E)))


# ---------------------------------------------------------------- 分析
def strata_keys(by_sex=True):
    keys = [("all", "全體", None, None)]
    if by_sex:
        keys += [(f"sex:{s}", SEX_LABEL[s], s, None) for s in ["M", "F"]]
    keys += [(f"age:{g}", f"{g} 歲", None, g) for g in AGE_GROUPS]
    if by_sex:
        keys += [(f"sex:{s}|age:{g}", f"{SEX_LABEL[s]}・{g} 歲", s, g) for s in ["M", "F"] for g in AGE_GROUPS]
    return [k + (None,) for k in keys] + [(f"risk:{v}", RISK_LABEL[v], None, None, v) for v in (1, 0)]


def change_class(a, b, code):
    """個人變化分類：1＝改善（BMI、體重為下降）、0＝持平、−1＝變差（BMI、體重為上升）。"""
    kind, thr = CHANGE_THRESH[code]
    good = MAIN[code][3] or -1
    d = (b - a) / a if kind == "rel" else b - a
    if d * good >= thr - EPS:
        return 1
    if d * good <= -thr + EPS:
        return -1
    return 0


def indiv_change(a_vals, b_vals):
    """a_vals、b_vals：{指標: 陣列}（同一批人的前測與比較次）。"""
    n = len(a_vals["WEIGHT"])
    out = dict(n=n)
    if n < MIN_N:
        return out
    for code in MAIN:
        cl = [change_class(a, b, code) for a, b in zip(a_vals[code], b_vals[code])]
        out[code] = (dict(improve=cl.count(1), stable=cl.count(0), worse=cl.count(-1)) if MAIN[code][3]
                     else dict(down=cl.count(1), stable=cl.count(0), up=cl.count(-1)))
    wa, wb = np.asarray(a_vals["WEIGHT"], float), np.asarray(b_vals["WEIGHT"], float)
    dF = (wb * np.asarray(b_vals["FATP"], float) - wa * np.asarray(a_vals["FATP"], float)) / 100
    dM = np.asarray(b_vals["PMM"], float) - np.asarray(a_vals["PMM"], float)
    fm = [tri(x, COMP_THRESH) for x in dF]
    mm = [tri(x, COMP_THRESH) for x in dM]
    types = [comp_type(f, m) for f, m in zip(fm, mm)]
    out["comp"] = {k: types.count(k) for k, *_ in COMP_TYPES}
    out["comp_group"] = {g: sum(out["comp"][k] for k, _, gg, _ in COMP_TYPES if gg == g) for g in ("good", "neutral", "mixed", "bad")}
    out["fat_mass_mean"] = float(dF.mean())
    out["muscle_mean"] = float(dM.mean())
    pct = (wb - wa) / wa * 100
    out["weight_loss"] = {str(t): int((pct <= -t + EPS).sum()) for t in WEIGHT_LOSS_TARGETS}
    out["weight_loss_keep"] = {str(t): int(((pct <= -t + EPS) & (np.asarray(mm) >= 0)).sum()) for t in WEIGHT_LOSS_TARGETS}
    out["weight_pct_mean"] = float(pct.mean())
    return out


def stratum_analysis(D, sex, grp, risk=None):
    K, people, long = D["K"], D["people"], D["long"]
    ids = people.index
    if sex:
        ids = ids[people.loc[ids, "SEX"] == sex]
    if grp:
        ids = ids[people.loc[ids, "AGEGRP"] == grp]
    if risk is not None:
        ids = ids[people.loc[ids, "RISK0"] == risk]
    comp = ids[people.loc[ids, "COMPLETE"] == 1]
    two = ids[people.loc[ids, "TWO"] == 1]
    post_wave = people.loc[two, "POSTWAVE"]
    lg = long[long.CUSTOMERID.isin(ids)]
    st = dict(n=int(len(ids)), n_complete=int(len(comp)), n_two=int(len(two)), n_wave=[int((lg.WAVE == w).sum()) for w in range(1, K + 1)])
    st["suppressed"] = st["n"] < MIN_N
    if st["suppressed"]:
        return st
    st["desc"] = {c: [desc(lg.loc[lg.WAVE == w, c]) if (lg.WAVE == w).sum() >= MIN_N else dict(n=int((lg.WAVE == w).sum()))
                      for w in range(1, K + 1)] for c in MAIN}
    wide = {c: lg.pivot(index="CUSTOMERID", columns="WAVE", values=c).reindex(columns=range(1, K + 1)) for c in MAIN}
    if len(comp) >= MIN_N:
        st["rm"] = {c: rm_anova(wide[c].loc[comp].values) for c in MAIN}
    # 參加兩次者（前測＋後測或追蹤測其一）合併：前測 vs 介入後量測
    post = lambda tab: np.array([tab.loc[i, post_wave[i]] for i in two], float)
    st["two"] = {c: (paired(wide[c].loc[two, 1].values, post(wide[c])) if len(two) >= MIN_N else dict(n=int(len(two)))) for c in MAIN}
    cat = {}
    nb = K * (K - 1) // 2
    for bc in BINARY:
        item = dict(waves=[dict(n=int((lg.WAVE == w).sum()), yes=int(lg.loc[lg.WAVE == w, bc].sum())) for w in range(1, K + 1)])
        B_all = lg.pivot(index="CUSTOMERID", columns="WAVE", values=bc).reindex(columns=range(1, K + 1))
        if len(comp) >= MIN_N:
            B = B_all.loc[comp].values.astype(int)
            Q, df, p = cochran_q(B)
            prs = []
            for i, j in combinations(range(K), 2):
                b_, c_ = int(((B[:, i] == 1) & (B[:, j] == 0)).sum()), int(((B[:, i] == 0) & (B[:, j] == 1)).sum())
                pm = mcnemar_exact(b_, c_)
                prs.append(dict(a=i + 1, b=j + 1, improved=b_, worsened=c_, p=pm, p_bonf=min(1.0, pm * nb)))
            item.update(n_complete=len(comp), yes_complete=B.sum(0).tolist(), Q=Q, df=df, p=p, pairs=prs)
        if len(two) >= MIN_N:
            x0, x1 = B_all.loc[two, 1].values.astype(int), post(B_all).astype(int)
            b_, c_ = int(((x0 == 1) & (x1 == 0)).sum()), int(((x0 == 0) & (x1 == 1)).sum())
            item["two"] = dict(n=int(len(two)), yes_pre=int(x0.sum()), yes_post=int(x1.sum()), improved=b_, worsened=c_, p=mcnemar_exact(b_, c_))
        else:
            item["two"] = dict(n=int(len(two)))
        cat[bc] = item
    st["binary"] = cat
    # 個人變化：三次皆參加者（前測→各次）、參加兩次者（前測→介入後）、全體（前測→最後一次量測）
    last = lambda tab, i: tab.loc[i, K] if i in comp else tab.loc[i, post_wave[i]]
    ind = {}
    for w in range(2, K + 1):
        ind[f"c{w}"] = indiv_change({c: wide[c].loc[comp, 1].values for c in MAIN}, {c: wide[c].loc[comp, w].values for c in MAIN})
    ind["two"] = indiv_change({c: wide[c].loc[two, 1].values for c in MAIN}, {c: post(wide[c]) for c in MAIN})
    inc = list(comp) + list(two)
    ind["last"] = indiv_change({c: wide[c].loc[inc, 1].values for c in MAIN}, {c: np.array([last(wide[c], i) for i in inc], float) for c in MAIN})
    st["indiv"] = ind
    st["bmi_cat"] = [[int(((lg.WAVE == w) & (lg.BMICAT == c)).sum()) for c in BMI_CATS] for w in range(1, K + 1)]
    st["vfat_cat"] = [[int(((lg.WAVE == w) & (lg.VFCAT == c)).sum()) for c in VFAT_CATS] for w in range(1, K + 1)]
    return st


def lmm_sensitivity(D):
    """敏感度分析：線性混合模型（隨機截距，REML；同 SPSS MIXED），納入所有至少量測一次者（含未納入主分析者）。"""
    import statsmodels.formula.api as smf
    K, lg = D["K"], D["long_all"]
    out = dict(n_people=int(lg.CUSTOMERID.nunique()), n_obs=int(len(lg)), n_wave=[int((lg.WAVE == w).sum()) for w in range(1, K + 1)], vars={})
    z = stats.norm.ppf(0.975)
    for c in MAIN:
        df = lg[["CUSTOMERID", "WAVE", c]].dropna().rename(columns={c: "Y"})
        try:
            fit = smf.mixedlm("Y ~ C(WAVE)", df, groups=df["CUSTOMERID"]).fit(reml=True, method=["lbfgs", "bfgs", "nm"])
        except Exception as e:  # noqa: BLE001
            out["vars"][c] = dict(error=str(e))
            continue
        fe = fit.fe_params
        V = fit.cov_params().loc[fe.index, fe.index].values
        b = fe.values
        means, diffs = [], []
        for w in range(1, K + 1):
            Lm = np.zeros(len(b))
            Lm[0] = 1
            if w > 1:
                Lm[w - 1] = 1
            m, se = Lm @ b, math.sqrt(Lm @ V @ Lm)
            means.append(dict(mean=m, se=se, ci_lo=m - z * se, ci_hi=m + z * se))
            if w > 1:
                d, sd = b[w - 1], math.sqrt(V[w - 1, w - 1])
                diffs.append(dict(b=w, diff=d, se=sd, ci_lo=d - z * sd, ci_hi=d + z * sd, p=2 * stats.norm.sf(abs(d / sd))))
        bb, VV = b[1:], V[1:, 1:]
        wald = float(bb @ np.linalg.solve(VV, bb))
        out["vars"][c] = dict(means=means, diffs=diffs, wald_chi2=wald, df=K - 1, p=stats.chi2.sf(wald, K - 1),
                              var_subject=float(fit.cov_re.iloc[0, 0]), var_resid=float(fit.scale), converged=bool(fit.converged))
    return out


def run(path, name=None, by_sex=True, by_group=False):
    """by_sex=False：不做性別分層、時間 × 性別交互作用與性別卡方（使用者指定的職場，例如性別幾乎單一）。"""
    D = load_data(path, name, by_group=by_group)
    K, people, long, info = D["K"], D["people"], D["long"], D["info"]
    info["by_sex"] = by_sex
    out = dict(info=info, min_n=MIN_N, strata={}, interaction={}, chisq=[], attrition={})
    out["fields"] = dict(main=[dict(code=k, name=v[0], unit=v[1], dec=v[2], good=v[3], note=v[4]) for k, v in MAIN.items()],
                         binary=[dict(code=k, name=v[0]) for k, v in BINARY.items()], bmi_cats=BMI_CATS, vfat_cats=VFAT_CATS)
    out["composition"] = dict(age_mean=people.AGE0.mean(), age_sd=people.AGE0.std(), age_min=int(people.AGE0.min()), age_max=int(people.AGE0.max()))
    for key, label, sex, grp, risk in strata_keys(by_sex):
        st = stratum_analysis(D, sex, grp, risk)
        st["label"] = label
        out["strata"][key] = st
    # 時間 × 性別、時間 × 年齡層 交互作用（完成全部量測者；混合設計 ANOVA）
    comp = people[people.COMPLETE == 1]
    for c in MAIN:
        Y = long[long.CUSTOMERID.isin(comp.index)].pivot(index="CUSTOMERID", columns="WAVE", values=c).reindex(columns=range(1, K + 1)).loc[comp.index].values
        out["interaction"][c] = dict(sex=mixed_anova_interaction(Y, comp.SEX.values) if by_sex else None, age=mixed_anova_interaction(Y, comp.AGEGRP.values),
                                     risk=mixed_anova_interaction(Y, comp.RISK0.map(RISK_LABEL).values))
    # 各次卡方：風險分類 × 性別／年齡層
    for w in range(1, K + 1):
        ww = long[long.WAVE == w]
        ages_present = [g for g in AGE_GROUPS if (ww.AGEGRP == g).any()]
        for bc, (bname, _) in BINARY.items():
            for var, labels, vals in [("SEX", ["男性", "女性"], ["M", "F"]), ("AGEGRP", ages_present, ages_present)][0 if by_sex else 1:]:
                tab = [[int(((ww[var] == v) & (ww[bc] == 1)).sum()), int(((ww[var] == v) & (ww[bc] == 0)).sum())] for v in vals]
                res = chisq_table(tab, labels, ["是", "否"])
                if var == "AGEGRP":
                    res.update(linear_trend(tab, [AGE_GROUPS.index(g) + 1 for g in ages_present]))
                res.update(wave=w, outcome=bc, outcome_name=bname, by="性別" if var == "SEX" else "年齡層")
                out["chisq"].append(res)
    # 代表性：分析對象中，三次皆參加 vs 參加兩次（比較前測值）
    t1 = D["by_wave"][1]
    flag = people.loc[t1.index, "COMPLETE"] == 1
    att = []
    for c in ["AGE"] + list(MAIN):
        x, y = t1.loc[flag, c], t1.loc[~flag, c]
        t = stats.ttest_ind(x, y, equal_var=False) if len(x) > 1 and len(y) > 1 else None
        att.append(dict(code=c, name="年齡" if c == "AGE" else MAIN[c][0], unit="歲" if c == "AGE" else MAIN[c][1],
                        n1=int(len(x)), m1=x.mean(), s1=x.std(), n0=int(len(y)), m0=y.mean() if len(y) else None,
                        s0=y.std() if len(y) > 1 else None, t=t.statistic if t else None, df=t.df if t else None, p=t.pvalue if t else None))
    tab = [[int(((t1.SEX == s) & flag).sum()), int(((t1.SEX == s) & ~flag).sum())] for s in ["M", "F"]]
    out["attrition"] = dict(n_completed=int(flag.sum()), n_dropped=int((~flag).sum()), vars=att,
                            sex=chisq_table(tab, ["男性", "女性"], ["三次皆參加", "參加兩次"]) if by_sex else None)

    def status(ww):
        return dict(n=len(ww), bmi_cat=[int((ww.BMICAT == c).sum()) for c in BMI_CATS], vfat_cat=[int((ww.VFCAT == c).sum()) for c in VFAT_CATS],
                    binary={bc: int(ww[bc].sum()) for bc in BINARY},
                    binary_by_sex={bc: {s: [int(ww.loc[ww.SEX == s, bc].sum()), int((ww.SEX == s).sum())] for s in ["M", "F"]} for bc in BINARY},
                    hidden_fat=int(((ww.BMI < 24) & (ww.fat == 1)).sum()))
    out["status"] = [status(D["by_wave"][w]) for w in range(1, K + 1)]
    out["lmm"] = lmm_sensitivity(D)
    out["change_rules"] = dict(thresh={k: list(v) for k, v in CHANGE_THRESH.items()}, weight_loss=WEIGHT_LOSS_TARGETS, comp_thresh=COMP_THRESH,
                               comp_types=[dict(code=k, name=n, group=g, note=t) for k, n, g, t in COMP_TYPES])
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
    names = [w["label"] for w in info["waves"]]
    b, last = o["status"][0], o["status"][-1]
    n = b["n"]
    pct = lambda k, nn=n: 100 * k / nn if nn else 0
    ow, ob, fat, vf = (b["binary"][k] for k in ("ow", "ob", "fat", "vfat"))
    trail = lambda k: f"；{names[-1]}（{last['n']} 人）為 {pct(last['binary'][k], last['n']):.1f}%"
    findings = []
    lvl = "high" if pct(ow) >= 50 else "mid" if pct(ow) >= 30 else "low"
    findings.append(dict(title="體位（BMI）", level=lvl, text=(
        f"前測（{n} 人）BMI ≥ 24（過重或肥胖）{ow} 人（{pct(ow):.1f}%），其中 BMI ≥ 27（肥胖）{ob} 人（{pct(ob):.1f}%）"
        f"{trail('ow')}。" + sex_gap(o, "ow"))))
    bs = b["binary_by_sex"]["fat"]
    lvl = "high" if pct(fat) >= 50 else "mid" if pct(fat) >= 30 else "low"
    findings.append(dict(title="體脂率", level=lvl, text=(
        f"依國民健康署標準（男性 ≥ 25%、女性 ≥ 30% 屬肥胖），前測體脂率超標 {fat} 人（{pct(fat):.1f}%"
        + ("；" if info.get("by_sex", True) else "")
        + (f"男性 {bs['M'][0]}/{bs['M'][1]}、女性 {bs['F'][0]}/{bs['F'][1]}）" if info.get("by_sex", True) else "）")
        + f"{trail('fat')}。" + sex_gap(o, "fat")
        + (f"前測有 {b['hidden_fat']} 人 BMI 未達 24 但體脂率已超標（俗稱「隱性肥胖」），不宜僅以體重判斷。" if b["hidden_fat"] else ""))))
    lvl = "high" if pct(vf) >= 40 else "mid" if pct(vf) >= 20 else "low"
    findings.append(dict(title="內臟脂肪", level=lvl, text=(
        f"前測內臟脂肪等級 ≥ 10（TANITA 原廠「偏高」標準）{vf} 人（{pct(vf):.1f}%），其中 ≥ 15 者 {b['vfat_cat'][2]} 人"
        f"{trail('vfat')}。" + sex_gap(o, "vfat")
        + "內臟脂肪與代謝症候群風險相關，國健署建議以腰圍輔助評估（男性 ≥ 90 cm、女性 ≥ 80 cm 為腹部肥胖），本次未測腰圍。")))
    allst = o["strata"]["all"]
    fav_any = unfav_any = False
    if "rm" in allst:
        sig = []
        for c, (nm, unit, dec, good, _) in MAIN.items():
            s = allst["rm"][c]
            if s["p_final"] < ALPHA:
                d = s["means"][-1] - s["means"][0]
                tag = "" if good == 0 else ("（有利）" if np.sign(d) == good else "（不利）")
                fav_any |= tag == "（有利）"
                unfav_any |= tag == "（不利）"
                sig.append(f"{nm}（{' → '.join(f'{m:.{max(dec, 1)}f}' for m in s['means'])} {unit}{tag}，{pfmt(s['p_final'])}）")
        txt = (f"三次皆參加者 {info['n_complete']} 人（重複測量 ANOVA）："
               + ("隨時間有顯著變化的指標為" + "；".join(sig) + "。" if sig else f"{'、'.join(v[0] for v in MAIN.values())}在{'、'.join(names)}之間均未達統計顯著變化。"))
    else:
        txt = f"三次皆參加者僅 {info['n_complete']} 人，人數不足，未進行三次比較。"
    nn = info["n_two"]
    if nn >= MIN_N:
        hits = []
        for c, (nm, unit, dec, good, _) in MAIN.items():
            pr = allst["two"][c]
            if pr.get("p") is not None and pr["p"] < ALPHA:
                tag = "" if good == 0 else ("有利" if np.sign(pr["diff"]) == good else "不利")
                fav_any |= tag == "有利"
                unfav_any |= tag == "不利"
                hits.append(f"{nm}{'上升' if pr['diff'] > 0 else '下降'} {abs(pr['diff']):.{max(dec, 1)}f} {unit}（{tag + '，' if tag else ''}{pfmt(pr['p'])}）")
        txt += (f"參加兩次者 {nn} 人（前測＋{'或'.join(names[1:])}）的前測與介入後比較："
                + ("、".join(hits) if hits else "各指標均無顯著變化") + "。")
    elif nn:
        txt += f"參加兩次者僅 {nn} 人，人數不足，未單獨檢定。"
    strat = []
    for key, st in o["strata"].items():
        if key == "all" or "|" in key or "rm" not in st:
            continue
        hits = [MAIN[c][0] for c in MAIN if st["rm"][c]["p_final"] < ALPHA]
        if hits:
            strat.append(f"{st['label']}（{st['n_complete']} 人）的{'、'.join(hits)}")
    il = allst.get("indiv", {}).get("last", {})
    if il.get("weight_loss"):
        wl = il["weight_loss"]
        cg, nn_ = il["comp_group"], il["n"]
        txt += (f"以個人身體組成來看，{nn_} 位納入分析者從前測到最後一次量測，屬「減脂保肌或增肌」者 {cg['good']} 人（{100 * cg['good'] / nn_:.1f}%）、"
                f"「增脂或肌肉流失」者 {cg['bad']} 人（{100 * cg['bad'] / nn_:.1f}%）、脂肪與肌肉同增同減者 {cg['mixed']} 人；"
                f"體重減少 3% 以上者 {wl['3']} 人（{100 * wl['3'] / nn_:.1f}%），其中肌肉量未減少者 {il['weight_loss_keep']['3']} 人。")
    if strat:
        txt += "分層檢定中，" + "；".join(strat) + "隨時間有顯著變化。"
    inter = []
    for by, lab in (("sex", "性別"), ("age", "年齡層"), ("risk", "前測體位")):
        if by == "sex" and not info.get("by_sex", True):
            continue
        hits = [MAIN[c][0] for c in MAIN if (o["interaction"][c].get(by) or {}).get("p_final", 1) < ALPHA]
        if hits:
            inter.append(f"{'、'.join(hits)}的變化趨勢在不同{lab}之間有差異（時間 × {lab}交互作用 p < 0.05）")
    if inter:
        txt += "；".join(inter) + "，詳見分層分析。"
    lvl = "low" if fav_any and not unfav_any else "high" if unfav_any and not fav_any else "mid"
    findings.append(dict(title="介入前後變化", level=lvl, text=txt))
    score = sum({"high": 2, "mid": 1, "low": 0}[f["level"]] for f in findings[:3])
    overall = "需優先介入" if score >= 4 else "需持續關注" if score >= 2 else "整體良好"
    rule = ("依前測三項風險分類盛行率判定：BMI ≥ 24 與體脂率超標比例 ≥ 50% 為「需介入」、30–49% 為「需關注」；"
            "內臟脂肪偏高比例 ≥ 40% 為「需介入」、20–39% 為「需關注」。需介入計 2 分、需關注計 1 分，"
            "合計 ≥ 4 分為「需優先介入」、2–3 分為「需持續關注」、0–1 分為「整體良好」。此分級為本報告自訂之彙整方式，非國健署公告分級。")
    recs = [
        dict(title="健康體重管理", text="依國健署「聰明吃、快樂動、天天量體重」原則；BMI ≥ 24 者以每週減重 0.5–1 公斤為目標，避免快速減重造成肌肉流失。"),
        dict(title="均衡飲食", text="依國健署「我的餐盤」六口訣：每天早晚一杯奶、每餐水果拳頭大、菜比水果多一點、飯跟蔬菜一樣多、豆魚蛋肉一掌心、堅果種子一茶匙；減少含糖飲料與高油加工食品。"),
        dict(title="規律身體活動", text="成人每週累積至少 150 分鐘中等費力身體活動（或 75 分鐘費力身體活動），並每週至少 2 天進行肌力訓練，有助於降低體脂並維持肌肉量。"),
        dict(title="職場支持措施", text="建議職場延續計畫成果：推動減少久坐（每坐 1 小時起身活動）、提供健康餐飲選項及團體運動課程，並將腰圍納入量測，以完整評估腹部肥胖。"),
        dict(title="提升參與完整度", text=f"本次三次皆參加者占全部參加者 {100 * info['n_complete'] / info['n_total']:.0f}%。建議固定量測時段（空腹、未運動、排尿後），並提醒參加者每次皆出席，以提高成效評估的可信度。"),
    ]
    return dict(overall=overall, rule=rule, findings=findings, recommendations=recs,
                sources=["衛生福利部國民健康署「成人健康體位標準」（BMI、腰圍、體脂肪率）",
                         "衛生福利部國民健康署「每日飲食指南」及「我的餐盤」（107 年版）",
                         "衛生福利部國民健康署 身體活動建議（成人每週 150 分鐘中等費力身體活動、每週 2 天肌力訓練）",
                         "內臟脂肪等級分級為 TANITA 原廠標準（非國健署公告）"])


def main():
    argv = sys.argv[1:]
    name = None
    if "--name" in argv:
        i = argv.index("--name")
        name = argv[i + 1]
        del argv[i:i + 2]
    outdir = Path(argv[1] if len(argv) > 1 else Path(__file__).parent / "output")
    outdir.mkdir(parents=True, exist_ok=True)
    _, res = run(argv[0], name)
    (outdir / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["info"], ensure_ascii=False))


if __name__ == "__main__":
    main()
