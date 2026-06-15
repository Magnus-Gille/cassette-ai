/* ============================================================
   THE MAGNETIC VAULT — release data + card/art rendering
   Vanilla JS, no build step. Drives the gallery and detail list.
   ============================================================ */

/* ---- the catalog -------------------------------------------------- */
const RELEASES = [
  {
    id: "doom",
    title: "DOOM",
    flex: "a cassette that plays DOOM",
    decodes: "The full game — Freedoom Episode 1, all 9 maps, in-browser sound, saves, and a hand-built bonus level — decoded <b>byte-exact</b> off a real cassette.",
    license: "GPL",
    sellable: true,
    tier: "today",          // today | hifi
    accent: "#c0492b",
    art: "doom",
    try: "https://magnus-gille.github.io/cassette-ai/",
    buy: "#order"
  },
  {
    id: "deck-test",
    title: "The Deck Test",
    flex: "play it, and it tells you what bitrate YOUR deck can do",
    decodes: "A link-evaluation tape. Play it into your deck, capture the return, and it prints a <b>report card</b> — the real bitrate your hardware can carry.",
    license: "MIT",
    sellable: true,
    tier: "today",
    accent: "#4f8a5b",
    art: "vu",
    try: "#try",
    buy: "#order"
  },
  {
    id: "willows",
    title: "The Willows",
    flex: "a playable, self-narrating book",
    decodes: "Algernon Blackwood's 1907 ghost story — and it <b>reads itself aloud</b>. Open the tape's file and the text plays back as a narrated book.",
    license: "Public domain",
    sellable: true,
    tier: "today",
    accent: "#6b8f3a",
    art: "book",
    try: "#try",
    buy: "#order"
  },
  {
    id: "console",
    title: "The Console",
    flex: "a whole fantasy games console on a cassette",
    decodes: "A TIC-80 fantasy console plus a pack of playable games, booting straight from the tape. <b>An arcade in your pocket</b>, pressed onto magnetic film.",
    license: "MIT",
    sellable: true,
    tier: "hifi",
    accent: "#3f7fa3",
    art: "console",
    try: "#try",
    buy: "#order"
  },
  {
    id: "grandmaster",
    title: "Grandmaster",
    flex: "a cassette that plays chess",
    decodes: "A complete chess engine and board you can play against, recovered from tape. <b>Sit down for a game</b> with a cassette.",
    license: "MIT",
    sellable: true,
    tier: "today",
    accent: "#7a5cab",
    art: "chess",
    try: "#try",
    buy: "#order"
  },
  {
    id: "great-library",
    title: "The Great Library",
    flex: "58 classic books on one tape",
    decodes: "Austen, Dickens, Tolstoy, Shakespeare and 54 more — <b>a whole shelf of world literature</b> on a single C90, every word lossless.",
    license: "Public domain",
    sellable: true,
    tier: "hifi",
    accent: "#b8860b",
    art: "library",
    try: "#try",
    buy: "#order"
  },
  {
    id: "svenska",
    title: "Den svenska samlingen",
    flex: "Selma Lagerlöf, in Swedish and English",
    decodes: "A Swedish collection — Lagerlöf's <b>Gösta Berling</b> and more, in the original Swedish alongside English translations. En kassett på två språk.",
    license: "Public domain",
    sellable: true,
    tier: "today",
    accent: "#2f6f8f",
    art: "svenska",
    try: "#try",
    buy: "#order"
  },
  {
    id: "modern-shelf",
    title: "The Modern Shelf",
    flex: "Doctorow + Watts + SCP",
    decodes: "Cory Doctorow, Peter Watts' <b>Blindsight</b>, and SCP archive selections — modern, generous, free-culture writing. Released as a gift.",
    license: "Free / gift only",
    sellable: false,        // NonCommercial — no buy button
    tier: "hifi",
    accent: "#8a5a2b",
    art: "shelf",
    try: "#try",
    buy: null
  }
];

/* ---- SVG label art ------------------------------------------------ *
 * Each release gets a bespoke cassette-inlay "spine art" panel.
 * Drawn at 320x180 (16:9) and scaled to fit.                          */
