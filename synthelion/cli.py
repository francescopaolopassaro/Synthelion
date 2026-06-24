# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Command-line interface for Synthelion."""
from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    # Force UTF-8 output without BOM — needed on Windows where the default
    # console encoding (cp1252) would mangle non-ASCII compressed text.
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
        print(json.dumps({"compressed": r.compressed_text, "efficiency_pct": round(r.efficiency_pct, 2)}))
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


if __name__ == "__main__":
    main()
