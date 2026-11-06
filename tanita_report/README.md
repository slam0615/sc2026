# TANITA 身體組成多次量測總體報告產生器

讀取 TANITA MC-780（GMON 軟體）匯出的 `.xls`，可以是英文欄位版或中文欄名版。資料可包含固定測量日的 2 次以上量測，允許部分人缺測。程式會自動產出：

| 檔案 | 用途 | 對象 |
|---|---|---|
| `<職場>_身體組成總體報告.html` | 互動式總體報告（可依性別、年齡層篩選），單一檔案、可離線開啟 | 職場 |
| `<職場>_身體組成總體報告_A4.pdf` | 同內容的 A4 直式列印版 | 職場 |
| `<職場>_驗算.xlsx` | 以 Excel 公式重算主要統計量，含 Python 對照值與差異 | **僅限分析人員** |
| `<職場>_驗算_寬格式.sav`、`_長格式.sav` | SPSS 資料檔，已設定中文變項標籤與數值標籤 | **僅限分析人員** |
| `<職場>_驗算.sps` | SPSS 語法：GLM 重複測量、Friedman、MIXED、Cochran's Q、McNemar、卡方 | 分析人員 |

## 使用方式

```bash
pip install pandas scipy statsmodels openpyxl xlrd pyreadstat
python build_report.py 匯出檔.xls [輸出資料夾] --name 職場名稱   # HTML + Excel + SPSS + PDF
python build_report.py 匯出檔.xls --name 職場名稱 --no-pdf
```

PDF 需要 Node.js 與 Playwright。沒有的話，用瀏覽器開啟 HTML 後選「列印 → 另存為 PDF」，版面相同。

多家職場的作業流程見 repo 根目錄的 `CLAUDE.md`。

> `output/`、`*.xls`、`*.xlsx`、`*.sav` 已列入 `.gitignore`。本 repo 是公開的，**請勿提交原始資料或驗算檔**。

## 資料處理

- **波次**：依測量日分群，相隔超過 7 天算新的一波（T1、T2、T3…）。
- **重複量測**：同一人同一波量了多次，保留最後一筆。
- **一致性檢查**：同一人的性別不一致，或身高差異超過 2 cm，會列為警告。
- **年齡層**：以首次量測年齡分為未滿 30、30–39、40 歲以上。任一組少於 10 人時，與人數較少的相鄰組合併。
- **基礎代謝量**：原始單位 kJ，除以 4.184 換算成 kcal。

## 統計方法（全部可在 SPSS 重現）

| 目的 | 方法 | 資料 | SPSS |
|---|---|---|---|
| 各次描述 | 平均、標準差、95% CI | 每次的全部受測者 | EXAMINE |
| **主分析**：三次是否不同 | 重複測量 ANOVA；Mauchly p < 0.05 時採 Greenhouse-Geisser 校正；偏 η²；Bonferroni 事後比較 | 完成全部量測者 | GLM /WSFACTOR |
| 無母數參考 | Friedman 檢定 | 完成全部量測者 | NPAR TESTS /FRIEDMAN |
| 補充：納入缺測者 | 線性混合模型（個人隨機截距、REML、Satterthwaite 自由度、Bonferroni） | 全部可用資料 | MIXED |
| 補充：兩兩比較 | 配對 t 檢定（Bonferroni） | 每對兩次皆有量測者 | T-TEST PAIRS |
| 風險分類變化 | Cochran's Q、McNemar 精確檢定（Bonferroni） | 完成全部量測者 | NPAR TESTS |
| 各次組間比例 | Pearson 卡方；期望次數小於 5 的格子超過 20% 時改用 Fisher 精確檢定 | 每次的全部受測者 | CROSSTABS |
| 分層 | 各分層的重複測量 ANOVA；時間 × 性別、時間 × 年齡層交互作用 | 完成者／全部可用資料 | SPLIT FILE + GLM；MIXED |
| 代表性 | T1 受測者中完成與未完成者比較（Welch t、卡方） | T1 受測者 | T-TEST、CROSSTABS |

驗證紀錄：

- 重複測量 ANOVA 的 F、Mauchly W、GG ε、p 值與 Friedman 檢定，都和 pingouin 套件的結果一致。
- 混合模型的變異數估計與 statsmodels 一致。只用完成者跑時，F 值和自由度與重複測量 ANOVA 相同（df = 2(n−1)），符合理論。
- Excel 公式結果和 Python 的差異都小於 1e-6。
- 混合模型的 Satterthwaite 自由度是數值近似，和 SPSS 可能在小數第三位有些微差異。

## 隱私規則

- 報告只呈現彙總統計，不含編號、姓名或個人數值。
- 任何分析人數少於 `MIN_N`（10 人）就不呈現；網頁內嵌資料也不寫入該分層人數。
- 驗算檔和 .sav 用序號取代受測者編號，但仍屬個人層級資料，只供內部驗算使用。

## A4 直式 PDF 版型（三次量測，約 11 頁）

| 頁 | 內容 |
|---|---|
| 1 | 標題、**總體評價與建議**（總評等級；體位、體脂肪、內臟脂肪、多次量測變化 4 張評價卡）、建議事項 |
| 2 | 受測概況（各次人數、參與型態、組成表、資料處理說明）、重點指標 6 張 KPI 卡（T1 → T2 → T3） |
| 3 | 16 項指標「相對 T1 變化量」小圖 |
| 4 | 重複測量 ANOVA 比較表（F、p、偏 η²、Friedman、Bonferroni 兩兩比較） |
| 5 | 健康分級分布（BMI、內臟脂肪；各次堆疊條）、Cochran's Q／McNemar 表 |
| 6 | 分層分析：性別、年齡層與交互作用 |
| 7–8 | 各次卡方檢定、樣本代表性 |
| 9 | 補充分析：混合模型、可用配對 t 檢定 |
| 10 | 分節身體組成 |
| 11 | 方法、研究限制、名詞與單位 |

配色採 Tropical punch：橘 `#FF8243`、粉 `#FFC0CB`、黃 `#FCE883`、青 `#069494`。粉色與黃色只用於底色與分級色塊，不用作文字顏色。互動元件在列印時會隱藏，PDF 固定呈現「全體」結果。
