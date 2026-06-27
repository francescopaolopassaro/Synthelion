# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Command-line interface for Synthelion."""
from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    # Force UTF-8 I/O — needed on Windows (default cp1252 mangles non-ASCII).
    # utf-8-sig on stdin strips BOM written by PowerShell pipes.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8-sig")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="synthelion",
        description="Synthelion — Python port of Caveman. Token compressor for LLMs.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # compress
    p_cmp = sub.add_parser("compress", help="Compress text to reduce LLM tokens")
    p_cmp.add_argument("--text", "-t", help="Text to compress (or use stdin)")
    p_cmp.add_argument("--level", "-l", choices=["light", "semantic", "aggressive"], default="semantic")
    p_cmp.add_argument("--language", "-L", help="ISO 639-3 code (auto-detected if omitted)")
    p_cmp.add_argument("--json", action="store_true", help="Output as JSON")

    # detect
    p_det = sub.add_parser("detect", help="Detect language of text")
    p_det.add_argument("--text", "-t", help="Text to analyse (or use stdin)")
    p_det.add_argument("--scores", action="store_true", help="Show per-language scores")

    # route
    p_route = sub.add_parser("route", help="Content-aware routing and compression")
    p_route.add_argument("--text", "-t", help="Content to route (or use stdin)")
    p_route.add_argument("--file", "-f", help="Path to input file")
    p_route.add_argument("--profile", choices=["light", "balanced", "agent", "aggressive"], default="balanced")
    p_route.add_argument("--json", action="store_true")

    # summarize
    p_sum = sub.add_parser("summarize", help="Extractive summarization")
    p_sum.add_argument("--text", "-t", help="Text to summarize (or use stdin)")
    p_sum.add_argument("--sentences", "-n", type=int)
    p_sum.add_argument("--ratio", "-r", type=float)
    p_sum.add_argument("--algo", choices=["tfidf", "textrank"], default="textrank")

    # serve-mcp
    sub.add_parser("serve-mcp", help="Start MCP server on stdio")

    # doctor — check installation health
    p_doctor = sub.add_parser("doctor", help="Check Synthelion installation health")
    p_doctor.add_argument("--json", action="store_true", help="Output as JSON")

    # install — register MCP server in agent configs
    p_install = sub.add_parser("install", help="Register Synthelion MCP server in an AI agent config")
    p_install.add_argument("--agent", choices=["claude", "gemini"], default="claude", help="Agent to configure (default: claude)")
    p_install.add_argument("--local", action="store_true", help="Install in project-local config instead of global")

    # status — aggregate savings from the ledger
    p_status = sub.add_parser("status", help="Show aggregate token savings statistics")
    p_status.add_argument("--days", "-d", type=int, help="Restrict to last N days")
    p_status.add_argument("--json", action="store_true", help="Output as JSON")

    # gain — savings history
    p_gain = sub.add_parser("gain", help="Show token savings history")
    p_gain.add_argument("--days", "-d", type=int, default=30, help="Range in days (default: 30)")
    p_gain.add_argument("--all", action="store_true", help="Show all-time records")
    p_gain.add_argument("--json", action="store_true", help="Output as JSON")

    # bench — benchmark compression on sample corpus
    p_bench = sub.add_parser("bench", help="Benchmark compression on built-in sample corpus")
    p_bench.add_argument("--json", action="store_true", help="Output as JSON")
    p_bench.add_argument("--level", "-l", choices=["light", "semantic", "aggressive"], default="semantic")

    # upgrade — self-upgrade via pip
    p_upgrade = sub.add_parser("upgrade", help="Upgrade Synthelion to the latest version from PyPI")
    p_upgrade.add_argument("--dry-run", action="store_true", help="Show what would run without running it")

    # export — export savings ledger
    p_export = sub.add_parser("export", help="Export savings ledger to CSV or JSONL")
    p_export.add_argument("--format", "-F", choices=["csv", "jsonl"], default="csv", help="Output format (default: csv)")
    p_export.add_argument("--output", "-o", help="Output file path (stdout if omitted)")
    p_export.add_argument("--days", "-d", type=int, help="Restrict to last N days")

    args = parser.parse_args()

    if args.cmd == "compress":
        _cmd_compress(args)
    elif args.cmd == "detect":
        _cmd_detect(args)
    elif args.cmd == "route":
        _cmd_route(args)
    elif args.cmd == "summarize":
        _cmd_summarize(args)
    elif args.cmd == "serve-mcp":
        from synthelion.plugins.mcp_server import main as mcp_main
        mcp_main()
    elif args.cmd == "status":
        _cmd_status(args)
    elif args.cmd == "gain":
        _cmd_gain(args)
    elif args.cmd == "bench":
        _cmd_bench(args)
    elif args.cmd == "doctor":
        _cmd_doctor(args)
    elif args.cmd == "install":
        _cmd_install(args)
    elif args.cmd == "upgrade":
        _cmd_upgrade(args)
    elif args.cmd == "export":
        _cmd_export(args)


