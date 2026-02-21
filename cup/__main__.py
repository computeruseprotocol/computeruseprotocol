"""CLI for CUP tree capture: python -m cup"""

from __future__ import annotations

import argparse
import json
import os
import time

from cup._router import get_adapter, detect_platform
from cup.format import build_envelope, serialize_compact, prune_tree


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CUP: Capture accessibility tree in Computer Use Protocol format")
    parser.add_argument("--depth", type=int, default=0,
                        help="Max tree depth (0 = unlimited)")
    parser.add_argument("--foreground", action="store_true",
                        help="Only capture the foreground/focused window")
    parser.add_argument("--app", type=str, default=None,
                        help="Filter to window/app title containing this string")
    parser.add_argument("--json-out", type=str, default=None,
                        help="Write pruned CUP JSON to file")
    parser.add_argument("--full-json-out", type=str, default=None,
                        help="Write full (unpruned) CUP JSON to file")
    parser.add_argument("--compact-out", type=str, default=None,
                        help="Write compact LLM text to file")
    parser.add_argument("--compact", action="store_true",
                        help="Print compact text to stdout")
    parser.add_argument("--platform", type=str, default=None,
                        choices=["windows", "macos", "web"],
                        help="Force platform (default: auto-detect)")
    parser.add_argument("--cdp-port", type=int, default=None,
                        help="CDP port for web platform (default: 9222)")
    parser.add_argument("--cdp-host", type=str, default=None,
                        help="CDP host for web platform (default: localhost)")
    args = parser.parse_args()

    max_depth = args.depth if args.depth > 0 else 999
    platform = args.platform or detect_platform()

    # Pass CDP connection args via env vars for the web adapter
    if platform == "web":
        if args.cdp_port:
            os.environ["CUP_CDP_PORT"] = str(args.cdp_port)
        if args.cdp_host:
            os.environ["CUP_CDP_HOST"] = args.cdp_host

    print(f"=== CUP Tree Capture ({platform}) ===")

    adapter = get_adapter(platform)
    sw, sh, scale = adapter.get_screen_info()
    scale_str = f" @{scale}x" if scale != 1.0 else ""
    print(f"Screen: {sw}x{sh}{scale_str}")

    # -- Window enumeration --
    t0 = time.perf_counter()
    if args.foreground:
        windows = [adapter.get_foreground_window()]
        print(f"Target: foreground (\"{windows[0]['title']}\")")
    else:
        windows = adapter.get_all_windows()
        if args.app:
            windows = [w for w in windows
                       if args.app.lower() in w["title"].lower()]
            if not windows:
                print(f"No window found matching '{args.app}'")
                return
        print(f"Target: {len(windows)} window(s)")
    t_enum = (time.perf_counter() - t0) * 1000

    # -- Tree capture --
    t0 = time.perf_counter()
    tree, stats = adapter.capture_tree(windows, max_depth=max_depth)
    t_walk = (time.perf_counter() - t0) * 1000

    print(f"Captured {stats['nodes']} nodes in {t_walk:.1f} ms (enum: {t_enum:.1f} ms)")
    print(f"Max depth: {stats['max_depth']}")

    # -- Envelope --
    app_name = windows[0]["title"] if len(windows) == 1 else None
    app_pid = windows[0]["pid"] if len(windows) == 1 else None
    app_bundle_id = windows[0].get("bundle_id") if len(windows) == 1 else None

    # Collect WebMCP tools when available (web platform)
    tools = None
    if hasattr(adapter, "get_last_tools"):
        tools = adapter.get_last_tools() or None

    envelope = build_envelope(
        tree, platform=platform,
        screen_w=sw, screen_h=sh, screen_scale=scale,
        app_name=app_name, app_pid=app_pid, app_bundle_id=app_bundle_id,
        tools=tools,
    )

    json_str = json.dumps(envelope, ensure_ascii=False)
    json_kb = len(json_str) / 1024
    print(f"JSON size: {json_kb:.1f} KB")

    # -- Role distribution --
    print(f"\nRole distribution (top 15):")
    for role, count in sorted(stats["roles"].items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {role:45s} {count:6d}")

    # -- WebMCP tools --
    if tools:
        print(f"\nWebMCP tools ({len(tools)}):")
        for tool in tools:
            desc = tool.get("description", "")
            desc_str = f" - {desc}" if desc else ""
            print(f"  {tool['name']}{desc_str}")

    # -- Output options --
    if args.json_out:
        pruned_tree = prune_tree(envelope["tree"])
        pruned_envelope = {**envelope, "tree": pruned_tree}
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(pruned_envelope, f, indent=2, ensure_ascii=False)
        pruned_kb = len(json.dumps(pruned_envelope, ensure_ascii=False)) / 1024
        print(f"\nPruned JSON written to {args.json_out} ({pruned_kb:.1f} KB)")

    if args.full_json_out:
        with open(args.full_json_out, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, ensure_ascii=False)
        print(f"Full JSON written to {args.full_json_out} ({json_kb:.1f} KB)")

    if args.compact_out or args.compact:
        compact_str = serialize_compact(envelope)
        compact_kb = len(compact_str) / 1024
        if args.compact:
            print(f"\n{compact_str}")
        if args.compact_out:
            with open(args.compact_out, "w", encoding="utf-8") as f:
                f.write(compact_str)
            ratio = (1 - compact_kb / json_kb) * 100 if json_kb > 0 else 0
            print(f"Compact written to {args.compact_out} ({compact_kb:.1f} KB, {ratio:.0f}% smaller)")


if __name__ == "__main__":
    main()
