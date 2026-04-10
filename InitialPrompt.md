**Initial prompt to create a plan for my Local LLM to write the nmon App. Claude improved on the prompt (final version is in nmon_prompt.md) and Claudes criticism of the initial prompt is included below.**

**Claude to LocalLLM Prompt - nmon**

**Nvidia Monitor**

I want you to review my prompt and improve it. my prompt is as follows "

I want to create an App that monitors my Nvidia card (s) Temperature and Memory use, named nmon. To implement this, I have a local LLM server (Ollama) installed at http://192.168.1.126:11434. On my local LLM server, I have an RTX 3090 and the loaded model is devstral Small 2. I want Claude to write a plan for my locall LLM to execute. I have aider installed.

1. nmon will monitor the Temperature and Memory use of all nvidia video cards in the system and store these values for the past 4hrs  
2. The first screen will show the current Temperature and Memory use. The update interval can be adjusted  
3. There will be a Maximum temperature (over the past 24hrs) and an average temperature (over the past hr)  
4. There will be tabs that allow review of prior temperature as line charts with temperature over time  
5. There will be tabs that allow review of prior power use as line charts with power use over time  
6. Every function must have unit tests

ultrathink. Think hard and create a detailed, step-by-step implementation plan for nmon. Include: file paths to create/modify, function signatures, data structures, error handling approach, and testing strategy. For each step, specify the exact file, the functions/classes involved, their parameters and return types, and the logic in pseudocode. Do not write any code yet. Lets start with a planning phase and write the plan in nmonArchitecture.md.  
"

**Claude Improvements**

Identified inconsistencies and gaps in monitoring app requirements

Here's my review and an improved version of your prompt. I'll call out the issues first, then give you the refined prompt.

**Issues with the current prompt:**

1.  **Data retention contradiction** — Point 1 says "past 4hrs" but point 3 says "past 24hrs max temp." The storage window needs to cover at least 24hrs to support point 3.
2.  **Power use appears from nowhere** — Points 1-2 define temp + memory, but point 5 suddenly introduces power use without ever declaring it as a monitored metric.
3.  **No tech stack specified** — Is this a TUI (terminal), web app, desktop app? Devstral needs to know what to build.
4.  **No data persistence strategy** — In-memory? SQLite? Flat file? This is an architectural decision that shouldn't be left ambiguous.
5.  **"All nvidia video cards"** — But your Ollama server has one 3090. Are you running nmon locally on your workstation with a different GPU config? The target machine matters.
6.  **Aider context is incomplete** — No mention of language (Python?), working directory, or how aider connects to Ollama.
7.  **Update interval is vague** — "can be adjusted" — what's the default? What's the valid range?
8.  **Chart tab structure is vague** — What time windows? Per-GPU or aggregate?
9.  **The "ultrathink" directive and Claude/Ollama framing is muddled** — You're asking Claude to write a plan for Ollama to execute via aider, but the prompt reads like it's addressed to Claude directly. Pick one audience.

Here's the improved prompt:

* * *

Acknowledged request to refine GPU monitoring application specification

Key changes I made and why:

**Structural fixes**: Power draw is now declared upfront as a monitored metric alongside temp and memory, so it doesn't appear out of thin air in a tab. The retention window is unified to 24 hours everywhere.

**Tech stack is explicit**: Python + Rich TUI + SQLite + pynvml/nvidia-smi. Devstral won't have to guess — and guessing is where local models go off the rails.

**The table format for metrics** makes the sampling/storage contract unambiguous at a glance.

**Removed the toolchain narration**: The original prompt spent tokens explaining Ollama, aider, and Claude to the model. The model doesn't need to know *it's running on Ollama* — it needs a clear spec. I stripped that out so you can paste this directly into aider's `/architect` or `/ask` mode.

**Testing is prescriptive**: Instead of "every function must have unit tests" (which Devstral will interpret as "write `test_foo` that asserts True"), it now asks for specific test cases per module and a mocking strategy for the GPU layer.

**Added a memory history tab**: You had temp and power charts but no memory chart, despite memory being a core metric. Felt like an oversight.

One suggestion — if you're using aider with Devstral as the coding model, consider feeding this plan through Claude Code or Claude chat first to generate `nmonArchitecture.md`, then hand *that* to aider for implementation. Devstral Small is solid for code generation from a spec but weaker at multi-file architectural planning.