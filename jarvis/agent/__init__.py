"""The agent core (Jarvis 4): one request = a goal, a plan, a check after every step, one repair, one question.

    context.py  what's on screen right now, as text (no AI, ~0.1 s)
    ocr.py      Windows' own offline text reading, for apps that don't name their buttons
    checks.py   "did that step work?" tests against a fresh snapshot
    plan.py     Step / Plan, the plan the AI writes (JSON), validated against the real tools
    run.py      execute, verify, repair once, ask one clear question; remembered plans

Design and task suite: docs/agent-core.md.
"""
