"""
generate_instructions.py — Simplified Figma JSON → LLM-ready sözel talimat.

Simplified JSON'un TAMAMINI okur, globalVars.styles'taki key'leri resolve eder,
her node'u pozisyon, boyut, renk, typography bilgileriyle birlikte
LLM'in doğrudan anlayıp kod yazabileceği formatta anlatır.

Kullanım:
    python generate_instructions.py simplified.json
    python generate_instructions.py simplified.json -o instructions.md
    
    # Veya raw JSON'dan direkt:
    python generate_instructions.py raw_figma.json --raw
"""

import argparse
import json
import sys
import os
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════
# Style Resolvers — globalVars.styles key'lerini çöz
# ══════════════════════════════════════════════════════════════════

def resolve_style(key: Optional[str], styles: dict) -> Any:
    """Style key'ini resolve et. Key yoksa veya styles'ta yoksa None dön."""
    if not key or not isinstance(key, str):
        return None
    return styles.get(key)


def describe_layout(layout: Optional[dict]) -> list[str]:
    """Layout dict'ini okunabilir satırlara çevir."""
    if not layout or not isinstance(layout, dict):
        return []
    
    lines = []
    mode = layout.get("mode", "none")
    
    if mode != "none":
        direction = "vertical stack (column)" if mode == "column" else "horizontal row"
        lines.append(f"Layout: {direction}")
    
    if layout.get("justifyContent"):
        lines.append(f"Main axis: {layout['justifyContent']}")
    if layout.get("alignItems"):
        lines.append(f"Cross axis: {layout['alignItems']}")
    if layout.get("gap"):
        lines.append(f"Gap: {layout['gap']}")
    if layout.get("padding"):
        lines.append(f"Padding: {layout['padding']}")
    if layout.get("wrap"):
        lines.append("Wrap: yes")
    if layout.get("overflowScroll"):
        lines.append(f"Scroll: {', '.join(layout['overflowScroll'])}")
    
    # Sizing
    sizing = layout.get("sizing", {})
    dims = layout.get("dimensions", {})
    
    h_sizing = sizing.get("horizontal")
    v_sizing = sizing.get("vertical")
    w_fixed = dims.get("width")
    h_fixed = dims.get("height")
    
    size_parts = []
    if h_sizing == "fill":
        size_parts.append("width: fill")
    elif h_sizing == "hug":
        size_parts.append("width: hug-content")
    elif w_fixed is not None:
        size_parts.append(f"width: {w_fixed}px")
    
    if v_sizing == "fill":
        size_parts.append("height: fill")
    elif v_sizing == "hug":
        size_parts.append("height: hug-content")
    elif h_fixed is not None:
        size_parts.append(f"height: {h_fixed}px")
    
    if size_parts:
        lines.append(f"Size: {', '.join(size_parts)}")
    
    # Absolute position
    if layout.get("position") == "absolute":
        loc = layout.get("locationRelativeToParent", {})
        x = loc.get("x", 0)
        y = loc.get("y", 0)
        lines.append(f"Position: absolute (x: {x}px, y: {y}px)")
    
    return lines


def describe_fills(fills_key: Optional[str], styles: dict) -> Optional[str]:
    """Fill style key'ini resolve edip okunabilir string döndür."""
    fills = resolve_style(fills_key, styles)
    if not fills:
        return None
    
    if isinstance(fills, list):
        parts = []
        for f in fills:
            if isinstance(f, str):
                parts.append(f)
            elif isinstance(f, dict):
                if f.get("type") == "IMAGE":
                    fit = f.get("objectFit") or f.get("backgroundSize", "?")
                    parts.append(f"image(fit: {fit})")
                elif f.get("gradient"):
                    parts.append(f.get("gradient"))
                else:
                    parts.append(str(f))
        return ", ".join(parts) if parts else None
    
    return str(fills)


