#!/usr/bin/env python3
"""
Parses aidercommands.md and runs aider --message for each step automatically.

The markdown file is expected to live alongside this script (e.g. in
``LocalLLMCoding/``). Aider itself is invoked from the current working
directory — so run this from the repo root you want aider to edit, e.g.::

    cd C:\\Coding\\nmonClaude
    python .\\LocalLLMCoding\\run_aider.py

Usage:
    python run_aider.py                    # run all steps
    python run_aider.py --from-step 5     # resume from step 5
    python run_aider.py --dry-run         # preview without running
    python run_aider.py --model gpt-4o    # override model for all steps
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_steps(md_path: str) -> list[dict]:
    content = Path(md_path).read_text(encoding="utf-8")

    # Find where each ## Step section begins
    step_re = re.compile(r'^## Step (\d+)', re.MULTILINE)
    matches = list(step_re.finditer(content))
    if not matches:
        sys.exit(f"No steps found in {md_path}")

    steps = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section = content[start:end]

        # Title from the header line
        title_match = re.match(r'## (Step \d+ — .+)', section)
        title = title_match.group(1).strip() if title_match else f"Step {m.group(1)}"

        # Extract all fenced code blocks: (language, body)
        blocks = re.findall(r'```(\w*)\n(.*?)```', section, re.DOTALL)

        bash_cmd = None
        prompt = None
        for lang, body in blocks:
            body = body.strip()
            if lang == 'bash' and bash_cmd is None:
                bash_cmd = body
            elif lang == '' and prompt is None:
                prompt = body

        if not bash_cmd or not prompt:
            print(f"  Warning: skipping unparseable section: {title}")
            continue

        steps.append({'number': int(m.group(1)), 'title': title,
                      'command': bash_cmd, 'prompt': prompt})

    return steps


def build_aider_cmd(step: dict, model: str | None) -> list[str]:
    # Parse the bash command line from the markdown, e.g.:
    #   aider --yes src/nmon/models.py src/nmon/config.py
    parts = step['command'].split()
    if parts[0] == 'aider':
        parts = parts[1:]           # drop 'aider', keep flags and file args

    cmd = ['aider', '--message', step['prompt']] + parts
    if model:
        cmd += ['--model', model]
    return cmd


def run_step(step: dict, model: str | None, dry_run: bool) -> bool:
    print(f"\n{'='*60}")
    print(f"  {step['title']}")
    print(f"{'='*60}")

    cmd = build_aider_cmd(step, model)

    # Show a readable preview (omit the long prompt body)
    preview = ' '.join(cmd[:cmd.index('--message')])
    print(f"  aider --message <prompt> {' '.join(cmd[cmd.index('--message')+2:])}")

    if dry_run:
        print(f"  [DRY RUN] prompt preview: {step['prompt'][:120].splitlines()[0]}...")
        return True

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n  [FAILED] exit code {result.returncode}")
        return False

    print(f"\n  [DONE] {step['title']}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run aider steps from aidercommands.md")
    parser.add_argument('file', nargs='?', default=None,
                        help="Markdown file to process (default: aidercommands.md next to this script)")
    parser.add_argument('--from-step', type=int, default=1, metavar='N',
                        help="Start from step N (useful for resuming after a failure)")
    parser.add_argument('--only-step', type=int, metavar='N',
                        help="Run only step N")
    parser.add_argument('--model', default=None,
                        help="Aider model override, e.g. gpt-4o or claude-3-5-sonnet")
    parser.add_argument('--dry-run', action='store_true',
                        help="Parse and preview steps without running aider")
    args = parser.parse_args()

    # Default markdown path is resolved relative to the script directory so
    # the script can be launched from any CWD (typically the repo root) and
    # still find its companion aidercommands.md.
    if args.file is None:
        md_path = SCRIPT_DIR / 'aidercommands.md'
    else:
        md_path = Path(args.file)
        if not md_path.is_absolute() and not md_path.exists():
            script_relative = SCRIPT_DIR / md_path
            if script_relative.exists():
                md_path = script_relative

    steps = parse_steps(str(md_path))
    print(f"Parsed {len(steps)} steps from {md_path}")

    if args.dry_run:
        for s in steps:
            print(f"\n  {s['title']}")
            print(f"    cmd:    {s['command']}")
            print(f"    prompt: {s['prompt'][:100].splitlines()[0]}...")
        return

    failed_at = None
    for step in steps:
        n = step['number']

        if args.only_step is not None and n != args.only_step:
            continue
        if n < args.from_step:
            print(f"  Skipping step {n} (--from-step {args.from_step})")
            continue

        ok = run_step(step, args.model, args.dry_run)
        if not ok:
            failed_at = n
            break

    if failed_at:
        print(f"\n[STOPPED] Failed at step {failed_at}.")
        print(
            f"  Fix the issue then resume with: "
            f"python {Path(sys.argv[0]).as_posix()} --from-step {failed_at}"
        )
        sys.exit(1)
    else:
        print(f"\n{'='*60}")
        print("  All steps completed.")
        print(f"{'='*60}")


if __name__ == '__main__':
    main()
