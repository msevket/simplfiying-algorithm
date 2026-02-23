"""
test_simplifier.py — Raw Figma JSON'u lokalde simplify et.

Kullanım:
    python test_simplifier.py raw_figma.json
    python test_simplifier.py raw_figma.json -o output.json
"""

import argparse
import json
import sys
import os

from figma_simplifier import simplify_figma_response, ALL_EXTRACTORS


def load_raw_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def count_nodes(nodes: list) -> int:
    total = 0
    for node in nodes:
        total += 1
        if "children" in node:
            total += count_nodes(node["children"])
    return total


def print_stats(raw: dict, simplified: dict):
    raw_size = len(json.dumps(raw))
    simplified_size = len(json.dumps(simplified, indent=2))
    reduction = round((1 - simplified_size / raw_size) * 100, 1) if raw_size > 0 else 0

    node_count = count_nodes(simplified.get("nodes", []))
    style_count = len(simplified.get("globalVars", {}).get("styles", {}))
    component_count = len(simplified.get("components", {}))

    print(f"\n{'=' * 50}")
    print(f"  Simplification Results")
    print(f"{'=' * 50}")
    print(f"  Raw JSON size:          {raw_size:,} chars")
    print(f"  Simplified size:        {simplified_size:,} chars")
    print(f"  Reduction:              {reduction}%")
    print(f"  Node count:             {node_count}")
    print(f"  Deduplicated styles:    {style_count}")
    print(f"  Components:             {component_count}")
    print(f"{'=' * 50}\n")


def main():
    parser = argparse.ArgumentParser(description="Raw Figma JSON -> Simplified JSON (local test)")

    parser.add_argument("input", help="Raw Figma API JSON file path")
    parser.add_argument("-o", "--output", default=None, help="Output file path (default: <input>_simplified.json)")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"File not found: {args.input}")
        sys.exit(1)

    print(f"Reading: {args.input}")
    raw = load_raw_json(args.input)

    print("Simplifying...")
    simplified = simplify_figma_response(
        raw,
        extractors=ALL_EXTRACTORS,
        max_depth=None,
    )

    print_stats(raw, simplified)

    base_name = os.path.splitext(os.path.basename(args.input))[0]
    output_path = args.output or f"{base_name}_simplified.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(simplified, f, indent=2)

    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()