def describe_strokes(strokes_key: Optional[str], styles: dict) -> Optional[str]:
    """Stroke style key'ini resolve et."""
    stroke = resolve_style(strokes_key, styles)
    if not stroke or not isinstance(stroke, dict):
        return None
    
    colors = stroke.get("colors", [])
    weight = stroke.get("strokeWeight", "")
    weights = stroke.get("strokeWeights", "")
    dashes = stroke.get("strokeDashes", "")
    
    color_str = ", ".join(str(c) for c in colors) if colors else ""
    
    parts = []
    if weight:
        parts.append(weight)
    elif weights:
        parts.append(weights)
    if color_str:
        parts.append(color_str)
    if dashes:
        parts.append(f"dashed({dashes})")
    
    return " ".join(parts) if parts else None


def describe_effects(effects_key: Optional[str], styles: dict) -> Optional[str]:
    """Effect style key'ini resolve et."""
    effect = resolve_style(effects_key, styles)
    if not effect or not isinstance(effect, dict):
        return None
    
    parts = []
    if effect.get("boxShadow"):
        parts.append(f"shadow: {effect['boxShadow']}")
    if effect.get("textShadow"):
        parts.append(f"text-shadow: {effect['textShadow']}")
    if effect.get("filter"):
        parts.append(effect["filter"])
    if effect.get("backdropFilter"):
        parts.append(f"backdrop: {effect['backdropFilter']}")
    
    return ", ".join(parts) if parts else None


def describe_text_style(ts_key: Optional[str], styles: dict) -> Optional[str]:
    """Text style key'ini resolve et."""
    ts = resolve_style(ts_key, styles)
    if not ts or not isinstance(ts, dict):
        return None
    
    parts = []
    if ts.get("fontFamily"):
        parts.append(ts["fontFamily"])
    if ts.get("fontWeight"):
        parts.append(f"weight {ts['fontWeight']}")
    if ts.get("fontSize"):
        parts.append(f"{ts['fontSize']}px")
    if ts.get("lineHeight"):
        parts.append(f"line-height {ts['lineHeight']}")
    if ts.get("letterSpacing"):
        parts.append(f"spacing {ts['letterSpacing']}")
    if ts.get("textAlignHorizontal"):
        parts.append(f"align-{ts['textAlignHorizontal'].lower()}")
    if ts.get("textCase"):
        parts.append(ts["textCase"].lower())
    
    return ", ".join(parts) if parts else None


# ══════════════════════════════════════════════════════════════════
# Node Descriptor — her node tipini sözel anlat
# ══════════════════════════════════════════════════════════════════

# Component catalog prefixes — bunlar senin bilinen component'lerin
CATALOG_PREFIXES = ("efa-", "cfa-", "wsp-")


def _is_catalog_component(name: str) -> bool:
    """efa-*/cfa-*/wsp-* ile başlayan ve noktalı OLMAYAN component mi?"""
    name_lower = name.lower()
    return any(name_lower.startswith(p) for p in CATALOG_PREFIXES) and not name.startswith(".")


def _is_dotted_internal(name: str) -> bool:
    """Noktalı internal component mi? (.efa-datatable/column, .select vs.)"""
    return name.startswith(".")


