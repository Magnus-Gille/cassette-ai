import pw from '/usr/local/lib/node_modules/@playwright/test/node_modules/playwright/index.js';
const { chromium } = pw;
const base = 'http://localhost:8811/tic80_console.html';

const browser = await chromium.launch({ headless: true });

async function run(cartFile, label) {
  const page = await browser.newContext().then(c => c.newPage());
  const failed = [];
  const reqs = [];
  page.on('request', r => reqs.push(r.url()));
  page.on('requestfailed', r => failed.push(r.url()));
  page.on('response', r => { if (r.status() >= 400) failed.push(r.url() + ' ' + r.status()); });

  // deep-link via hash so it auto-boots that cart
  await page.goto(base + '#' + cartFile, { waitUntil: 'load' });
  // it auto-boots on load via the hash; wait for the engine to take over
  await page.waitForTimeout(4500);

  function sampler() {
    const c = document.getElementById('canvas');
    const t = document.createElement('canvas'); t.width = c.width; t.height = c.height;
    t.getContext('2d').drawImage(c, 0, 0);
    const d = t.getContext('2d').getImageData(0, 0, t.width, t.height).data;
    const colors = new Set(); let nb = 0;
    for (let i = 0; i < d.length; i += 4) { colors.add((d[i]<<16)|(d[i+1]<<8)|d[i+2]); if (d[i]+d[i+1]+d[i+2]>12) nb++; }
    return { colors: colors.size, nonBlack: nb, total: d.length/4, sig: t.toDataURL().slice(-50) };
  }

  // sample two frames ~1s apart to detect animation
  const a = await page.evaluate(sampler);
  await page.waitForTimeout(1000);
  const b = await page.evaluate(sampler);

  await page.screenshot({ path: `/Users/magnus/repos/cassette-ai/payloads/tic80/dist/verify_${label}.png` });
  console.log(`\n=== ${label} (${cartFile}) ===`);
  console.log('  title:', await page.title());
  console.log('  frameA colors/nonBlack:', a.colors, a.nonBlack, '/', a.total);
  console.log('  frameB colors/nonBlack:', b.colors, b.nonBlack);
  console.log('  ANIMATING (frame changed):', a.sig !== b.sig);
  console.log('  failed-requests:', JSON.stringify(failed));
  console.log('  external-fetches (non-html):', reqs.filter(u => !u.endsWith('tic80_console.html') && !u.includes('#')).length);
  await page.context().close();
}

await run('fire.lua', 'fire');
await run('p3d.lua', 'p3d');
await browser.close();
