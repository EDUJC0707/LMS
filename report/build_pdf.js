const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'test', 'rpa-test', 'node_modules', 'playwright'));
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + path.join(__dirname, 'report.html'), { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.pdf({ path: path.join(__dirname, 'LMS 외부서비스 결정.pdf'), format: 'A4', printBackground: true, preferCSSPageSize: true });
  // QA screenshots per page
  await page.setViewportSize({ width: 794, height: 1123 });
  for (let i = 0; i < 4; i++) {
    await page.evaluate((idx) => { document.querySelectorAll('.page')[idx].scrollIntoView(); }, i).catch(()=>{});
  }
  await browser.close();
  console.log('pdf saved');
})();
