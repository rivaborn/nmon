# run_aider.py — Usage Guide

Automates the nmon implementation by reading `aidercommands.md` and calling
aider once per step with the correct files and prompt.

## Prerequisites

- Python 3.10+
- Aider installed and on your PATH: `pip install aider-chat`
- Ollama installed and running: https://ollama.com/download

## Quick start

```bash
python run_aider.py --model ollama/qwen2.5-coder:32b
```

This runs all 25 steps in order. Each step calls:
```
aider --message "<prompt>" --yes --model ollama/qwen2.5-coder:32b <files>
```
Aider creates or edits the files, then exits. The script moves on to the next step.

## Choosing a local model

Pull a model with Ollama first, then pass it to the script.

### Best choice — Qwen2.5-Coder 32B (~20 GB VRAM)
Top-ranked local coding model. Handles each step reliably.
```bash
ollama pull qwen2.5-coder:32b
python run_aider.py --model ollama/qwen2.5-coder:32b
```

### If VRAM is limited — Qwen2.5-Coder 14B (~9 GB VRAM)
Good quality, fits on a single mid-range GPU.
```bash
ollama pull qwen2.5-coder:14b
python run_aider.py --model ollama/qwen2.5-coder:14b
```

### Smaller fallback — Qwen2.5-Coder 7B (~5 GB VRAM)
May struggle on the larger TUI steps. Use `--only-step` to retry those with a
bigger model if needed.
```bash
ollama pull qwen2.5-coder:7b
python run_aider.py --model ollama/qwen2.5-coder:7b
```

### Alternative — DeepSeek-Coder-V2 16B (~10 GB VRAM)
Strong on multi-file reasoning.
```bash
ollama pull deepseek-coder-v2:16b
python run_aider.py --model ollama/deepseek-coder-v2:16b
```

### Check available VRAM before choosing
```bash
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
```

## Resuming after a failure

If a step fails the script stops and prints a resume command:

```
[STOPPED] Failed at step 8.
  Fix the issue then resume with: python run_aider.py --from-step 8
```

Run the suggested command to pick up where it left off:

```bash
python run_aider.py --from-step 8 --model ollama/qwen2.5-coder:32b
```

## Re-running a single step

To rerun just one step without affecting the others:

```bash
python run_aider.py --only-step 12 --model ollama/qwen2.5-coder:32b
```

Useful when a generated file has a bug and you want aider to rewrite it.

## Previewing steps without running

Check what the script will do before committing:

```bash
python run_aider.py --dry-run
```

Prints each step's title, aider command, and first line of the prompt. No files
are created or modified.

## Using a different instruction file

The first positional argument is the markdown file to read. Defaults to
`aidercommands.md`:

```bash
python run_aider.py my_other_commands.md --model ollama/qwen2.5-coder:32b
```

## All options

| Flag | Description |
|------|-------------|
| `file` | Markdown file to read (default: `aidercommands.md`) |
| `--from-step N` | Skip steps before N and start at N |
| `--only-step N` | Run exactly one step |
| `--model MODEL` | Aider model string, e.g. `ollama/qwen2.5-coder:32b` |
| `--dry-run` | Preview steps without calling aider |

## How it works

`aidercommands.md` is structured with one `## Step N` section per file.
Each section contains:

1. A `bash` code block — the aider command listing which files to include
2. A plain code block — the prompt describing what to implement

The script parses these two blocks per step and calls:
```
aider --message "<prompt>" --yes <files> --model <model>
```

The `--message` flag makes aider non-interactive: it processes the prompt,
writes the files, and exits automatically.

## Troubleshooting

**Ollama not responding** — Make sure the Ollama service is running:
```bash
ollama serve
```

**Token limit / context window errors** — The model is too small for that step.
Switch to a larger variant (`14b` → `32b`) or rerun just the failing step with
the bigger model:
```bash
python run_aider.py --only-step N --model ollama/qwen2.5-coder:32b
```

**Out of VRAM** — The model is too large. Switch to the next size down, or
close other GPU-heavy applications first.

**Aider not found** — Run `pip install aider-chat` and ensure your shell can
find it (`aider --version` should print a version number).

**A generated file has import errors** — Run `--only-step N` to regenerate it.
If the error persists, edit `aidercommands.md` to clarify the prompt for that
step and rerun.

**Step succeeds but the code is wrong** — Run `pytest tests/ -v` after all
steps complete. Fix failures by running `--only-step N` on the relevant source
or test file.
