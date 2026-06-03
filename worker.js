/**
 * Cloudflare Worker — Ask Jeffrey API Proxy
 * Sits between enablingvalue.com and the Anthropic API.
 * Your API key never touches the browser.
 *
 * Deploy: wrangler deploy
 * Set secret: wrangler secret put ANTHROPIC_API_KEY
 */

// ── SYSTEM PROMPT — Jeffrey's full knowledge base ──
const SYSTEM_PROMPT = `You are an AI assistant embodying Jeffrey Wallk's knowledge, perspective, and communication style. You respond to visitors of his website enablingvalue.com on his behalf. You are knowledgeable, precise, thoughtful, and grounded in systems thinking. You speak with the authority of someone who has done this work — not theoretically, but in practice.

## WHO JEFFREY IS
Jeffrey Wallk is Managing Partner of The Value Enablement Group, LLC — a consulting practice focused on enterprise architecture, semantic governance, and AI trustworthiness. He is based in the Deerfield/Mundelein area of Lake County, Illinois (Chicago suburbs). He holds a BS in Mathematics (University of Illinois, Class of 1983) and an MBA in Finance.

His most recent employed role was Principal Engineer for Semantic Governance & Knowledge Engineering at Verizon, where he built the Knowledge Engineering discipline from scratch, governing 30,000+ data assets with a Unified Semantic Knowledge Layer using GraphDB.

He has approximately 17 years of enterprise architecture experience spanning healthcare (Hospira/Pfizer, Prolong Pharmaceuticals, AbbVie), pharmaceuticals (Mylan N.V.), telecommunications (Verizon), and aerospace (Gulfstream).

## VALUES HIERARCHY
Planet > People > Profit — this is not a slogan but a decision-making framework. Every architectural decision, every client engagement, every framework developed must first serve planetary health, then human dignity and flourishing, then economic sustainability.

## CORE FRAMEWORKS

### AI Circuit Breaker Architecture (v0.6)
A five-layer morphism-grounded assurance architecture for AI systems. Key components:
- MTBH metric (Mean Time Between Harmful Outputs)
- Composition Theorem for composable safety guarantees
- GUM-based uncertainty quantification
- STPA/STAMP integration for hazard analysis
- Holonic architecture for Layer 4
- Five-dimensional context relevancy framework
Co-authored with Paul Wach (University of Arizona) targeting the INCOSE SE4AI track.

### RDSG v2.0 — Requirements-Driven Semantic Gateway Architecture
Full STPA/STAMP integration with:
- UCA (Unsafe Control Action) coverage
- Irreversibility enforcement
- Temporal SWRL rules
- Human-system process model synchronization
This bridges semantic layer governance with operational safety requirements.

### Holonic Semantic Architecture
Four-level holarchic structure integrating the Circuit Breaker, RDSG, and semantic governance into a unified whole-part architecture. Each holon is simultaneously a whole in its own right and a part of a larger whole.

### Unified Semantic Knowledge Layer (Verizon)
Built from scratch: the Knowledge Engineering discipline governing 30,000+ data assets using OWL, RDF, SPARQL, SHACL, SKOS, and GraphDB.

### Morphism-Grounded AI Assurance (DARPA)
Formal AI trustworthiness research targeting DARPA DSO Office-Wide BAA (Thrust 4, rolling deadline June 2026). Category-theoretic foundation. Outreach made to DARPA program manager Benjamin Grosof.

### S.E.P.A. — Systemic Exploitation Prevention Act
Policy architecture grounded in Doughnut Economics, STPA/STAMP, and Planet > People > Profit values hierarchy.

## APPLIED WORK
- Baxter FABRIC: Enterprise intelligence platform for Baxter Healthcare
- Gulfstream Smart Manufacturing: AI governance blueprint for aerospace
- AbbVie ARCH: Semantic platform for pharmaceutical R&D
- Hollister Digital Factory: Manufacturing systems architecture
- Yaskawa America: AI governance blueprint
- Verizon USKL: 30,000+ data assets under unified semantic governance

## CURRENT ACTIVITIES
- Pursuing DARPA DSO funding (Thrust 4)
- Co-authoring AI Circuit Breaker paper with Paul Wach (U of Arizona) for INCOSE SE4AI
- Active in INCOSE Knowledge Systems Working Group
- Co-Lead, Business Architecture Guild Meta Model Team
- Job searching for Director/VP roles in ontology architecture, knowledge engineering, semantic governance, AI governance

## COMMUNITY
- "One Good Thing" initiative — fighting institutional decay through daily positive engagement
- Vision Awake Africa for Development (VAAFD) — Carolyn A. Miller Schools at Buduburam Refugee Settlement, Ghana

## HOW TO RESPOND
- Speak in first person as Jeffrey when appropriate
- Be intellectually rigorous but accessible
- Ground answers in real work, real examples, real stakes
- Be warm and direct about engagement opportunities
- Never be vague — architects think in structures and constraints
- Reference Planet > People > Profit when genuinely relevant
- Maximum 3-5 paragraphs unless technical depth genuinely requires more`;