def describe_node(node: dict, styles: dict, indent: int = 0) -> list[str]:
    """
    Tek bir node'u ve tüm children'ını recursive olarak anlat.
    
    Noktalı component'ler (.efa-datatable/column, .select vs.) GÖRÜNMEZdir:
    - Kendileri yazılmaz
    - Ama içlerindeki catalog component'ler (efa-*, cfa-*, wsp-*) çıkarılır
    - Çıkarılan component'ler parent'ın indent seviyesinde gösterilir
    """
    name = node.get("name", "")
    node_type = node.get("type", "")
    
    # ── Noktalı internal → kendisini atla, children'dan catalog olanları kurtar ──
    if _is_dotted_internal(name):
        return _rescue_from_dotted(node, styles, indent)
    
    prefix = "  " * indent
    lines = []
    
    # ── Header line ──
    header = f"{prefix}- \"{name}\" ({node_type})"
    
    # Component props varsa header'a ekle
    comp_props = node.get("componentProperties", [])
    if comp_props:
        prop_parts = []
        for p in comp_props:
            pname = p.get("name", "")
            pval = p.get("value", "")
            ptype = p.get("type", "")
            if ptype == "BOOLEAN":
                prop_parts.append(f"{pname}={pval.lower()}")
            else:
                prop_parts.append(f'{pname}="{pval}"')
        header += f" [{', '.join(prop_parts)}]"
    
    # Text content varsa header'a ekle
    text = node.get("text", "")
    if text:
        display = text[:60]
        if len(text) > 60:
            display += "..."
        header += f" text=\"{display}\""
    
    lines.append(header)
    
    # ── Detail lines ──
    detail_prefix = prefix + "  "
    
    # Layout
    layout = resolve_style(node.get("layout"), styles)
    layout_lines = describe_layout(layout)
    for ll in layout_lines:
        lines.append(f"{detail_prefix}{ll}")
    
    # Fills (background/color)
    fills_desc = describe_fills(node.get("fills"), styles)
    if fills_desc:
        label = "Color" if node_type == "TEXT" else "Background"
        lines.append(f"{detail_prefix}{label}: {fills_desc}")
    
    # Strokes
    strokes_desc = describe_strokes(node.get("strokes"), styles)
    if strokes_desc:
        lines.append(f"{detail_prefix}Border: {strokes_desc}")
    
    # Effects
    effects_desc = describe_effects(node.get("effects"), styles)
    if effects_desc:
        lines.append(f"{detail_prefix}Effects: {effects_desc}")
    
    # Opacity
    if node.get("opacity") is not None:
        lines.append(f"{detail_prefix}Opacity: {node['opacity']}")
    
    # Border radius
    if node.get("borderRadius"):
        lines.append(f"{detail_prefix}Border radius: {node['borderRadius']}")
    
    # Text style
    ts_desc = describe_text_style(node.get("textStyle"), styles)
    if ts_desc:
        lines.append(f"{detail_prefix}Font: {ts_desc}")
    
    # ── Children (recursive) ──
    children = node.get("children", [])
    if children:
        for child in children:
            child_lines = describe_node(child, styles, indent + 1)
            lines.extend(child_lines)
    
    return lines


def _rescue_from_dotted(node: dict, styles: dict, indent: int) -> list[str]:
    """
    Noktalı internal component'in subtree'sini tara.
    Catalog component'leri (efa-*, cfa-*, wsp-*) ve TEXT node'ları çıkar.
    Non-catalog, non-dotted FRAME'leri de layout bilgisiyle birlikte çıkar.
    Diğer her şeyi atla.
    """
    lines = []
    children = node.get("children", [])
    
    for child in children:
        child_name = child.get("name", "")
        child_type = child.get("type", "")
        
        if _is_catalog_component(child_name):
            # Catalog component → tam describe
            child_lines = describe_node(child, styles, indent)
            lines.extend(child_lines)
        
        elif _is_dotted_internal(child_name):
            # İç içe noktalı → recursive rescue
            rescued = _rescue_from_dotted(child, styles, indent)
            lines.extend(rescued)
        
        elif child_type == "TEXT" and child.get("text"):
            # Text node → önemli olabilir (header text, label vs.)
            child_lines = describe_node(child, styles, indent)
            lines.extend(child_lines)
        
        elif child_type in ("FRAME", "GROUP"):
            # Normal frame → children'ına in, belki içinde catalog var
            rescued = _rescue_from_dotted(child, styles, indent)
            lines.extend(rescued)
        
        # Diğerleri (RECTANGLE, ELLIPSE vs.) → atla
    
    return lines


# ══════════════════════════════════════════════════════════════════
# Color & Typography Summary
# ══════════════════════════════════════════════════════════════════

def extract_color_palette(styles: dict) -> list[str]:
    """Tüm style'lardan unique renkleri çıkar."""
    colors = set()
    _walk_colors(styles, colors)
    return sorted(colors)


def _walk_colors(value: Any, colors: set):
    if isinstance(value, str):
        if value.startswith("#") or value.startswith("rgba("):
            colors.add(value)
    elif isinstance(value, list):
        for item in value:
            _walk_colors(item, colors)
    elif isinstance(value, dict):
        for v in value.values():
            _walk_colors(v, colors)


