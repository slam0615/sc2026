// 以 Chromium 將報告 HTML 列印為 A4 直式 PDF（含頁首、頁碼）
// 用法：node render_pdf.mjs <report.html> <out.pdf> [頁首文字]
import { createRequire } from 'module';
import { pathToFileURL } from 'url';
const require = createRequire(import.meta.url);
let pw;
try { pw = require('playwright'); } catch { pw = require(process.env.PLAYWRIGHT_MODULE || '/opt/node-tools/node_modules/playwright'); }
const [, , src, out, head = ''] = process.argv;
const browser = await pw.chromium.launch();
const page = await browser.newPage();
await page.goto(pathToFileURL(src).href + '?print', { waitUntil: 'networkidle' }).catch(() => page.goto(pathToFileURL(src).href + '?print'));
await page.emulateMedia({ media: 'print' });
await page.evaluate(() => document.fonts.ready);
const small = 'font-size:8px;color:#6f7e82;width:100%;padding:0 13mm;font-family:"Noto Sans TC","WenQuanYi Zen Hei",sans-serif;display:flex;justify-content:space-between';
await page.pdf({
  path: out, format: 'A4', printBackground: true, preferCSSPageSize: true,
  displayHeaderFooter: true,
  headerTemplate: `<div style='${small}'><span>${head}　身體組成前後測總體報告</span><span>TANITA 身體組成分析</span></div>`,
  footerTemplate: `<div style='${small}'><span>僅呈現彙總統計，不含個人資料</span><span>第 <span class="pageNumber"></span> / <span class="totalPages"></span> 頁</span></div>`,
});
await browser.close();
