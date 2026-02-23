"""
test_simplifier.py — Raw Figma JSON'u lokalde simplify et.

Kullanım:
    python test_simplifier.py raw_figma.json                     # → simplified.yaml
    python test_simplifier.py raw_figma.json -o output.yaml      # → custom output path
    python test_simplifier.py raw_figma.json -f json              # → JSON formatında
    python test_simplifier.py raw_figma.json -f both              # → hem YAML hem JSON
"""

import argparse
import json
import sys
import os

# yaml opsiyonel — yoksa sadece json çıktı verir
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ─── figma_simplifier.py'den import ───
# Aynı dizinde figma_simplifier.py olduğunu varsayıyoruz.
# Eğer farklı bir path'teyse sys.path'e ekle.
from figma_simplifier import simplify_figma_response, ALL_EXTRACTORS


def load_raw_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_output(data: dict, output_path: str, fmt: str):
    if fmt == "yaml":
        if not HAS_YAML:
            print("⚠ PyYAML yüklü değil, JSON olarak yazılıyor.")
            fmt = "json"

    if fmt == "yaml":
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    else:
        content = json.dumps(data, indent=2, ensure_ascii=False)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def print_stats(raw: dict, simplified: dict):
    raw_size = len(json.dumps(raw))
    simplified_size = len(json.dumps(simplified))
    reduction = round((1 - simplified_size / raw_size) * 100, 1) if raw_size > 0 else 0

    node_count = count_nodes(simplified.get("nodes", []))
    style_count = len(simplified.get("globalVars", {}).get("styles", {}))
    component_count = len(simplified.get("components", {}))

    print(f"\n{'═' * 50}")
    print(f"  📊 Simplification Sonuçları")
    print(f"{'═' * 50}")
    print(f"  Raw JSON boyutu:        {raw_size:,} chars")
    print(f"  Simplified boyutu:      {simplified_size:,} chars")
    print(f"  Azalma:                 {reduction}%")
    print(f"  Node sayısı:            {node_count}")
    print(f"  Deduplicated styles:    {style_count}")
    print(f"  Components:             {component_count}")
    print(f"{'═' * 50}\n")


def count_nodes(nodes: list) -> int:
    total = 0
    for node in nodes:
        total += 1
        if "children" in node:
            total += count_nodes(node["children"])
    return total


def main():
    parser = argparse.ArgumentParser(
        description="Raw Figma JSON → Simplified output (local test)"
    )
    parser.add_argument(
        "input",
        help="Raw Figma API JSON dosyasının path'i"
    )
    parser.add_argument(
        "-o", "--output",
        help="Çıktı dosya path'i (default: simplified.yaml veya .json)",
        default=None
    )
    parser.add_argument(
        "-f", "--format",
        choices=["yaml", "json", "both"],
        default="yaml",
        help="Çıktı formatı (default: yaml)"
    )

    args = parser.parse_args()

    # 1. Raw JSON'u oku
    if not os.path.exists(args.input):
        print(f"❌ Dosya bulunamadı: {args.input}")
        sys.exit(1)

    print(f"📂 Okunuyor: {args.input}")
    raw = load_raw_json(args.input)

    # 2. Simplify et
    print("⚙️  Simplifying...")
    simplified = simplify_figma_response(
        raw,
        extractors=ALL_EXTRACTORS,
        max_depth=None,  # Tüm depth'lere in
    )

    # 3. Stats göster
    print_stats(raw, simplified)

    # 4. Çıktıyı yaz
    base_name = os.path.splitext(os.path.basename(args.input))[0]

    if args.format == "both":
        yaml_path = args.output or f"{base_name}_simplified.yaml"
        json_path = os.path.splitext(yaml_path)[0] + ".json"
        write_output(simplified, yaml_path, "yaml")
        write_output(simplified, json_path, "json")
        print(f"✅ YAML → {yaml_path}")
        print(f"✅ JSON → {json_path}")
    else:
        ext = ".yaml" if args.format == "yaml" else ".json"
        output_path = args.output or f"{base_name}_simplified{ext}"
        write_output(simplified, output_path, args.format)
        print(f"✅ Çıktı → {output_path}")


if __name__ == "__main__":
    main()