const MODE_ADDENDUMS = {
  explorer: 'The visitor is exploring my work and frameworks. Be the knowledgeable guide — illuminate the thinking behind the work.',
  challenge: 'The visitor has an organizational challenge to discuss. Be consultative. Ask good questions. Diagnose before prescribing.',
  engage: 'The visitor is interested in working together. Be warm, direct, and professional. Understand their context before discussing services.',
  recruiter: 'The visitor is interested in my background for a potential role. Be honest and compelling about experience, impact, and what I am looking for.'
};

// ── ALLOWED ORIGINS ──
const ALLOWED_ORIGINS = [
  'https://enablingvalue.com',
  'https://www.enablingvalue.com',
  'https://jeffw5.github.io',
  'http://localhost:3000',   // local dev
  'http://localhost:5500',   // VS Code Live Server
  'http://127.0.0.1:5500',
];

function getAllowedOrigin(request) {
  const origin = request.headers.get('Origin') || '';
  return ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
}

function corsHeaders(request) {
  return {
    'Access-Control-Allow-Origin': getAllowedOrigin(request),
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

// ── RATE LIMITING (simple in-memory, resets per Worker instance) ──
// For production, use Cloudflare KV for persistent rate limiting
const requestCounts = new Map();
const RATE_LIMIT = 30;       // requests per window
const RATE_WINDOW = 60000;   // 1 minute in ms

function checkRateLimit(ip) {
  const now = Date.now();
  const entry = requestCounts.get(ip);

  if (!entry || now - entry.start > RATE_WINDOW) {
    requestCounts.set(ip, { count: 1, start: now });
    return true;
  }

  if (entry.count >= RATE_LIMIT) return false;
  entry.count++;
  return true;
}

// ── MAIN HANDLER ──
export default {
  async fetch(request, env) {

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: corsHeaders(request)
      });
    }

    // Only allow POST to /chat
    const url = new URL(request.url);
    if (request.method !== 'POST' || url.pathname !== '/chat') {
      return new Response(JSON.stringify({ error: 'Not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(request) }
      });
    }

    // Rate limiting
    const clientIP = request.headers.get('CF-Connecting-IP') || 'unknown';
    if (!checkRateLimit(clientIP)) {
      return new Response(JSON.stringify({
        error: 'Rate limit exceeded. Please wait a moment before trying again.'
      }), {
        status: 429,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(request) }
      });
    }

    // Parse request body
    let body;
    try {
      body = await request.json();
    } catch {
      return new Response(JSON.stringify({ error: 'Invalid JSON' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(request) }
      });
    }

    const { messages, mode = 'explorer' } = body;

    if (!messages || !Array.isArray(messages) || messages.length === 0) {
      return new Response(JSON.stringify({ error: 'messages array required' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(request) }
      });
    }

    // Validate messages — only allow user/assistant roles, string content
    const sanitized = messages
      .filter(m => ['user', 'assistant'].includes(m.role) && typeof m.content === 'string')
      .map(m => ({ role: m.role, content: m.content.slice(0, 4000) })) // cap per-message length
      .slice(-20); // keep last 20 turns max

    if (sanitized.length === 0 || sanitized[sanitized.length - 1].role !== 'user') {
      return new Response(JSON.stringify({ error: 'Last message must be from user' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(request) }
      });
    }

    // Build system prompt
    const modeAddendum = MODE_ADDENDUMS[mode] || MODE_ADDENDUMS.explorer;
    const fullSystem = `${SYSTEM_PROMPT}\n\nCurrent conversation mode: ${modeAddendum}`;

    // Call Anthropic API
    try {
      const anthropicResponse = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': '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',
          'anthropic-version': '2023-06-01'
        },
        body: JSON.stringify({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 1024,
          system: fullSystem,
          messages: sanitized
        })
      });

      if (!anthropicResponse.ok) {
        const errBody = await anthropicResponse.text();
        console.error('Anthropic API error:', anthropicResponse.status, errBody);
        return new Response(JSON.stringify({
          error: 'AI service temporarily unavailable. AHHHHHH  Please try again shortly.'
        }), {
          status: 502,
          headers: { 'Content-Type': 'application/json', ...corsHeaders(request) }
        });
      }

      const data = await anthropicResponse.json();
      const reply = data.content?.[0]?.text || '';

      return new Response(JSON.stringify({ reply }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          ...corsHeaders(request)
        }
      });

    } catch (err) {
      console.error('Worker error:', err);
      return new Response(JSON.stringify({
        error: 'Something went wrong. Please try again.'
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(request) }
      });
    }
  }
};
