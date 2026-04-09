import argparse
import sys
from rich.console import Console
from nmon.config import load_config, ConfigError
from nmon.gpu.nvml_source import NvmlSource
from nmon.gpu.smi_source import SmiSource
from nmon.storage import Storage
from nmon.collector import Collector
from nmon.tui.app import NmonApp

console = Console()

def _pick_source():
    nvml = NvmlSource()
    if nvml.is_available():
        console.print("[green]Using pynvml[/green]")
        return nvml
    smi = SmiSource()
    if smi.is_available():
        console.print("[yellow]pynvml unavailable, using nvidia-smi[/yellow]")
        return smi
    return None

def main() -> None:
    parser = argparse.ArgumentParser(description="nmon — Nvidia GPU Monitor")
    parser.add_argument("--config", default=None, help="Path to config.toml")
    parser.add_argument("--interval", type=int, default=None)
    parser.add_argument("--db", default=None, help="Path to SQLite database")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        sys.exit(1)

    if args.interval is not None:
        config.interval_seconds = args.interval
    if args.db is not None:
        config.db_path = args.db

    source = _pick_source()
    if source is None:
        console.print("[red]No Nvidia GPU source available. "
                      "Install pynvml or ensure nvidia-smi is on PATH.[/red]")
        sys.exit(1)

    storage = Storage(config.db_path)
    collector = Collector(source, storage, config)
    app = NmonApp(collector, storage, config)
    try:
        app.run()
    finally:
        collector.stop()
        storage.close()
        source.close()

if __name__ == "__main__":
    main()