def _read_input(args) -> str:
    if hasattr(args, "file") and args.file:
        with open(args.file, encoding="utf-8") as f:
            return f.read()
    if args.text:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print("ERROR: provide --text, --file, or pipe input via stdin", file=sys.stderr)
    raise SystemExit(1)


def _cmd_compress(args) -> None:
    from synthelion.core import CompressionService
    from synthelion.models import CompressionLevel
    level_map = {"light": CompressionLevel.LIGHT, "semantic": CompressionLevel.SEMANTIC, "aggressive": CompressionLevel.AGGRESSIVE}
    text = _read_input(args)
    svc = CompressionService()
    r = svc.compress(text, level_map[args.level], iso3=args.language)
    if args.json:
        print(json.dumps({
            "compressed": r.compressed_text,
            "efficiency_pct": round(r.efficiency_pct, 2),
            "energy_mwh": round(r.estimated_energy_saved_mwh, 3),
            "co2_mg": round(r.estimated_co2_saved_mg, 3),
        }))
    else:
        print(r.compressed_text)
        print(f"\n[{r.efficiency_pct:.1f}% saved — {r.original_tokens} → {r.compressed_tokens} tokens]", file=sys.stderr)


def _cmd_detect(args) -> None:
    from synthelion.detector import LanguageDetector
    text = _read_input(args)
    det = LanguageDetector()
    if args.scores:
        scores = det.detect_with_scores(text)
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
        for iso3, score in top:
            print(f"{iso3}: {score:.3f}")
    else:
        print(det.detect(text))


def _cmd_route(args) -> None:
    from synthelion.content_router import ContentRouter
    from synthelion.models import CompressionProfile
    profile_map = {
        "light": CompressionProfile.LIGHT, "balanced": CompressionProfile.BALANCED,
        "agent": CompressionProfile.AGENT, "aggressive": CompressionProfile.AGGRESSIVE,
    }
    text = _read_input(args)
    router = ContentRouter.from_profile(profile_map[args.profile])
    r = router.route(text)
    if args.json:
        print(json.dumps({
            "compressed": r.compressed, "type": r.detected_type.value,
            "strategy": r.strategy_used, "savings_pct": round(r.savings_pct, 2),
        }))
    else:
        print(r.compressed)
        print(f"\n[{r.detected_type.value} → {r.strategy_used} — {r.savings_pct:.1f}% saved]", file=sys.stderr)


def _cmd_summarize(args) -> None:
    from synthelion.nlp.summarizer import TfIdfSummarizer
    from synthelion.nlp.text_rank import TextRankSummarizer
    text = _read_input(args)
    summ = TfIdfSummarizer() if args.algo == "tfidf" else TextRankSummarizer()
    print(summ.summarize(text, sentence_count=args.sentences, ratio=args.ratio))


