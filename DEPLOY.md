# Ask Jeffrey — Deployment Guide
## enablingvalue.com + Cloudflare Worker Backend

---

## File Overview

| File | Where It Goes | Purpose |
|---|---|---|
| `index.html` | GitHub repo root | Landing page / storyboard |
| `avatar.html` | GitHub repo root | Jarvis interface (calls Worker) |
| `worker.js` | Cloudflare Workers | Secure API proxy (holds your key) |
| `wrangler.toml` | Local deploy folder | Cloudflare config |
| `CNAME` | GitHub repo root | Custom domain binding |

---

## STEP 1 — Set Up GitHub Pages (5 min)

```bash
# Create the repo on github.com: jeffw5/enablingvalue (public)
git clone https://github.com/jeffw5/enablingvalue
cd enablingvalue

# Copy index.html and avatar.html into this folder
cp /path/to/index.html .
cp /path/to/avatar.html .

# Add custom domain file
echo "enablingvalue.com" > CNAME

git add .
git commit -m "Launch enablingvalue.com"
git push origin main
```

Then in GitHub: **Settings → Pages → Source: main branch → root (/) → Save**

Your site will be live at `https://jeffw5.github.io/enablingvalue` within ~60 seconds.

---

## STEP 2 — Deploy the Cloudflare Worker (10 min)

### 2a. Install Wrangler (Cloudflare's CLI)

```bash
npm install -g wrangler
```

### 2b. Log in to Cloudflare

```bash
wrangler login
# Opens browser — log in with your Cloudflare account
# (Free account works fine — create one at cloudflare.com if needed)
```

### 2c. Create a deployment folder

```bash
mkdir ask-jeffrey-worker
cd ask-jeffrey-worker
cp /path/to/worker.js .
cp /path/to/wrangler.toml .
```

### 2d. Deploy the Worker

```bash
wrangler deploy
```

Output will include your Worker URL — something like:
```
https://ask-jeffrey.YOUR-SUBDOMAIN.workers.dev
```

**Copy this URL** — you'll need it in Step 3.

### 2e. Set your Anthropic API key as a secret (NEVER in code)

```bash
wrangler secret put ANTHROPIC_API_KEY
# Paste your key when prompted: sk-ant-api03-...
# It is encrypted and never visible in logs or source
```

Test it works:
```bash
curl -X POST https://ask-jeffrey.YOUR-SUBDOMAIN.workers.dev/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Who is Jeffrey Wallk?"}],"mode":"explorer"}'
```

You should get a JSON response: `{"reply":"..."}`

---

## STEP 3 — Connect avatar.html to Your Worker (2 min)

Open `avatar.html` and find line ~990:

```javascript
const WORKER_URL = 'https://ask-jeffrey.YOUR-SUBDOMAIN.workers.dev/chat';
```

Replace `YOUR-SUBDOMAIN` with your actual Cloudflare subdomain, then:

```bash
cd /path/to/enablingvalue-repo
git add avatar.html
git commit -m "Wire avatar to Worker endpoint"
git push
```

---

## STEP 4 — Connect Your Custom Domain (15 min)

### At your domain registrar (wherever enablingvalue.com is registered):

Add these DNS records:

**For GitHub Pages (the website):**
```
Type: CNAME
Name: www
Value: jeffw5.github.io
TTL: 3600

Type: A
Name: @
Value: 185.199.108.153
Value: 185.199.109.153
Value: 185.199.110.153
Value: 185.199.111.153
TTL: 3600
```

**For Cloudflare Worker (optional — custom API subdomain):**
```
Type: CNAME
Name: api
Value: ask-jeffrey.YOUR-SUBDOMAIN.workers.dev
TTL: 3600
```

If you add the `api.enablingvalue.com` subdomain, update `wrangler.toml` (uncomment the routes section) and update `WORKER_URL` in `avatar.html` to `https://api.enablingvalue.com/chat`.

DNS propagation: 5 minutes to 48 hours (usually under 30 min).

---

## STEP 5 — Verify Everything

Visit:
- `https://enablingvalue.com` → landing page loads ✓
- `https://enablingvalue.com/avatar.html` → chat interface loads ✓
- Type a message → response comes back from Jeffrey ✓

---

## Updating Content

**To update Jeffrey's knowledge base** (what the assistant knows):
Edit the `SYSTEM_PROMPT` constant in `worker.js` and redeploy:
```bash
cd ask-jeffrey-worker
wrangler deploy
```

**To update the website design:**
Edit `index.html` or `avatar.html`, commit, and push to GitHub.

**To add new portfolio items:**
Edit the portfolio section in `index.html`.

---

## Cost Estimate

| Service | Free Tier | Paid |
|---|---|---|
| GitHub Pages | Free (unlimited) | — |
| Cloudflare Workers | 100,000 req/day free | $5/mo for 10M req |
| Anthropic API | Pay per use | ~$0.003 per conversation |

For typical consulting traffic (hundreds of visitors/month), total cost: **under $5/month**, almost entirely Anthropic API usage.

---

## Rate Limiting

The Worker is configured to allow **30 requests per minute per IP address**.
To adjust, edit `RATE_LIMIT` and `RATE_WINDOW` in `worker.js`.

For production with higher traffic, switch to Cloudflare KV for persistent rate limiting:
```bash
wrangler kv:namespace create "RATE_LIMITS"
# Then add KV binding to wrangler.toml
```

---

## Troubleshooting

**"Failed to fetch" error in browser:**
- Check that WORKER_URL in avatar.html matches your deployed Worker URL exactly
- Verify CORS: your domain must be in the ALLOWED_ORIGINS array in worker.js

**Worker returns 502:**
- Your ANTHROPIC_API_KEY secret may not be set. Run: `wrangler secret put ANTHROPIC_API_KEY`

**GitHub Pages not showing custom domain:**
- Verify CNAME file contains exactly: `enablingvalue.com`
- Check DNS records are set correctly at your registrar

---

*Built for Jeffrey Wallk · The Value Enablement Group, LLC*
*enablingvalue.com · knowledge-architects.org*