function relArt(kind, accent) {
  const c = accent || "#e6a24c";
  const base = (inner) =>
    `<svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" role="img" aria-hidden="true">
       <defs>
         <linearGradient id="g_${kind}" x1="0" y1="0" x2="0" y2="1">
           <stop offset="0" stop-color="#2b2620"/><stop offset="1" stop-color="#17130e"/>
         </linearGradient>
       </defs>
       <rect width="320" height="180" fill="url(#g_${kind})"/>
       <!-- ferric tape sheen -->
       <rect width="320" height="180" fill="${c}" opacity="0.05"/>
       ${inner}
     </svg>`;

  // shared reel glyph
  const reel = (cx, cy, r, col, spinClass) =>
    `<g class="${spinClass||''}" style="transform-origin:${cx}px ${cy}px">
       <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${col}" stroke-width="2.5"/>
       <circle cx="${cx}" cy="${cy}" r="${r*0.34}" fill="${col}"/>
       ${[0,60,120,180,240,300].map(a=>{
         const rad=a*Math.PI/180;
         return `<line x1="${cx+Math.cos(rad)*r*0.42}" y1="${cy+Math.sin(rad)*r*0.42}" x2="${cx+Math.cos(rad)*r*0.85}" y2="${cy+Math.sin(rad)*r*0.85}" stroke="${col}" stroke-width="2"/>`;
       }).join('')}
     </g>`;

  const grid = `${Array.from({length:9},(_,i)=>`<line x1="${20+i*35}" y1="20" x2="${20+i*35}" y2="160" stroke="${c}" stroke-width="0.5" opacity="0.12"/>`).join('')}`;

  switch (kind) {
    case "doom": // a stylized demon-sigil mark + reels
      return base(`${grid}
        ${reel(70,90,30,c,'reel-spin')}
        ${reel(250,90,30,c,'reel-spin slow')}
        <g transform="translate(160,90)" fill="none" stroke="${c}" stroke-width="3">
          <path d="M0,-34 L26,-6 L18,30 L-18,30 L-26,-6 Z"/>
          <circle cx="-9" cy="-2" r="4.5" fill="${c}"/><circle cx="9" cy="-2" r="4.5" fill="${c}"/>
          <path d="M-13,14 Q0,24 13,14" stroke="${c}"/>
        </g>
        <text x="160" y="160" text-anchor="middle" fill="${c}" font-family="ui-monospace,monospace" font-size="11" letter-spacing="4" opacity="0.8">BYTE-EXACT</text>`);

    case "vu": // VU meter art for the deck test
      return base(`${grid}
        <path d="M40,140 A120,120 0 0 1 280,140" fill="none" stroke="${c}" stroke-width="2" opacity="0.4"/>
        ${Array.from({length:11},(_,i)=>{const a=(-50+i*10)*Math.PI/180;const big=i>7;
          return `<line x1="${160+Math.cos(a)*108}" y1="${150+Math.sin(a)*108}" x2="${160+Math.cos(a)*122}" y2="${150+Math.sin(a)*122}" stroke="${i>7?'#c0492b':c}" stroke-width="${big?2.5:1.5}"/>`;}).join('')}
        <line x1="160" y1="150" x2="${160+Math.cos(-15*Math.PI/180)*100}" y2="${150+Math.sin(-15*Math.PI/180)*100}" stroke="#f4efe6" stroke-width="2.5" class="vu-needle" style="transform-origin:160px 150px"/>
        <circle cx="160" cy="150" r="6" fill="${c}"/>
        <text x="248" y="60" fill="#c0492b" font-family="ui-monospace,monospace" font-size="13" font-weight="700">+3</text>
        <text x="160" y="172" text-anchor="middle" fill="${c}" font-family="ui-monospace,monospace" font-size="10" letter-spacing="3" opacity="0.8">YOUR DECK</text>`);

    case "book": // open self-narrating book + soundwave
      return base(`${grid}
        ${reel(255,42,18,c,'reel-spin slow')}
        <g transform="translate(160,84)" stroke="${c}" stroke-width="2" fill="none">
          <path d="M-58,-30 Q-30,-38 0,-30 Q30,-38 58,-30 L58,34 Q30,26 0,34 Q-30,26 -58,34 Z"/>
          <line x1="0" y1="-30" x2="0" y2="34"/>
          ${[-1,1].map(s=>[-18,-8,2].map(y=>`<line x1="${s*8}" y1="${y}" x2="${s*48}" y2="${y}" stroke-width="1.4" opacity="0.7"/>`).join('')).join('')}
        </g>
        <g transform="translate(160,150)">
          ${Array.from({length:21},(_,i)=>{const h=4+Math.abs(Math.sin(i*0.9))*14;return `<rect x="${-100+i*10}" y="${-h/2}" width="3" height="${h}" rx="1.5" fill="${c}" opacity="0.85"/>`;}).join('')}
        </g>`);

    case "console": // pixel arcade + d-pad
      return base(`${grid}
        ${reel(60,46,18,c,'reel-spin')}${reel(260,46,18,c,'reel-spin slow')}
        <g transform="translate(160,92)">
          <rect x="-72" y="-34" width="144" height="68" rx="8" fill="none" stroke="${c}" stroke-width="2.5"/>
          ${Array.from({length:60},(_,i)=>`<rect x="${-62+(i%15)*8}" y="${-24+Math.floor(i/15)*10}" width="6" height="6" fill="${c}" opacity="${(i*7%5)/5*0.7+0.15}"/>`).join('')}
        </g>
        <g transform="translate(160,154)" fill="${c}">
          <rect x="-20" y="-3" width="40" height="6" rx="3"/><rect x="-3" y="-12" width="6" height="24" rx="3"/>
          <circle cx="44" cy="0" r="5"/><circle cx="60" cy="0" r="5"/>
        </g>`);

    case "chess": // crown / knight + board
      return base(`${grid}
        ${reel(60,46,18,c,'reel-spin')}${reel(260,46,18,c,'reel-spin slow')}
        <g transform="translate(110,150)">
          ${Array.from({length:36},(_,i)=>{const x=i%6,y=Math.floor(i/6);return (x+y)%2===0?`<rect x="${-54+x*18}" y="${-54+y*18}" width="18" height="18" fill="${c}" opacity="0.18"/>`:'';}).join('')}
          <rect x="-54" y="-54" width="108" height="108" fill="none" stroke="${c}" stroke-width="1.5" opacity="0.5"/>
        </g>
        <g transform="translate(205,86)" fill="none" stroke="${c}" stroke-width="3">
          <path d="M-16,34 L16,34 L13,4 Q22,-2 14,-14 Q24,-26 6,-30 Q10,-38 0,-42 Q-12,-34 -10,-22 Q-26,-16 -16,-2 Q-22,4 -16,8 Z" stroke-linejoin="round"/>
          <circle cx="-2" cy="-22" r="2.5" fill="${c}"/>
        </g>`);

    case "library": // tall stack of book spines + count
      return base(`${grid}
        ${reel(265,40,16,c,'reel-spin slow')}
        <g transform="translate(40,30)">
          ${Array.from({length:13},(_,i)=>`<rect x="${i*18}" y="${(i%3)*4}" width="13" height="${100-(i%4)*8}" rx="2" fill="none" stroke="${c}" stroke-width="2" opacity="${0.5+(i%3)*0.18}"/>`).join('')}
        </g>
        <text x="160" y="168" text-anchor="middle" fill="${c}" font-family="'Iowan Old Style',Palatino,serif" font-size="26" font-style="italic" opacity="0.95">58 books</text>`);

    case "svenska": // Swedish flag-tinted spine + crown
      return base(`${grid}
        ${reel(60,46,18,c,'reel-spin')}${reel(260,46,18,c,'reel-spin slow')}
        <g transform="translate(160,96)">
          <rect x="-70" y="-26" width="140" height="52" rx="5" fill="none" stroke="${c}" stroke-width="2"/>
          <line x1="-26" y1="-26" x2="-26" y2="26" stroke="${c}" stroke-width="6" opacity="0.7"/>
          <line x1="-70" y1="-2" x2="70" y2="-2" stroke="${c}" stroke-width="6" opacity="0.7"/>
          <text x="22" y="6" text-anchor="middle" fill="${c}" font-family="'Iowan Old Style',serif" font-size="15" font-style="italic">SV / EN</text>
        </g>
        <text x="160" y="160" text-anchor="middle" fill="${c}" font-family="ui-monospace,monospace" font-size="9" letter-spacing="3" opacity="0.75">LAGERLÖF</text>`);

    case "shelf": // gift-ribbon shelf
      return base(`${grid}
        ${reel(60,46,18,c,'reel-spin')}${reel(260,46,18,c,'reel-spin slow')}
        <g transform="translate(160,96)">
          ${[-44,-22,0,22,44].map((x,i)=>`<rect x="${x-7}" y="${-30+(i%2)*6}" width="14" height="${64-(i%2)*6}" rx="2" fill="none" stroke="${c}" stroke-width="2" opacity="0.8"/>`).join('')}
          <path d="M-2,-40 Q-22,-52 -14,-36 Q-2,-44 0,-30 Q2,-44 14,-36 Q22,-52 2,-40 Z" fill="${c}" opacity="0.9"/>
        </g>
        <text x="160" y="166" text-anchor="middle" fill="${c}" font-family="ui-monospace,monospace" font-size="9" letter-spacing="3" opacity="0.75">A GIFT</text>`);

    default:
      return base(`${reel(80,90,34,c,'reel-spin')}${reel(240,90,34,c,'reel-spin slow')}`);
  }
}