def _cmd_status(args) -> None:
    from synthelion.analytics.ledger import get_ledger
    ledger = get_ledger()
    days = getattr(args, "days", None)
    records = ledger.records_since(int(days)) if days else ledger.all_records()
    s = ledger.summary(records)
    if getattr(args, "json", False):
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return
    label = f"last {days} days" if days else "all time"
    print(f"Synthelion savings — {label}")
    print(f"  Calls         : {s['total_calls']}")
    print(f"  Tokens before : {s['tokens_before']:,}")
    print(f"  Tokens after  : {s['tokens_after']:,}")
    print(f"  Tokens saved  : {s['tokens_saved']:,}")
    print(f"  Avg efficiency: {s['avg_efficiency_pct']:.1f}%")
    cost = s.get("cost_usd_saved", 0.0)
    if cost:
        print(f"  Cost saved    : ${cost:.4f}  ({s.get('pricing_note', '')})")
    if s["by_tool"]:
        print("  By tool:")
        for tool, saved in sorted(s["by_tool"].items(), key=lambda x: x[1], reverse=True):
            print(f"    {tool}: {saved:,} tokens saved")
    if s["by_content_type"]:
        print("  By content type:")
        for ct, saved in sorted(s["by_content_type"].items(), key=lambda x: x[1], reverse=True):
            print(f"    {ct}: {saved:,} tokens saved")


def _cmd_gain(args) -> None:
    from synthelion.analytics.ledger import get_ledger
    ledger = get_ledger()
    if getattr(args, "all", False):
        records = ledger.all_records()
        label = "all time"
    else:
        days = getattr(args, "days", 30)
        records = ledger.records_since(days)
        label = f"last {days} days"
    s = ledger.summary(records)
    if getattr(args, "json", False):
        print(json.dumps({"range": label, **s}, ensure_ascii=False, indent=2))
        return
    cost = s.get("cost_usd_saved", 0.0)
    cost_str = f" · ${cost:.4f} saved" if cost else ""
    print(f"Synthelion gain — {label}")
    print(f"  {s['total_calls']} calls · {s['tokens_saved']:,} tokens saved · {s['avg_efficiency_pct']:.1f}% avg efficiency{cost_str}")


def _cmd_bench(args) -> None:
    """Run compression on built-in sample corpus and report savings by content type."""
    from synthelion.content_router import ContentRouter
    from synthelion.models import CompressionProfile

    corpus = _bench_corpus()
    router = ContentRouter.from_profile(CompressionProfile.BALANCED)
    results = []
    for item in corpus:
        r = router.route(item["text"])
        saved_pct = r.savings_pct
        results.append({
            "label": item["label"],
            "content_type": r.detected_type.value,
            "tokens_before": r.tokens_before,
            "tokens_after": r.tokens_after,
            "savings_pct": round(saved_pct, 1),
        })

    if getattr(args, "json", False):
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    total_before = sum(r["tokens_before"] for r in results)
    total_after = sum(r["tokens_after"] for r in results)
    mean_pct = sum(r["savings_pct"] for r in results) / len(results) if results else 0

    print("Synthelion bench — built-in corpus")
    print(f"{'Label':<30} {'Type':<20} {'Before':>8} {'After':>8} {'Saved':>8}")
    print("-" * 80)
    for r in results:
        print(f"{r['label']:<30} {r['content_type']:<20} {r['tokens_before']:>8} {r['tokens_after']:>8} {r['savings_pct']:>7.1f}%")
    print("-" * 80)
    saved = total_before - total_after
    overall_pct = (saved / total_before * 100) if total_before else 0
    print(f"{'TOTAL':<30} {'':<20} {total_before:>8} {total_after:>8} {overall_pct:>7.1f}%")
    print(f"\nMean savings per sample: {mean_pct:.1f}%")