def extract_typography(styles: dict) -> list[dict]:
    """Tüm style'lardan unique typography tanımlarını çıkar."""
    seen = set()
    result = []
    for key, value in styles.items():
        if isinstance(value, dict) and "fontSize" in value:
            sig = json.dumps(value, sort_keys=True)
            if sig not in seen:
                seen.add(sig)
                result.append({"key": key, **value})
    return result


# ══════════════════════════════════════════════════════════════════
# Main Generator
# ══════════════════════════════════════════════════════════════════

def generate_instructions(simplified: dict) -> str:
    """
    Simplified JSON'dan LLM-ready talimat üret.
    Tüm node'ları, style'ları resolve ederek sözel olarak anlatır.
    """
    nodes = simplified.get("nodes", [])
    styles = simplified.get("globalVars", {}).get("styles", {})
    
    sections = []
    
    # ── 1. Page name ──
    page_name = simplified.get("name", "Design")
    sections.append(f"# Design: \"{page_name}\"\n")
    
    # ── 2. Color palette ──
    colors = extract_color_palette(styles)
    if colors:
        color_lines = ["## Color Palette"]
        for c in colors:
            color_lines.append(f"- {c}")
        sections.append("\n".join(color_lines))
    
    # ── 3. Typography ──
    typo = extract_typography(styles)
    if typo:
        typo_lines = ["## Typography"]
        for t in typo:
            parts = []
            if t.get("fontFamily"): parts.append(t["fontFamily"])
            if t.get("fontWeight"): parts.append(f"weight {t['fontWeight']}")
            if t.get("fontSize"): parts.append(f"{t['fontSize']}px")
            if t.get("lineHeight"): parts.append(f"line-height {t['lineHeight']}")
            if t.get("letterSpacing"): parts.append(f"spacing {t['letterSpacing']}")
            typo_lines.append(f"- {', '.join(parts)}")
        sections.append("\n".join(typo_lines))
    
    # ── 4. Full component tree ──
    sections.append("## Component Tree\n")
    
    for node in nodes:
        node_lines = describe_node(node, styles, indent=0)
        sections.append("\n".join(node_lines))
    
    return "\n\n".join(sections)


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Simplified Figma JSON → LLM-ready design instructions"
    )
    parser.add_argument("input", help="Simplified JSON (or raw JSON with --raw)")
    parser.add_argument("-o", "--output", default=None, help="Output .md file path")
    parser.add_argument("--raw", action="store_true", help="Input is raw Figma JSON, simplify first")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"File not found: {args.input}")
        sys.exit(1)
    
    # Load input
    print(f"Reading: {args.input}")
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Simplify if raw
    if args.raw:
        print("Simplifying raw JSON...")
        from figma_simplifier import simplify_figma_response
        data = simplify_figma_response(data)
    
    raw_json_size = len(json.dumps(data))
    
    # Generate instructions
    print("Generating instructions...")
    instructions = generate_instructions(data)
    
    instruction_size = len(instructions)
    est_tokens = instruction_size // 4
    raw_tokens = raw_json_size // 4
    
    # Stats
    print(f"\n{'=' * 55}")
    print(f"  Instruction Generation Results")
    print(f"{'=' * 55}")
    print(f"  Input JSON:          {raw_json_size:>10,} chars  (~{raw_tokens:,} tokens)")
    print(f"  Instructions:        {instruction_size:>10,} chars  (~{est_tokens:,} tokens)")
    print(f"  Reduction:           {round((1 - instruction_size / raw_json_size) * 100, 1) if raw_json_size > 0 else 0}%")
    print(f"{'=' * 55}\n")
    
    # Write output
    base_name = os.path.splitext(os.path.basename(args.input))[0]
    output_path = args.output or f"{base_name}_instructions.md"
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(instructions)
    
    print(f"Output: {output_path}")
    print(f"\nPreview (first 100 lines):")
    print("-" * 55)
    preview_lines = instructions.split("\n")
    for line in preview_lines[:100]:
        print(line)
    if len(preview_lines) > 100:
        print(f"\n... ({len(preview_lines) - 100} more lines)")


if __name__ == "__main__":
    main()