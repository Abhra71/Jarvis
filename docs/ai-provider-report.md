# AI provider comparison (26 Sep 2026)

Measured with `tools/ai_eval.py`:
- **text:** 16 spoken commands. Did the AI pick the right action?
- **screen:** 12 click tasks on synthetic pages (`tools/eval_screens.py`): a video site with an ad and a pop-up, and chess boards from both sides. Did the click land on the target?

All tests used a system prompt with fake names, so no personal data was sent. Raw results are in `logs/ai_eval.jsonl`; summarise them with `tools/eval_report.py`.

## Rules (the user's constraints)
Free, **renewing** (not a one-time credit), no card, fast enough for voice, and reliable.

## Results

| Model | Commands | Screen clicks | Typical / slowest | Tokens in per request | Notes |
|---|---|---|---|---|---|
| Gemini 3.5 Flash-Lite | **16/16** | **10/12** | 1.4 s / 2.0 s (screen 2.5 / 3.1) | 3,300 / 4,400 | Best all-rounder; misses were only on the flipped (Black) board |
| Gemini 3.1 Flash-Lite (current) | 18/18 (earlier run) | 9/12 | 1.3 s (screen 2.5 / 3.1) | 3,300 / 4,400 | All 3 screen misses: left out `y2` in click_pair (a tool-design problem) |
| Groq gpt-oss-120b | 15/16 | can't see | **1.1 s / 1.9 s** | 2,200 | Fast and accurate for commands |
| Groq gpt-oss-20b | 15/16 | can't see | **0.9 s / 1.9 s** | 2,200 | Fastest |
| OpenRouter Nemotron-3 Super (free) | 14/16 | can't see | 2.9 s / 9.5 s | 4,000 | Its 2 misses spoke its own thinking aloud |
| NVIDIA Muse Glimmer-30B | 11/16 | 7/12 | 5.8 s / 22 s (screen 12 / 32 s) | 3,800 | Too slow and less accurate |
| Gemma 4 31B (Gemini API) | — | — | ~22 s | — | Too slow for voice |
| Gemini 3.8 Flash | — | — | 7 s | — | Free allowance used up after 1 request |
| NVIDIA Kimi K3, GLM-5.3, DeepSeek V4.1, Nemotron | — | — | no answer in 40–60 s | — | NVIDIA's free service didn't respond all evening |
| OpenRouter Qwen 3.8 (free) | — | — | timeouts, then "rate-limited upstream" | — | Overloaded |
| OpenRouter Inkling (free) | — | — | refused | — | "Only available on agentic harnesses" |
| Groq Qwen 3.8 (vision) | — | — | 0.5–1.1 s | — | Daily token cap reached before it could be tested |
| Mistral (free plan: $10/month credit) | — | — | — | — | Account allows 0 requests/min: API not enabled yet |

## Free limits (measured from the providers' own replies)
- **Groq:**
  - Per model: 1,000 requests/day, **8,000 tokens/min**, **200,000 tokens/day**.
  - It counts `max_tokens` against the per-minute limit up front, so a request with a screenshot and a 2,048-token answer budget is refused as "too large".
- **OpenRouter:** 50 free requests/day; the key expires 2027-03-25.
- **Cerebras:** now a one-time $5 trial (needs a card, 30 days, 5 req/min). Rejected.
- **GitHub Models:** retired on 30 Jul 2026.
- **DeepSeek (own API):** one-time 5M tokens, then paid; text only.
- **Gemini:** Flash-Lite free tier is about 1,000–1,500 requests/day (the user checked AI Studio). Gemini 3.8 Flash has a tiny free allowance.

## Conclusions
1. **Tokens are the bottleneck, not speed.**
   - Every request sends 2,200–4,400 tokens, mostly the full list of 30 tools plus instructions.
   - Groq's 8k/min and 200k/day caps mean only ~2 requests a minute and ~50–90 a day per model.
   - Sending only the tools each request type needs, and a shorter prompt, should cut this by 2–3×. That multiplies the free capacity by the same amount.
2. **No single winner, so split the jobs:**
   - **commands:** Groq gpt-oss (≈1 s);
   - **screen:** Gemini 3.5 Flash-Lite;
   - **backups:** the other Groq model, then Gemini 3.1 Flash-Lite, then OpenRouter Nemotron; plus Mistral once enabled.
3. **Chess must not rely on AI vision.** Flipped boards were missed, and the AI mangled two-click arguments. Squares should be computed in code (the site-skill plan).
4. `click_pair` should take squares or element names, not six numbers.

## After v3 steps 2–3: smaller requests (26 Sep, evening)
Each request now carries only the tools and prompt rules its kind of job needs (`jarvis/router.py`); the AI can ask for more with `more_tools`. Same test sets, same fake names.

| Model | Commands | Screen clicks | Typical / slowest | Tokens in per request |
|---|---|---|---|---|
| Groq gpt-oss-120b | **16/16** (was 15/16) | can't see | 0.8 s / 1.4 s | **1,070** (was 2,200) |
| Groq gpt-oss-20b | **16/16** (was 15/16) | can't see | 0.7 s / 1.0 s | **1,070** (was 2,200) |
| Gemini 3.5 Flash-Lite | 15/16 (was 16/16) | **11/12** (was 10/12) | 0.9 s / 1.3 s (screen 1.6 / 1.8 s) | 1,440 / 3,360 with a screenshot (was 3,300 / 4,400) |

- Gemini's one command "miss" asked for the typing tools on "send hi to mom on whatsapp" instead of opening WhatsApp first: harmless (sending needs a spoken yes anyway).
- The screen miss is the flipped (Black) board again; chess squares will be computed in code (step 5).
- About half the tokens per request means about twice as many requests fit in Groq's 8k/min and 200k/day.

## After v3 step 4: the screen as text (26 Sep, evening)
Suite `elements` in `tools/ai_eval.py`: 12 requests on item lists like the ones UI Automation reads from YouTube, Physics Wallah and chess.com (made-up names). Right answer = `click_element` on the right item.

| Model | Right item | Typical / slowest | Tokens in |
|---|---|---|---|
| Groq gpt-oss-120b | **12/12** | 0.8 s / 1.5 s | 1,800 |
| Groq gpt-oss-20b | 11/12 (once replied without clicking) | 0.7 s / 1.0 s | 1,800 |
| Gemini 3.5 Flash-Lite | 12/12 | 1.1 s / 8.7 s (one slow reply) | 2,500 |

Compared with clicking from a screenshot (10–11/12, 1.5–2.5 s, ~3,400 tokens), named items are exact and need no picture.