def _bench_corpus() -> list[dict]:
    return [
        {
            "label": "plain_text_eng",
            "text": (
                "The quick brown fox jumps over the lazy dog. "
                "This is a simple sentence that contains many common English words. "
                "The articles, prepositions, and conjunctions should be removed. "
                "We are testing the compression algorithm with this text."
            ),
        },
        {
            "label": "plain_text_ita",
            "text": (
                "Il gatto è seduto sul tappeto. "
                "La veloce volpe marrone salta sopra il cane pigro. "
                "Questo è un testo di prova per testare la compressione in italiano. "
                "Gli articoli e le preposizioni dovrebbero essere rimossi."
            ),
        },
        {
            "label": "json_array",
            "text": (
                '[{"id":1,"name":"Alice","age":30,"city":"Rome","active":true},'
                '{"id":2,"name":"Bob","age":25,"city":"Milan","active":false},'
                '{"id":3,"name":"Carol","age":35,"city":"Naples","active":true}]'
            ),
        },
        {
            "label": "git_diff",
            "text": (
                "diff --git a/foo.py b/foo.py\n"
                "index 1234567..abcdefg 100644\n"
                "--- a/foo.py\n"
                "+++ b/foo.py\n"
                "@@ -1,5 +1,5 @@\n"
                " def hello():\n"
                '-    print("hello world")\n'
                '+    print("hello synthelion")\n'
                " \n"
                " def bye():\n"
                '     print("bye")\n'
            ),
        },
        {
            "label": "code_python",
            "text": (
                "# This is a comment\n"
                "def fibonacci(n):\n"
                "    # Base cases\n"
                "    if n <= 1:\n"
                "        return n\n"
                "    # Recursive call\n"
                "    return fibonacci(n - 1) + fibonacci(n - 2)\n"
                "\n"
                "# Main entry point\n"
                "if __name__ == '__main__':\n"
                "    print(fibonacci(10))\n"
            ),
        },
        {
            "label": "log_stacktrace",
            "text": (
                "ERROR 2026-01-01 12:00:00 Exception in thread main\n"
                "java.lang.NullPointerException\n"
                "\tat com.example.App.main(App.java:10)\n"
                "ERROR 2026-01-01 12:00:01 Exception in thread main\n"
                "java.lang.NullPointerException\n"
                "\tat com.example.App.main(App.java:10)\n"
                "ERROR 2026-01-01 12:00:02 Exception in thread main\n"
                "java.lang.NullPointerException\n"
                "\tat com.example.App.main(App.java:10)\n"
                "INFO  2026-01-01 12:00:03 Application started\n"
            ),
        },
        {
            "label": "html_content",
            "text": (
                "<html><head><title>Test</title></head><body>"
                "<h1>Hello World</h1>"
                "<p>This is a paragraph with some <strong>bold</strong> text.</p>"
                "<ul><li>Item one</li><li>Item two</li><li>Item three</li></ul>"
                "</body></html>"
            ),
        },
    ]


def _cmd_doctor(args) -> None:
    """Health check: verify MCP package, ledger, session DB, and installation."""
    import shutil
    from pathlib import Path

    checks: list[dict] = []

    # 1. MCP package
    try:
        import mcp
        checks.append({"check": "mcp package", "status": "ok", "detail": getattr(mcp, "__version__", "installed")})
    except ImportError:
        checks.append({"check": "mcp package", "status": "error", "detail": "not installed — run: pip install mcp"})

    # 2. Synthelion version
    try:
        import synthelion
        checks.append({"check": "synthelion", "status": "ok", "detail": f"v{synthelion.__version__}"})
    except Exception as e:
        checks.append({"check": "synthelion", "status": "error", "detail": str(e)})

    # 3. Savings ledger
    try:
        from synthelion.analytics.ledger import get_ledger
        ledger = get_ledger()
        s = ledger.summary()
        checks.append({"check": "savings ledger", "status": "ok", "detail": f"{s['total_calls']} calls recorded"})
    except Exception as e:
        checks.append({"check": "savings ledger", "status": "error", "detail": str(e)})

    # 4. Session DB
    try:
        from synthelion.analytics.session_db import get_session_db
        db = get_session_db()
        checks.append({"check": "session db", "status": "ok", "detail": f"backend={db.backend()}"})
    except Exception as e:
        checks.append({"check": "session db", "status": "error", "detail": str(e)})

    # 5. synthelion-mcp in PATH
    mcp_cmd = shutil.which("synthelion-mcp")
    if mcp_cmd:
        checks.append({"check": "synthelion-mcp in PATH", "status": "ok", "detail": mcp_cmd})
    else:
        checks.append({"check": "synthelion-mcp in PATH", "status": "warn", "detail": "not found — run: pip install synthelion"})

    # 6. Claude Code global config
    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        try:
            import json as _json
            cfg = _json.loads(claude_json.read_text(encoding="utf-8"))
            if "synthelion" in cfg.get("mcpServers", {}):
                checks.append({"check": "claude code mcp", "status": "ok", "detail": str(claude_json)})
            else:
                checks.append({"check": "claude code mcp", "status": "warn", "detail": "synthelion not in ~/.claude.json — run: synthelion install"})
        except Exception:
            checks.append({"check": "claude code mcp", "status": "warn", "detail": "could not read ~/.claude.json"})
    else:
        checks.append({"check": "claude code mcp", "status": "warn", "detail": "~/.claude.json not found — run: synthelion install"})

    if getattr(args, "json", False):
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return

    has_error = any(c["status"] == "error" for c in checks)
    print("Synthelion doctor")
    for c in checks:
        icon = {"ok": "✓", "warn": "!", "error": "✗"}.get(c["status"], "?")
        print(f"  [{icon}] {c['check']}: {c['detail']}")
    if has_error:
        print("\nSome checks failed. Run with --json for structured output.")
        raise SystemExit(1)
    else:
        print("\nAll checks passed.")