/* ---- license badge helper ---------------------------------------- */
function licenseBadge(r) {
  if (!r.sellable) return `<span class="badge badge-gift">${r.license}</span>`;
  return `<span class="badge badge-license">${r.license}</span>`;
}
function tierBadge(r) {
  return r.tier === "today"
    ? `<span class="badge badge-tier"><span class="dot"></span>Plays on any deck</span>`
    : `<span class="badge badge-tier hifi"><span class="dot"></span>Hi-fi setup</span>`;
}

/* ---- gallery card (homepage) ------------------------------------- */
function cardHTML(r) {
  const buy = r.sellable
    ? `<a class="btn btn-dark btn-sm" href="${r.buy}">Order a cassette</a>`
    : `<span class="badge badge-gift" title="Released under a NonCommercial license — free to keep, not for sale">Free &amp; gift only</span>`;
  return `
    <article class="inlay" style="--card-accent:${r.accent}">
      <div class="art">${relArt(r.art, r.accent)}</div>
      <div class="body">
        <div class="toptag">${licenseBadge(r)}${tierBadge(r)}</div>
        <h3>${r.title}</h3>
        <p class="flex">“${r.flex}”</p>
        <p class="decodes">${r.decodes}</p>
        <div class="actions">
          <a class="try" href="${r.try}">▶ Try in browser</a>
          ${buy}
        </div>
      </div>
    </article>`;
}

