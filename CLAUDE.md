# TANITA 職場身體組成報告：工作流程

本 repo 的 `tanita_report/` 是固定版本的分析程式。每家職場在**各自獨立的對話**中執行，步驟如下，不要自行更改統計方法。方法要修改時，先在主對話改好程式並推送，再開始下一家。

## 每家職場的步驟

1. 使用者上傳該職場的 TANITA MC-780 GMON 匯出檔（`.xls`，英文欄位或中文欄名版本皆可）。
2. 安裝套件（雲端環境每次都是新的）：
   `pip install scipy statsmodels xlrd pyreadstat`
3. 執行：
   `cd tanita_report && python build_report.py <上傳檔路徑> --name <職場名稱>`
4. 產出位於 `tanita_report/output/`：
   - `<職場>_身體組成總體報告.html`：互動式報告，給職場
   - `<職場>_身體組成總體報告_A4.pdf`：列印版，給職場
   - `<職場>_驗算.xlsx`、`<職場>_驗算_寬格式.sav`、`<職場>_驗算_長格式.sav`、`<職場>_驗算.sps`：**僅供分析人員**，含去識別化的個人資料
5. 檢查 Excel：執行 xlsx skill 的 `recalc.py`，確認 `total_errors` 為 0，且所有「差異」欄小於 1e-5。
6. 檢查報告：看 `results.json` 的 `info.cleaning_log`（重複量測、性別或身高不一致、年齡層合併），有警告就先回報使用者。
7. 用 SendUserFile 把產出傳給使用者，並提醒雲端環境會被回收，要立即下載。

## 絕對不要

- 把原始資料、`output/`、`.xlsx`、`.sav` 提交到 git。repo 是公開的，`.gitignore` 已排除這些檔案。
- 在報告中加入個人層級資料，或把分層最低人數 `MIN_N`（10 人）調低。
- 更動統計方法、判讀標準或評價規則。這些變更要在主對話進行，讓 21 家保持一致。

## 方法摘要（細節見 `tanita_report/README.md`）

- 測量波次依測量日分群（相隔超過 7 天算新的一波）。同一人同一波重複量測時，保留最後一筆。
- 主分析：完成全部量測者的重複測量 ANOVA（Mauchly 檢定，必要時用 Greenhouse-Geisser 校正，Bonferroni 事後比較），以 Friedman 檢定為參考。
- 補充分析：用全部可用資料跑線性混合模型（REML、Satterthwaite 自由度），並對各配對的可用資料做配對 t 檢定。
- 分類變項：Cochran's Q 與 McNemar 檢定；各波量測做卡方檢定，必要時改用 Fisher 精確檢定。
- 分層：依性別與年齡層。任一年齡層少於 10 人時，自動與相鄰組合併。
