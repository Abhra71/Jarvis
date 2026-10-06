# Which model does which job, and why

Made by `tools/assign.py --write` from the benchmark results. Do not edit by hand: re-run the benchmarks (`tools/bench.py understand --all`, `tools/bench_coding.py --repair --all`) and this tool.

Updated: 06 Oct 2026 17:23

## The chains (the router tries them in this order)

**understand:** `groq:qwen/qwen3.8-27b` → `gemini:gemini-3.5-flash-lite` → `nvidia:nvidia/nemotron-3-super-120b-a12b` → `cloudflare:@cf/openai/gpt-oss-120b`
- gemini:gemini-3.5-flash: not enough data (20 answers)
- gemini:gemini-3.8-flash: not enough data (8 answers)
- gemini:gemma-4-31b-it: not enough data (0 answers)
- leader groq:qwen/qwen3.8-27b: right 90%, wrong actions 5%, 0.6 s, available 98%
- then gemini:gemini-3.5-flash-lite: right 85%, wrong actions 8%, 1.0 s, available 100%
- then nvidia:nvidia/nemotron-3-super-120b-a12b: right 78%, wrong actions 11%, 3.8 s, available 99%
- then cloudflare:@cf/openai/gpt-oss-120b: right 78%, wrong actions 12%, 1.9 s, available 99%

**code:** `gemini:gemini-3.5-flash-lite` → `nvidia:nvidia/nemotron-3-super-120b-a12b` → `groq:openai/gpt-oss-120b` → `groq:openai/gpt-oss-20b`
- cloudflare:@cf/meta/llama-3.3-70b-instruct-fp8-fast: not enough data (0 answers)
- cloudflare:@cf/openai/gpt-oss-120b: not enough data (0 answers)
- cloudflare:@cf/qwen/qwen3-30b-a3b-fp8: not enough data (0 answers)
- leader gemini:gemini-3.5-flash-lite: right 94%, wrong actions 2%, 1.6 s, available 100%
- then nvidia:nvidia/nemotron-3-super-120b-a12b: right 93%, wrong actions 1%, 5.9 s, available 99%
- then groq:openai/gpt-oss-120b: right 92%, wrong actions 2%, 0.8 s, available 100%
- then groq:openai/gpt-oss-20b: right 91%, wrong actions 2%, 0.6 s, available 100%

## Understanding: the user's real sentences

Each model got the same 167 sentences (a fixed sample of the 537 the user really said, labelled by hand with the screen they were said on). *Wrong action* = it acted, but wrongly or where it should have asked/ignored: the worst outcome. *Available* = calls that got an answer (the free tiers are sometimes overloaded).

