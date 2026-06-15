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

## (d) Coupons / promo codes

The site does **no discount math** and stores **no discount logic**. A coupon's
real value is created, validated, and applied entirely by **Stripe at checkout**
(a Stripe *promotion code*). The site's only job is to *surface* the code and tell
buyers to type it into the code box on Stripe's checkout page. The list price you
show stays the list price — Stripe charges the discounted total. This is the secure
design: a coupon can't be forged from the browser, because the browser never
computes it.

There are two layers, and you set up both: the **coupon** (the discount rule, e.g.
"10% off") and the **promotion code** (the customer-facing string they type, e.g.
`LAUNCH10`).

### 1. Create the coupon in Stripe

1. In the [Stripe Dashboard](https://dashboard.stripe.com/), go to
   **Product catalog → Coupons → + New** (older UIs: **Products → Coupons**).
2. Choose the discount: **Percentage off** (e.g. `10`%) or **Fixed amount off**
   (e.g. `€5` — match the currency to your prices, EUR).
3. *(Optional)* set limits: an **expiry date**, a **max number of redemptions**
   (a hard cap, e.g. first 50 orders), or **once / forever / multiple months**
   duration (for one-time tape sales, "Once" is fine).
4. Save. The coupon now exists but has **no customer-facing code yet** — that's
   the next step.

### 2. Create a PROMOTION CODE for it

The promotion code is the human string buyers actually type.

1. Open the coupon you just made → **Promotion codes → + Add code** (or
   **Create promotion code**).
2. Set the **code** to a clean, memorable string — `LAUNCH10`. (Codes are
   case-insensitive at checkout but conventionally uppercase.)
3. *(Optional)* add per-code limits: first-time customers only, minimum order
   amount, its own expiry / redemption cap.
4. Save. `LAUNCH10` is now a live code attached to the 10%-off coupon.

> You can attach several promotion codes to one coupon (e.g. `LAUNCH10` and
> `FRIEND10` both = 10% off), and run different coupons over time.

### 3. Turn ON "Allow promotion codes" on each Payment Link

A code box only appears at checkout if the Payment Link allows it. **This is the
step people forget** — without it the buyer has nowhere to type the code.

1. For **each** sellable release's Payment Link: open it in the Dashboard →
   **Payment Links → (the link) → Edit**.
2. Find **"Allow promotion codes"** (under the link's options / *Advanced*) and
   **switch it on**. Save.
3. Repeat for every Payment Link you want the promo to work on. (New links: tick
   the same option when you create them.)

Now the Stripe checkout page for that product shows an **"Add promotion code"**
field; the buyer enters `LAUNCH10` and Stripe applies the discount to the total.

### 4. Flip the site banner on/off + set the code

Open **`assets/releases.js`** and edit the `PROMO` block near the top (just below
`RESTOCK_EMAIL`):

```js
const PROMO = {
  active: true,                    // false → no banner, no "have a code?" line
  code:  "LAUNCH10",               // must EXACTLY match the Stripe promotion code
  label: "10% off your first tape",
  note:  "enter the code at checkout"
};
```

- `active: true` renders a slim, **dismissible** ferric banner near the top of the
  homepage and the releases page, and adds a *"Have a discount code? Enter it at
  checkout."* line to each sellable release's checkout note.
- `active: false` removes all of that — nothing promo-related shows.
- `code` is shown to buyers for reference only; **it is never applied client-side.**
  Make it match the Stripe promotion code character-for-character so people copy
  the right thing.

Dismissals are remembered per-code in the browser's `localStorage`, so changing
`code` to a new promotion (e.g. `SUMMER15`) shows the banner again to everyone.

> **Reminder:** the three Stripe steps above are what make the discount real.
> Flipping `PROMO.active` alone only advertises a code — if you skip step 3
> ("Allow promotion codes"), buyers will see the code on the site but have no box
> to enter it at checkout.

**Gumroad equivalent:** Gumroad calls these **Discounts** — create a discount code
under your product's **Discounts** tab (percent or amount off, optional expiry /
quantity cap); Gumroad's checkout always shows a code field, so there's no
"allow codes" toggle. Put the same code in `PROMO.code`.

---

## Quick reference

- **Price change** → edit `price_eur` (plain number, euros).
- **New checkout provider** → just paste a different URL into `order_url`.
- **Out of stock** → `status: "sold_out"`. **Back in stock** → `status: "available"`.
- **Run a promo** → make a Stripe coupon + promotion code, switch on "Allow
  promotion codes" on each Payment Link, then set `PROMO.active = true` and
  `PROMO.code` in `releases.js`. **End it** → `PROMO.active = false`.
- **Restock notification address** → `RESTOCK_EMAIL` at the bottom of `RELEASES`.
- **The disclaimer** customers are pointed to before ordering → `disclaimer.html`.

No secrets, no keys, no server. The repo can stay fully public.
