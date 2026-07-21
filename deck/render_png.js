// slide-N.html → pptx_png/slide-N.png (2560×1440, 2x)
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'test', 'rpa-test', 'node_modules', 'playwright'));

const N = 10;
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 });
  for (let i = 1; i <= N; i++) {
    const file = path.join(__dirname, `slide-${i}.html`);
    await page.goto('file://' + file, { waitUntil: 'networkidle' });
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(__dirname, 'pptx_png', `slide-${i}.png`) });
    console.log(`rendered slide-${i}.png`);
  }
  await browser.close();
})();
