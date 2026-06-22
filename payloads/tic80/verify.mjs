// Isolated verification of the production artifact (its own Chromium; the shared
// MCP browser is contended by another agent).
import pw from '/usr/local/lib/node_modules/@playwright/test/node_modules/playwright/index.js';
const { chromium } = pw;
const base = 'http://localhost:8811/tic80_console.html';

const browser = await chromium.launch({ headless: true });

function sampler() {
  const c = document.getElementById('canvas');
  const t = document.createElement('canvas'); t.width = c.width; t.height = c.height;
  const ctx = t.getContext('2d'); ctx.drawImage(c, 0, 0);
  const d = ctx.getImageData(0, 0, t.width, t.height).data;
  const colors = new Set(); let nb = 0;
  for (let i = 0; i < d.length; i += 4) {
    colors.add((d[i] << 16) | (d[i + 1] << 8) | d[i + 2]);
    if (d[i] + d[i + 1] + d[i + 2] > 12) nb++;
  }
  return { w: c.width, h: c.height, colors: colors.size, nb,
           total: d.length / 4, sig: t.toDataURL().slice(-40),
           sample: [...colors].slice(0, 8).map(x => '#' + x.toString(16).padStart(6, '0')) };
}

async function test(mode, cartFile, label) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const reqs = [], failed = [], cerr = [];
  page.on('request', r => reqs.push(r.url()));
  page.on('requestfailed', r => failed.push(r.url() + ' [' + (r.failure()?.errorText) + ']'));
  page.on('response', r => { if (r.status() >= 400) failed.push(r.url() + ' ' + r.status()); });
  page.on('console', m => { if (m.type() === 'error') cerr.push(m.text()); });
  page.on('pageerror', e => cerr.push('PAGEERROR:' + e.message));

  if (mode === 'click') {
    await page.goto(base, { waitUntil: 'load' });
    await page.click('#playBtn');
  } else {
    await page.goto(base + '#' + cartFile, { waitUntil: 'load' }); // auto-boots
  }

  // poll up to ~6s for a rendered cart frame
  let res = null;
  for (let t = 0; t < 50; t++) {
    await page.waitForTimeout(120);
    res = await page.evaluate(sampler);
    if (res.colors > 2 && res.nb > 50 && res.w > 400) break;
  }
  const f1 = res.sig;
  await page.waitForTimeout(700);
  const f2 = (await page.evaluate(sampler)).sig;

  await page.screenshot({ path: `/Users/magnus/repos/cassette-ai/payloads/tic80/dist/verify_${label}.png` });

  const ext = [...new Set(reqs)].filter(u => !u.endsWith('tic80_console.html') && !u.includes('#'));
  console.log(`\n=== ${label} (${mode}${cartFile ? ' ' + cartFile : ''}) ===`);
  console.log(`  canvas ${res.w}x${res.h}  distinctColors=${res.colors}  nonBlack=${res.nb}/${res.total}`);
  console.log(`  animating=${f1 !== f2}   palette=${JSON.stringify(res.sample)}`);
  console.log(`  EXTERNAL fetches (excl. the html):`, JSON.stringify(ext));
  console.log(`  failed requests:`, JSON.stringify(failed));
  console.log(`  console errors:`, JSON.stringify(cerr));
  await ctx.close();
  return { label, ok: res.colors > 2 && res.nb > 50, ext, failed };
}

const r = [];
r.push(await test('click', null, 'tetris_default'));
r.push(await test('hash', 'fire.lua', 'fire'));
r.push(await test('hash', 'p3d.lua', 'p3d'));
r.push(await test('hash', 'palette.lua', 'palette'));

await browser.close();
console.log('\n=== SUMMARY ===');
for (const x of r) console.log(`  ${x.label}: rendered=${x.ok} extFetches=${x.ext.length} failed=${x.failed.length}`);
