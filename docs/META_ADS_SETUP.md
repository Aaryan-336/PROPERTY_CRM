# Meta Ads, Lead Ads and reel campaigns — setup

What the CRM does once this is wired:

| Feature | Where | How |
|---|---|---|
| Manage campaigns (pause, resume, budget) | `/meta-ads` | Graph Marketing API / Ads MCP, per-user token |
| **Meta Lead Ads → Leads** | `/meta-ads` → Lead intake | Webhook `POST /internal/meta/webhook`, plus "Sync now" backfill |
| **Cost per lead / per site visit** | `/meta-ads` → What your ad spend turned into | Insights joined to CRM stages |
| **Campaign ideas from reels** | `/meta-ads` → Campaign ideas | Instagram insights ranked and matched to CRM demand; creates campaigns **paused** |

## 1. Meta developer app

1. <https://developers.facebook.com> → **Create app** → business type, add the **Marketing API**
   and **Webhooks** products, and **Facebook Login for Business** (or Facebook Login).
2. **Settings → Basic**: copy the App ID and App Secret.
3. **Facebook Login → Settings → Valid OAuth Redirect URIs**:
   `https://property-crm-zgwv.onrender.com/meta-ads/oauth/callback`
4. **Webhooks → Page → Subscribe**:
   * Callback URL: `https://property-crm-zgwv.onrender.com/internal/meta/webhook`
   * Verify token: the value of `META_WEBHOOK_VERIFY_TOKEN` on Render
   * Subscribe to the **`leadgen`** field.
5. Permissions the app requests (all are asked at connect time):
   `ads_read, ads_management, business_management, pages_show_list, pages_read_engagement,
   pages_manage_metadata, leads_retrieval, instagram_basic, instagram_manage_insights`.
   While the app is in **Development mode** these work for people with a role on the app
   (Roles → add yourself as admin). Public use needs Meta **App Review** for each.

## 2. Render environment (service `PROPERTY_CRM`)

| Variable | Value |
|---|---|
| `META_APP_ID` / `META_APP_SECRET` | from step 1.2 |
| `META_REDIRECT_URI` | `https://property-crm-zgwv.onrender.com/meta-ads/oauth/callback` |
| `META_TOKEN_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — keep it stable |
| `META_WEBHOOK_VERIFY_TOKEN` | any long random string (the blueprint generates one) |
| `META_POST_CONNECT_REDIRECT` | your Vercel URL + `/meta-ads` |
| `META_DEFAULT_DAILY_BUDGET`, `META_TARGET_CITIES` | optional; defaults 500 and `Mumbai` |

## 3. In Meta, before the first reel campaign

* The **Facebook Page** must be linked to your **Instagram professional account**
  (Page settings → Linked accounts).
* Create at least one **Instant Form** (Ads Manager → Instant forms, or Page → Publishing tools →
  Lead ads forms). Ask for full name + phone (+ email); add questions like "BHK" and
  "Preferred location" and the CRM maps them to the lead's BHK and areas.

## 4. In the CRM

1. `/meta-ads` → **Connect Meta Ads** (approve every permission). With one Page it is chosen and
   subscribed to lead delivery automatically; with several, pick it in **Lead intake**.
2. **Sync now** imports any existing leads.
3. A new lead appears as a contact (source *Meta Ads*, campaign name filled in), the owner gets a
   push notification, and a repeat enquiry with the same phone is attached to the existing lead
   rather than duplicated.
4. **Campaign ideas from your reels** ranks your reels and suggests budget/audience. *Set up
   campaign* → *Create paused campaign* builds campaign + ad set + ad on Meta, all paused.
   Review in Ads Manager, then resume from the campaign list.

## How reels are ranked

`score = 50 × reach / best reach + 50 × weighted engagement / best engagement`, where weighted
engagement is `likes + 2×comments + 3×shares + 3×saves` over reach. Reels with under 200 reach
are marked "too new to judge". Reasons also cite CRM demand: if a caption names an area (e.g.
*Malad*), the card shows how many of your leads ask for it and how many listings you hold there.