/* ---- detail row (releases.html / index detail) ------------------- */
function detailHTML(r) {
  const buy = r.sellable
    ? `<a class="btn btn-dark" href="${r.buy}">Order a cassette →</a>`
    : `<span class="badge badge-gift" style="padding:8px 12px;font-size:.7rem">Free &amp; gift only — not for sale</span>`;
  return `
    <article class="rel" id="rel-${r.id}">
      <div class="rel-art">${relArt(r.art, r.accent)}</div>
      <div class="rel-body">
        <span class="eyebrow">${r.id.replace(/-/g,' ')}</span>
        <h3>${r.title}</h3>
        <p class="flex">“${r.flex}”</p>
        <div class="rel-meta">${licenseBadge(r)}${tierBadge(r)}</div>
        <p>${r.decodes}</p>
        <div class="rel-actions">
          <a class="btn btn-primary" href="${r.try}">▶ Try in browser</a>
          ${buy}
        </div>
      </div>
    </article>`;
}

/* ---- mount ------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  const g = document.getElementById("gallery");
  if (g) g.innerHTML = RELEASES.map(cardHTML).join("");
  const d = document.getElementById("details");
  if (d) d.innerHTML = RELEASES.map(detailHTML).join("");

  // mobile nav toggle
  const t = document.querySelector(".nav-toggle");
  const nav = document.querySelector(".nav");
  if (t && nav) t.addEventListener("click", () => nav.classList.toggle("open"));
});