| Model | Sentences | Available | Right | Wrong action | Wrong kind | Missing detail | No answer | Median s | Slow 10% s | Tokens in/out (cached) | act | ignore | chat | ask | code | refuse | control |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| groq:qwen/qwen3.8-27b | 152 | 98% | **89%** | 5% | 5% | 0% | 1% | 0.6 | 1.2 | 1417/179 (0) | 71/76 | 19/21 | 9/12 | 10/14 | 17/18 | 5/5 | 5/6 |
| gemini:gemini-3.1-flash-lite | 167 | 82% | **86%** | 8% | 4% | 1% | 2% | 4.4 | 13.9 | 1369/29 (0) | 72/80 | 15/22 | 10/12 | 10/14 | 28/28 | 4/5 | 4/6 |
| gemini:gemini-3.5-flash-lite | 167 | 100% | **85%** | 8% | 5% | 2% | 0% | 1.0 | 1.3 | 1395/26 (0) | 69/80 | 19/22 | 11/12 | 9/14 | 24/28 | 4/5 | 6/6 |
| nvidia:nvidia/nemotron-3-super-120b-a12b | 167 | 99% | **78%** | 11% | 8% | 2% | 1% | 3.8 | 8.8 | 1374/387 (0) | 67/80 | 14/22 | 9/12 | 12/14 | 24/28 | 1/5 | 3/6 |
| cloudflare:@cf/openai/gpt-oss-120b | 167 | 99% | **78%** | 12% | 9% | 1% | 1% | 1.9 | 5.1 | 1372/100 (0) | 72/80 | 16/22 | 8/12 | 10/14 | 18/28 | 2/5 | 4/6 |
| groq:openai/gpt-oss-120b | 167 | 100% | **77%** | 12% | 8% | 2% | 0% | 0.7 | 1.5 | 1415/83 (897) | 69/80 | 15/22 | 6/12 | 11/14 | 21/28 | 3/5 | 4/6 |
| cloudflare:@cf/meta/llama-3.3-70b-instruct-fp8-fast | 167 | 100% | **72%** | 22% | 4% | 2% | 0% | 1.5 | 2.9 | 1348/32 (0) | 63/80 | 14/22 | 8/12 | 4/14 | 26/28 | 1/5 | 4/6 |
| cloudflare:@cf/qwen/qwen3-30b-a3b-fp8 | 167 | 88% | **71%** | 7% | 13% | 1% | 8% | 3.2 | 6.6 | 1231/406 (0) | 65/80 | 13/22 | 7/12 | 14/14 | 15/28 | 3/5 | 2/6 |
| groq:openai/gpt-oss-20b | 167 | 100% | **63%** | 19% | 16% | 2% | 0% | 0.7 | 1.3 | 1415/106 (596) | 64/80 | 7/22 | 6/12 | 12/14 | 13/28 | 1/5 | 2/6 |
| gemini:gemini-3.5-flash | 37 | 29% | **46%** | 8% | 0% | 0% | 46% | 2.4 | 3.7 | 750/25 (0) | 13/22 | 0/4 | 2/3 | 0/3 | - | 2/3 | 0/2 |
| nvidia:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning | 98 | 31% | **40%** | 8% | 11% | 3% | 38% | 13.8 | 18.3 | 862/339 (0) | 21/45 | 4/13 | 3/9 | 3/7 | 5/16 | 1/3 | 2/5 |
| gemini:gemini-3.8-flash | 37 | 12% | **19%** | 3% | 0% | 0% | 78% | 4.4 | 10.5 | 300/6 (0) | 6/22 | 1/4 | 0/3 | 0/3 | - | 0/3 | 0/2 |
| gemini:gemma-4-31b-it | 36 | 0% | **0%** | 0% | 0% | 0% | 100% | 0.0 | 0.0 | 0/0 (0) | 0/22 | 0/4 | 0/3 | 0/3 | - | 0/3 | 0/1 |

## Coding: Java (BlueJ) and C++ (VS Code)

118 cases: the user's 25 real coding sentences on the file they had, plus 93 student-style ones. Every edit compiled by the real javac / g++. With one repair try (as Jarvis runs it).

| Model | Cases | Right | User's own | Doesn't compile | Wrong code | Wrote instead of asking | Asked instead of writing | No answer | Median s | Slow 10% s |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini:gemini-3.5-flash-lite | 118 | **94%** | 22/25 | 0% | 3% | 2% | 2% | 0% | 1.6 | 2.3 |
| nvidia:nvidia/nemotron-3-super-120b-a12b | 118 | **92%** | 21/25 | 0% | 3% | 1% | 3% | 1% | 5.9 | 12.5 |
| groq:openai/gpt-oss-120b | 118 | **92%** | 21/25 | 0% | 4% | 2% | 2% | 0% | 0.8 | 1.2 |
| groq:openai/gpt-oss-20b | 118 | **91%** | 22/25 | 0% | 5% | 2% | 3% | 0% | 0.6 | 0.9 |
| cloudflare:@cf/meta/llama-3.3-70b-instruct-fp8-fast | 4 | **0%** | 0/4 | 0% | 0% | 0% | 0% | 100% | 0.0 | 0.0 |
| cloudflare:@cf/openai/gpt-oss-120b | 14 | **0%** | 0/14 | 0% | 0% | 0% | 0% | 100% | 0.0 | 0.0 |
| cloudflare:@cf/qwen/qwen3-30b-a3b-fp8 | 14 | **0%** | 0/14 | 0% | 0% | 0% | 0% | 100% | 0.0 | 0.0 |
