# Shop setup — The Magnetic Vault

A practical owner guide. The storefront is static HTML; payments are **hosted
checkout links** (Stripe Payment Links or Gumroad). **No API keys or card
handling live anywhere in this repo** — a Payment Link is just a URL, and that
is the entire security model. You paste a URL; Stripe/Gumroad does the rest
(PCI, card data, receipts) on their own pages.

Everything you edit day-to-day is in **`assets/releases.js`**, in the
`RELEASES` array near the top. Each release object has three fields you'll touch:

| field | what it does |
|-------|--------------|
| `status`    | `'available'` → priced Order button · `'sold_out'` → greyed + "email me when it's back" · `'gift_only'` → free badge, never sold |
| `order_url` | the hosted checkout URL for this tape (Stripe or Gumroad) |
| `price_eur` | the price in euros, as a plain number (shipping is added at checkout) |

There is no build step. Edit the file, save, reload the page.

---

## (a) Create a Stripe Payment Link (recommended)

One link per product. Takes about two minutes each.

1. Log in to the [Stripe Dashboard](https://dashboard.stripe.com/).
2. Go to **Product catalog → Payment links → + New** (or **Payments → Payment Links**).
3. **Add a product**: name it (e.g. *"The Willows — cassette"*), set the price
   in **EUR** to match `price_eur` in `releases.js`. Use a **one-time** price
   (not a subscription).
4. Under the link's options, **turn on "Collect customers' shipping addresses"**.
5. Add **shipping rates** (Dashboard → Settings → Shipping, or inline on the
   link): create at least one rate (e.g. *Sweden*, *EU*, *Worldwide*) so the
   "+ shipping calculated at checkout" promise on the site holds true.
6. *(Optional but recommended)* limit the country list to where you'll actually
   ship, and set a quantity limit if you want a hard cap per order.
7. **Create the link.** Stripe gives you a URL like
   `https://buy.stripe.com/abc123XYZ`.
8. Paste it into the matching release's `order_url` in `assets/releases.js`,
   replacing the `STRIPE_PAYMENT_LINK_<slug>` placeholder:

   ```js
   order_url: "https://buy.stripe.com/abc123XYZ",
   ```

Repeat for each sellable release. The placeholders currently in the file are:

```
doom                  → STRIPE_PAYMENT_LINK_doom
deck-test             → STRIPE_PAYMENT_LINK_the-deck-test
willows               → STRIPE_PAYMENT_LINK_the-willows
console               → STRIPE_PAYMENT_LINK_the-console
grandmaster           → STRIPE_PAYMENT_LINK_grandmaster
great-library         → STRIPE_PAYMENT_LINK_the-great-library
svenska               → STRIPE_PAYMENT_LINK_den-svenska-samlingen
modern-shelf          → (none — gift only, never sold)
```

> Until you replace a placeholder, that release's Order button links to the
> literal placeholder string. Swap them all before going live.

---

## (b) Prefer Gumroad? Same idea, different URL

Gumroad works identically from the site's point of view — it's just a hosted URL.

1. Create a product in [Gumroad](https://gumroad.com/) (set price in EUR,
   enable **"I want to ship this product"** so it collects a shipping address,
   and add your shipping rates).
2. Publish it and copy the product URL, e.g.
   `https://yourname.gumroad.com/l/the-willows`.
3. Paste that into `order_url` exactly as you would a Stripe link:

   ```js
   order_url: "https://yourname.gumroad.com/l/the-willows",
   ```

Nothing else changes — the button, the price, and the "+ shipping at checkout"
note all still work. (If you go all-Gumroad, you can soften the word "Stripe"
in the checkout note inside `assets/releases.js` → `checkoutNote()` and in the
order sections of `index.html` / `releases.html`.)

---

## (c) Mark a release sold out (and bring it back)

When a small batch runs out, flip one field. Open `assets/releases.js`, find the
release, and set:

```js
status: "sold_out",
```

The site immediately swaps the Order button for a greyed **"Sold out"** chip and
shows a **"✉ Email me when it's back"** mailto link (it points at
`RESTOCK_EMAIL`, set near the bottom of the `RELEASES` array — change it there).

When you've recorded more, set it back:

```js
status: "available",
```

`DOOM` and `The Great Library` currently ship as `sold_out` to demonstrate the
state — flip them to `available` once their links and stock are ready.

`The Modern Shelf` stays `gift_only` (NonCommercial license → never sold).

---

## Quick reference

- **Price change** → edit `price_eur` (plain number, euros).
- **New checkout provider** → just paste a different URL into `order_url`.
- **Out of stock** → `status: "sold_out"`. **Back in stock** → `status: "available"`.
- **Restock notification address** → `RESTOCK_EMAIL` at the bottom of `RELEASES`.
- **The disclaimer** customers are pointed to before ordering → `disclaimer.html`.

No secrets, no keys, no server. The repo can stay fully public.