def _cmd_install(args) -> None:
    """Register Synthelion MCP server in an AI agent config."""
    import json as _json
    import shutil
    from pathlib import Path

    agent = getattr(args, "agent", "claude")
    local = getattr(args, "local", False)

    mcp_cmd = shutil.which("synthelion-mcp") or "synthelion-mcp"
    mcp_entry = {"command": mcp_cmd, "args": []}

    if agent == "claude":
        if local:
            config_path = Path(".claude") / "settings.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            config_path = Path.home() / ".claude.json"

        # Read or create
        if config_path.exists():
            try:
                cfg = _json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
        else:
            cfg = {}

        cfg.setdefault("mcpServers", {})["synthelion"] = mcp_entry
        config_path.write_text(_json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✓ Synthelion MCP registered in {config_path}")
        print("  Restart Claude Code to activate.")

    elif agent == "gemini":
        if local:
            config_path = Path(".gemini") / "settings.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            config_path = Path.home() / ".gemini" / "settings.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)

        if config_path.exists():
            try:
                cfg = _json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
        else:
            cfg = {}

        cfg.setdefault("mcpServers", {})["synthelion"] = mcp_entry
        config_path.write_text(_json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✓ Synthelion MCP registered in {config_path}")
        print("  Restart Gemini CLI to activate.")

    else:
        print(f"ERROR: unsupported agent '{agent}'. Supported: claude, gemini", file=sys.stderr)
        raise SystemExit(1)


def _cmd_upgrade(args) -> None:
    """Upgrade Synthelion to the latest version via pip."""
    import subprocess
    if getattr(args, "dry_run", False):
        print("Would run: pip install --upgrade synthelion")
        return
    print("Upgrading Synthelion…")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "synthelion"],
    )
    if result.returncode == 0:
        import importlib
        import synthelion as _syn
        importlib.reload(_syn)
        print(f"\n[OK] Synthelion {_syn.__version__} installed.")
        print("Restart your agent or MCP server to activate the new version.")
    else:
        print("\n[X] Upgrade failed.", file=sys.stderr)
        raise SystemExit(result.returncode)


def _cmd_export(args) -> None:
    """Export savings ledger to CSV or JSONL."""
    import csv
    import io
    from synthelion.analytics.ledger import get_ledger
    ledger = get_ledger()
    days = getattr(args, "days", None)
    records = ledger.records_since(int(days)) if days else ledger.all_records()
    fmt = getattr(args, "format", "csv")
    output_path = getattr(args, "output", None)

    if not records:
        print("No records found.", file=sys.stderr)
        return

    if fmt == "jsonl":
        content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
    else:
        buf = io.StringIO()
        # Collect all unique keys across all records (different records may have different fields)
        all_keys: list[str] = []
        seen: set[str] = set()
        for rec in records:
            for k in rec:
                if k not in seen:
                    seen.add(k)
                    all_keys.append(k)
        writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        content = buf.getvalue()

    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"[OK] Exported {len(records)} records to {output_path}")
    else:
        sys.stdout.write(content)


if __name__ == "__main__":
    main()
