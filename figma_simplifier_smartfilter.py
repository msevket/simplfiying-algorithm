"""
figma_simplifier.py — Figma-Context-MCP v0.6.4 Extractor Pattern, Python port
Smart filter (efa-*/cfa-*/wsp-* component handling) ve design rules entegre.
"""
import json
import string
import random
from typing import Any, Callable, Optional


# ══════════════════════════════════════════════════════════════════
# Types
# ══════════════════════════════════════════════════════════════════

SimplifiedNode = dict[str, Any]
GlobalVars = dict[str, dict[str, Any]]
TraversalContext = dict[str, Any]
ExtractorFn = Callable[[dict, SimplifiedNode, TraversalContext], None]


# ══════════════════════════════════════════════════════════════════
# Utility Functions
# ══════════════════════════════════════════════════════════════════

VECTOR_TYPES = frozenset({
    "IMAGE-SVG", "VECTOR", "STAR", "LINE",
    "ELLIPSE", "REGULAR_POLYGON", "RECTANGLE"
})

DEFAULT_COMPONENT_PREFIXES = ("efa-", "cfa-", "wsp-")


def _matches_component_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    """Check if node name matches any component prefix (case-insensitive)."""
    name_lower = name.lower()
    return any(name_lower.startswith(p) for p in prefixes)


def _matches_dotted_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    """Check if node name matches any dotted (internal) component prefix."""
    name_lower = name.lower()
    return any(name_lower.startswith(f".{p}") for p in prefixes)


def is_visible(node: dict) -> bool:
    return node.get("visible", True)


def round_num(n: float) -> float:
    if n != n:
        raise TypeError("Input must be a valid number")
    return round(n, 2)


def format_padding(top: float, right: float, bottom: float, left: float) -> Optional[str]:
    if top == 0 and right == 0 and bottom == 0 and left == 0:
        return None
    if all(v == top for v in [top, right, bottom, left]):
        return f"{top}px"
    if left == right and top == bottom:
        return f"{top}px {right}px"
    if left == right:
        return f"{top}px {right}px {bottom}px"
    return f"{top}px {right}px {bottom}px {left}px"


def clean_empty(obj: Any) -> Any:
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            result = clean_empty(v)
            if result is not None and result != [] and result != {}:
                cleaned[k] = result
        return cleaned if cleaned else None
    if isinstance(obj, list):
        cleaned = [clean_empty(item) for item in obj]
        return [item for item in cleaned if item is not None]
    return obj


def generate_var_key(prefix: str = "var") -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=6))
    return f"{prefix}_{suffix}"


def rgba_to_css(color: dict, extra_opacity: float = 1.0) -> str:
    r = round(color.get("r", 0) * 255)
    g = round(color.get("g", 0) * 255)
    b = round(color.get("b", 0) * 255)
    a = round(color.get("a", 1) * extra_opacity, 2)
    if a >= 1:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"rgba({r}, {g}, {b}, {a})"


def get_or_create_style_key(global_vars: dict, style_value: Any, prefix: str = "var") -> str:
    serialized = json.dumps(style_value, sort_keys=True)
    for key, existing in global_vars["styles"].items():
        if json.dumps(existing, sort_keys=True) == serialized:
            return key
    new_key = generate_var_key(prefix)
    global_vars["styles"][new_key] = style_value
    return new_key


def resolve_named_style(node: dict, context: TraversalContext, style_keys: list[str]) -> Optional[str]:
    node_styles = node.get("styles")
    if not isinstance(node_styles, dict):
        return None
    extra_styles = context["globalVars"].get("extraStyles", {})
    for key in style_keys:
        style_id = node_styles.get(key)
        if style_id and style_id in extra_styles:
            name = extra_styles[style_id].get("name")
            if name:
                return name
    return None


# ══════════════════════════════════════════════════════════════════
# Layout Extractor
# ══════════════════════════════════════════════════════════════════

def _map_primary_align(value: str, children: list = None, axis: str = None, mode: str = None) -> Optional[str]:
    mapping = {
        "MIN": None,
        "CENTER": "center",
        "MAX": "flex-end",
        "SPACE_BETWEEN": "space-between",
        "BASELINE": "baseline",
    }
    if children and mode and mode != "none":
        direction = "horizontal" if (axis == "primary" and mode == "row") or (axis == "counter" and mode == "column") else "vertical"
        all_fill = all(
            c.get("layoutPositioning") == "ABSOLUTE" or
            (c.get("layoutSizingHorizontal") == "FILL" if direction == "horizontal" else c.get("layoutSizingVertical") == "FILL")
            for c in children if isinstance(c, dict)
        )
        if all_fill and children:
            return "stretch"
    return mapping.get(value)


def _map_counter_align(value: str) -> Optional[str]:
    return {"MIN": None, "CENTER": "center", "MAX": "flex-end", "STRETCH": "stretch"}.get(value)


def _map_sizing(value: Optional[str]) -> Optional[str]:
    return {"FIXED": "fixed", "FILL": "fill", "HUG": "hug"}.get(value)


def _extract_layout_props(node: dict) -> dict:
    layout_mode_raw = node.get("layoutMode")
    if not layout_mode_raw or layout_mode_raw == "NONE":
        mode = "none"
    elif layout_mode_raw == "HORIZONTAL":
        mode = "row"
    else:
        mode = "column"

    result = {"mode": mode}

    overflow = node.get("overflowDirection", "")
    scroll = []
    if "HORIZONTAL" in overflow:
        scroll.append("x")
    if "VERTICAL" in overflow:
        scroll.append("y")
    if scroll:
        result["overflowScroll"] = scroll

    if mode == "none":
        return result

    children = node.get("children", [])
    result["justifyContent"] = _map_primary_align(
        node.get("primaryAxisAlignItems", "MIN"), children, "primary", mode
    )
    result["alignItems"] = _map_primary_align(
        node.get("counterAxisAlignItems", "MIN"), children, "counter", mode
    )
    result["alignSelf"] = _map_counter_align(node.get("layoutAlign", "MIN"))

    if node.get("layoutWrap") == "WRAP":
        result["wrap"] = True

    spacing = node.get("itemSpacing")
    if spacing:
        result["gap"] = f"{spacing}px"

    padding = format_padding(
        node.get("paddingTop", 0), node.get("paddingRight", 0),
        node.get("paddingBottom", 0), node.get("paddingLeft", 0),
    )
    if padding:
        result["padding"] = padding

    return result


def _extract_dimensions(node: dict, parent: Optional[dict], mode: str) -> dict:
    result = {"mode": mode}
    result["sizing"] = {
        "horizontal": _map_sizing(node.get("layoutSizingHorizontal")),
        "vertical": _map_sizing(node.get("layoutSizingVertical")),
    }

    if node.get("layoutPositioning") == "ABSOLUTE":
        result["position"] = "absolute"

    bbox = node.get("absoluteBoundingBox", {})
    parent_bbox = (parent or {}).get("absoluteBoundingBox", {})

    if result.get("position") == "absolute" and bbox and parent_bbox:
        result["locationRelativeToParent"] = {
            "x": round_num(bbox.get("x", 0) - parent_bbox.get("x", 0)),
            "y": round_num(bbox.get("y", 0) - parent_bbox.get("y", 0)),
        }

    if bbox:
        dims = {}
        w = bbox.get("width")
        h = bbox.get("height")
        h_sizing = node.get("layoutSizingHorizontal")
        v_sizing = node.get("layoutSizingVertical")
        grow = node.get("layoutGrow")
        stretch = node.get("layoutAlign") == "STRETCH"

        if mode == "row":
            if not grow and h_sizing == "FIXED":
                dims["width"] = round_num(w)
            if not stretch and v_sizing == "FIXED":
                dims["height"] = round_num(h)
        elif mode == "column":
            if not stretch and h_sizing == "FIXED":
                dims["width"] = round_num(w)
            if not grow and v_sizing == "FIXED":
                dims["height"] = round_num(h)
        else:
            if not h_sizing or h_sizing == "FIXED":
                dims["width"] = round_num(w) if w else None
            if not v_sizing or v_sizing == "FIXED":
                dims["height"] = round_num(h) if h else None

        if dims:
            result["dimensions"] = dims

    return result


def layout_extractor(node: dict, result: SimplifiedNode, context: TraversalContext):
    layout_props = _extract_layout_props(node)
    dim_props = _extract_dimensions(
        node, context.get("parent"), layout_props.get("mode", "none")
    )
    merged = {**layout_props, **dim_props}

    if len(merged) <= 1 and merged.get("mode") == "none":
        return

    key = get_or_create_style_key(context["globalVars"], merged, "layout")
    result["layout"] = key


# ══════════════════════════════════════════════════════════════════
# Text Extractor
# ══════════════════════════════════════════════════════════════════

def _extract_text_style(node: dict) -> Optional[dict]:
    style = node.get("style", {})
    if not style:
        return None
    result = {}
    if style.get("fontFamily"):
        result["fontFamily"] = style["fontFamily"]
    if style.get("fontWeight"):
        result["fontWeight"] = style["fontWeight"]
    if style.get("fontSize"):
        result["fontSize"] = style["fontSize"]
        lh = style.get("lineHeightPx")
        if lh and style["fontSize"]:
            result["lineHeight"] = f"{round(lh / style['fontSize'], 2)}em"
        ls = style.get("letterSpacing")
        if ls and ls != 0 and style["fontSize"]:
            result["letterSpacing"] = f"{round(ls / style['fontSize'] * 100, 1)}%"
    for k in ("textCase", "textAlignHorizontal", "textAlignVertical"):
        if style.get(k):
            result[k] = style[k]
    return result if result else None


def text_extractor(node: dict, result: SimplifiedNode, context: TraversalContext):
    if node.get("type") == "TEXT":
        chars = node.get("characters")
        if chars:
            result["text"] = chars

    style = _extract_text_style(node)
    if style:
        named = resolve_named_style(node, context, ["text", "typography"])
        if named:
            context["globalVars"]["styles"][named] = style
            result["textStyle"] = named
        else:
            result["textStyle"] = get_or_create_style_key(
                context["globalVars"], style, "style"
            )


# ══════════════════════════════════════════════════════════════════
# Visuals Extractor
# ══════════════════════════════════════════════════════════════════

def _process_fill(fill: dict, has_children: bool = False) -> Optional[Any]:
    if not fill.get("visible", True):
        return None

    fill_type = fill.get("type")

    if fill_type == "SOLID":
        color = fill.get("color", {})
        return rgba_to_css(color, fill.get("opacity", 1))

    elif fill_type == "IMAGE":
        result = {
            "type": "IMAGE",
            "imageRef": fill.get("imageRef"),
            "scaleMode": fill.get("scaleMode", "FILL"),
        }
        scale_mode = fill.get("scaleMode", "FILL")
        if scale_mode == "FILL":
            if has_children:
                result.update({"backgroundSize": "cover", "backgroundRepeat": "no-repeat", "isBackground": True})
            else:
                result["objectFit"] = "cover"
        elif scale_mode == "FIT":
            if has_children:
                result.update({"backgroundSize": "contain", "backgroundRepeat": "no-repeat", "isBackground": True})
            else:
                result["objectFit"] = "contain"
        elif scale_mode == "TILE":
            result.update({"backgroundRepeat": "repeat", "isBackground": True})
        elif scale_mode == "STRETCH":
            if has_children:
                result.update({"backgroundSize": "100% 100%", "backgroundRepeat": "no-repeat", "isBackground": True})
            else:
                result["objectFit"] = "fill"

        transform = fill.get("imageTransform")
        if transform:
            result["imageDownloadArguments"] = {
                "needsCropping": True,
                "cropTransform": transform,
            }
        return result

    elif fill_type in ("GRADIENT_LINEAR", "GRADIENT_RADIAL", "GRADIENT_ANGULAR", "GRADIENT_DIAMOND"):
        stops = fill.get("gradientStops", [])
        stop_str = ", ".join(
            f"{rgba_to_css(s['color'])} {round(s['position'] * 100)}%"
            for s in sorted(stops, key=lambda x: x["position"])
        )
        prefix_map = {
            "GRADIENT_LINEAR": "linear-gradient",
            "GRADIENT_RADIAL": "radial-gradient",
            "GRADIENT_ANGULAR": "conic-gradient",
            "GRADIENT_DIAMOND": "radial-gradient",
        }
        return {"type": fill_type, "gradient": f"{prefix_map[fill_type]}({stop_str})"}

    return None


def _process_effects(node: dict) -> dict:
    effects = node.get("effects", [])
    if not effects:
        return {}

    visible = [e for e in effects if e.get("visible", True)]
    result = {}

    shadows = []
    for e in visible:
        if e["type"] == "DROP_SHADOW":
            c = rgba_to_css(e.get("color", {}))
            ox, oy = e.get("offset", {}).get("x", 0), e.get("offset", {}).get("y", 0)
            shadows.append(f"{ox}px {oy}px {e.get('radius', 0)}px {e.get('spread', 0)}px {c}")
        elif e["type"] == "INNER_SHADOW":
            c = rgba_to_css(e.get("color", {}))
            ox, oy = e.get("offset", {}).get("x", 0), e.get("offset", {}).get("y", 0)
            shadows.append(f"inset {ox}px {oy}px {e.get('radius', 0)}px {e.get('spread', 0)}px {c}")

    if shadows:
        key = "textShadow" if node.get("type") == "TEXT" else "boxShadow"
        result[key] = ", ".join(shadows)

    blur = [e for e in visible if e["type"] == "LAYER_BLUR"]
    if blur:
        result["filter"] = " ".join(f"blur({e.get('radius', 0)}px)" for e in blur)

    backdrop = [e for e in visible if e["type"] == "BACKGROUND_BLUR"]
    if backdrop:
        result["backdropFilter"] = " ".join(f"blur({e.get('radius', 0)}px)" for e in backdrop)

    return result


def visuals_extractor(node: dict, result: SimplifiedNode, context: TraversalContext):
    has_children = bool(node.get("children"))

    fills_raw = node.get("fills", [])
    if fills_raw:
        processed = [_process_fill(f, has_children) for f in fills_raw]
        processed = [f for f in processed if f is not None]
        processed.reverse()
        if processed:
            named = resolve_named_style(node, context, ["fill", "fills"])
            if named:
                context["globalVars"]["styles"][named] = processed
                result["fills"] = named
            else:
                result["fills"] = get_or_create_style_key(context["globalVars"], processed, "fill")

    strokes_raw = node.get("strokes", [])
    if strokes_raw:
        stroke_colors = [_process_fill(s, has_children) for s in strokes_raw if is_visible(s)]
        stroke_colors = [s for s in stroke_colors if s is not None]
        if stroke_colors:
            stroke_data = {"colors": stroke_colors}
            sw = node.get("strokeWeight")
            if sw and sw > 0:
                stroke_data["strokeWeight"] = f"{sw}px"
            sd = node.get("strokeDashes")
            if sd:
                stroke_data["strokeDashes"] = sd
            isw = node.get("individualStrokeWeights")
            if isw:
                stroke_data["strokeWeights"] = format_padding(
                    isw.get("top", 0), isw.get("right", 0),
                    isw.get("bottom", 0), isw.get("left", 0)
                )
            named = resolve_named_style(node, context, ["stroke", "strokes"])
            if named:
                context["globalVars"]["styles"][named] = stroke_colors
                result["strokes"] = named
            else:
                result["strokes"] = get_or_create_style_key(context["globalVars"], stroke_data, "stroke")

    effects = _process_effects(node)
    if effects:
        named = resolve_named_style(node, context, ["effect", "effects"])
        if named:
            context["globalVars"]["styles"][named] = effects
            result["effects"] = named
        else:
            result["effects"] = get_or_create_style_key(context["globalVars"], effects, "effect")

    opacity = node.get("opacity")
    if opacity is not None and opacity != 1:
        result["opacity"] = opacity

    cr = node.get("cornerRadius")
    rcr = node.get("rectangleCornerRadii")
    if rcr and isinstance(rcr, list) and len(rcr) == 4:
        result["borderRadius"] = f"{rcr[0]}px {rcr[1]}px {rcr[2]}px {rcr[3]}px"
    elif cr and cr > 0:
        result["borderRadius"] = f"{cr}px"


# ══════════════════════════════════════════════════════════════════
# Component Extractor
# ══════════════════════════════════════════════════════════════════

def component_extractor(node: dict, result: SimplifiedNode, context: TraversalContext):
    if node.get("type") != "INSTANCE":
        return
    cid = node.get("componentId")
    if cid:
        result["componentId"] = cid
    props = node.get("componentProperties")
    if props and isinstance(props, dict):
        result["componentProperties"] = [
            {"name": name, "value": str(info.get("value", "")), "type": info.get("type", "")}
            for name, info in props.items()
        ]


# ══════════════════════════════════════════════════════════════════
# Traversal Engine
# ══════════════════════════════════════════════════════════════════

def _traverse_node(
    node: dict,
    extractors: list[ExtractorFn],
    context: TraversalContext,
    max_depth: Optional[int],
    after_children_fn: Optional[Callable] = None,
) -> Optional[SimplifiedNode]:
    if not is_visible(node):
        return None

    node_type = node.get("type", "UNKNOWN")
    if node_type == "VECTOR":
        node_type = "IMAGE-SVG"

    result: SimplifiedNode = {
        "id": node.get("id", ""),
        "name": node.get("name", ""),
        "type": node_type,
    }

    for extractor in extractors:
        extractor(node, result, context)

    if max_depth is None or context["currentDepth"] < max_depth:
        children_raw = node.get("children", [])
        if children_raw:
            child_context = {
                **context,
                "currentDepth": context["currentDepth"] + 1,
                "parent": node,
            }
            children = []
            for child in children_raw:
                simplified = _traverse_node(child, extractors, child_context, max_depth, after_children_fn)
                if simplified:
                    children.append(simplified)

            if children:
                if after_children_fn:
                    children = after_children_fn(node, result, children)
                if children:
                    result["children"] = children

    return clean_empty(result)


def vector_collapse_hook(parent_node: dict, result: SimplifiedNode, children: list[SimplifiedNode]) -> list:
    if not children:
        return children
    parent_type = parent_node.get("type", "")
    all_vectors = all(c.get("type") in VECTOR_TYPES for c in children)
    is_container = parent_type in ("FRAME", "GROUP", "INSTANCE")
    if is_container and all_vectors:
        result["type"] = "IMAGE-SVG"
        return []
    return children


# ══════════════════════════════════════════════════════════════════
# Smart Filter (component handling for efa-*/cfa-*/wsp-*)
# ══════════════════════════════════════════════════════════════════

def smart_filter(node: dict, prefixes: tuple[str, ...] = DEFAULT_COMPONENT_PREFIXES) -> dict | list | None:
    """
    - efa-*/cfa-*/wsp-* component → semantic extract: props + child'lardan anlamsal özet çıkar
    - Noktalı (.xxx) node'lar bir component'in ALTINDA ise zaten atılıyor (parent component tüm subtree'yi özetliyor)
    - Noktalı node'lar bağımsız ise (parent component değilse) → at, ama içinde component varsa kurtar
    - Diğer node'lar → layout bilgisini koru, children'a recursive in
    """
    name = node.get("name", "")

    # ── 1. efa-*/cfa-*/wsp-* component (noktalı OLMAYAN) ──
    if _matches_component_prefix(name, prefixes) and not name.startswith("."):
        return _extract_component_semantic(node, prefixes)

    # ── 2. Noktalı node (herhangi bir .xxx) ──
    # Bunlar internal component'ler. Normalde parent efa-* tarafından özetlenirler.
    # Ama bazen bağımsız da olabilirler (parent efa-* değilse).
    # Bu durumda: kendisini at, içinde efa-*/cfa-*/wsp-* varsa kurtar.
    if name.startswith("."):
        rescued = []
        for child in node.get("children", []):
            r = smart_filter(child, prefixes)
            if r is not None:
                if isinstance(r, list):
                    rescued.extend(r)
                else:
                    rescued.append(r)
        return rescued if rescued else None

    # ── 3. Normal node (container/frame/text) → layout koru, children'a in ──
    result = {k: v for k, v in node.items() if k != "children"}
    children = node.get("children", [])
    if children:
        filtered = []
        for child in children:
            r = smart_filter(child, prefixes)
            if r is not None:
                if isinstance(r, list):
                    filtered.extend(r)
                else:
                    filtered.append(r)
        if filtered:
            result["children"] = filtered
    return result


def _extract_component_semantic(node: dict, prefixes: tuple[str, ...]) -> dict:
    """
    Bir efa-*/cfa-*/wsp-* component'ten anlamsal bilgi çıkar.
    Internal yapıyı (100+ node) at, yerine özet koy.

    Çıkarılan bilgiler:
    - componentProperties (Figma prop'ları)
    - texts: child'larda bulunan text içerikleri
    - icons: child'larda bulunan icon referansları
    - nested_components: child'larda bulunan diğer efa-*/cfa-*/wsp-* component'ler
    - repeated_patterns: tekrar eden yapılar (kolon sayısı, row sayısı vb.)
    """
    name = node.get("name", "")

    result = {
        "id": node.get("id"),
        "name": name,
        "type": node.get("type"),
        "layout": node.get("layout"),
        "componentId": node.get("componentId"),
    }

    # Figma component properties (prop-driven bilgi)
    props = node.get("componentProperties")
    if props:
        result["componentProperties"] = props

    # Child'lardan semantic bilgi çıkar
    semantic = _scan_subtree(node, prefixes)

    if semantic.get("texts"):
        result["extractedTexts"] = semantic["texts"]

    if semantic.get("icons"):
        result["extractedIcons"] = list(set(semantic["icons"]))  # deduplicate

    if semantic.get("nested_components"):
        result["nestedComponents"] = semantic["nested_components"]

    if semantic.get("sections"):
        result["extractedSections"] = semantic["sections"]

    return result


def _scan_subtree(node: dict, prefixes: tuple[str, ...]) -> dict:
    """
    Bir component'in tüm subtree'sini recursive tara.
    Text, icon, nested component ve tekrar eden pattern'ları topla.
    """
    texts = []
    icons = []
    nested_components = []
    sections = []

    children = node.get("children", [])
    for child in children:
        _collect_semantic(child, prefixes, texts, icons, nested_components, sections, depth=0)

    # Tekrar eden section'ları grupla ve say
    grouped_sections = _group_sections(sections)

    result = {}
    if texts:
        result["texts"] = texts
    if icons:
        result["icons"] = icons
    if nested_components:
        result["nested_components"] = nested_components
    if grouped_sections:
        result["sections"] = grouped_sections

    return result


def _collect_semantic(
    node: dict,
    prefixes: tuple[str, ...],
    texts: list,
    icons: list,
    nested_components: list,
    sections: list,
    depth: int,
):
    """Recursive olarak subtree'den anlamsal bilgi topla."""
    name = node.get("name", "")
    node_type = node.get("type", "")

    # ── Nested efa-*/cfa-*/wsp-* component (noktalı olmayanlar) ──
    if _matches_component_prefix(name, prefixes) and not name.startswith("."):
        # Bu component'in kendi props'ını al
        compact = {
            "name": name,
            "type": node_type,
        }
        props = node.get("componentProperties")
        if props:
            compact["componentProperties"] = props

        # Icon ise ayrıca icons listesine de ekle
        if _is_icon_node(name):
            icon_name = _extract_icon_name(name)
            if icon_name:
                icons.append(icon_name)
                compact["icon"] = icon_name
        else:
            nested_components.append(compact)
        return  # Bu component'in child'larına inme

    # ── Text node ──
    if node_type == "TEXT":
        text_content = node.get("text") or node.get("characters") or name
        if text_content and text_content.strip():
            texts.append(text_content.strip())
        return

    # ── Icon node (efa-icons:xxx pattern) ──
    if _is_icon_node(name):
        icon_name = _extract_icon_name(name)
        if icon_name:
            icons.append(icon_name)
        return

    # ── Section/column pattern detection ──
    # Noktalı node'lar section olarak kaydedilir (column, row, header vb.)
    if name.startswith("."):
        section_info = _extract_section_info(node, prefixes)
        if section_info:
            sections.append(section_info)
        return  # Noktalı node'un child'larına section_info içinde inildi

    # ── Normal container → recursive in ──
    for child in node.get("children", []):
        _collect_semantic(child, prefixes, texts, icons, nested_components, sections, depth + 1)


def _is_icon_node(name: str) -> bool:
    """efa-icons:xxx, cfa-icons:xxx, wsp-icons:xxx pattern'ını yakala."""
    name_lower = name.lower()
    return "icons:" in name_lower or "-icons:" in name_lower


def _extract_icon_name(name: str) -> str:
    """'efa-icons:edit' → 'edit', 'efa-icons:arrow_breadcrumbs' → 'arrow_breadcrumbs'"""
    if ":" in name:
        return name.split(":", 1)[1].strip()
    return name


def _extract_section_info(node: dict, prefixes: tuple[str, ...]) -> Optional[dict]:
    """
    Noktalı bir internal node'dan section bilgisi çıkar.
    Örn: .datatable column → type: column, header: "Header", cell_count: 5
    """
    name = node.get("name", "")
    name_lower = name.lower()

    info = {"name": name}

    # Header text'i bul
    headers = []
    cell_texts = []
    cell_icons = []
    child_count = 0

    for child in node.get("children", []):
        child_name = child.get("name", "").lower()
        child_type = child.get("type", "")

        # Header detection
        if "header" in child_name:
            header_texts = _find_texts_in_subtree(child)
            headers.extend(header_texts)

        # Column/cell container detection
        elif child_name in ("columns", "rows", "items", "cells"):
            cell_children = child.get("children", [])
            child_count = len(cell_children)
            # İlk cell'den sample al
            if cell_children:
                sample = cell_children[0]
                sample_texts = _find_texts_in_subtree(sample)
                cell_texts.extend(sample_texts)
                sample_icons = _find_icons_in_subtree(sample)
                cell_icons.extend(sample_icons)

        # Direct text child
        elif child_type == "TEXT":
            text = child.get("text") or child.get("characters") or child.get("name", "")
            if text.strip():
                headers.append(text.strip())

    if headers:
        info["header"] = headers[0]

    if child_count > 0:
        info["rowCount"] = child_count

    if cell_texts:
        info["cellType"] = "text"
        info["sampleValue"] = cell_texts[0]
    elif cell_icons:
        info["cellType"] = "icon"
        info["icon"] = cell_icons[0]

    # Column type detection from name
    if "column" in name_lower:
        info["type"] = "column"
    elif "header" in name_lower:
        info["type"] = "header"
    elif "pagination" in name_lower:
        info["type"] = "pagination"
    elif "row" in name_lower:
        info["type"] = "row"

    return info


def _find_texts_in_subtree(node: dict) -> list[str]:
    """Node subtree'sindeki tüm text content'leri bul."""
    texts = []
    if node.get("type") == "TEXT":
        text = node.get("text") or node.get("characters") or node.get("name", "")
        if text.strip():
            texts.append(text.strip())
    for child in node.get("children", []):
        texts.extend(_find_texts_in_subtree(child))
    return texts


def _find_icons_in_subtree(node: dict) -> list[str]:
    """Node subtree'sindeki tüm icon referanslarını bul."""
    icons = []
    name = node.get("name", "")
    if _is_icon_node(name):
        icon_name = _extract_icon_name(name)
        if icon_name:
            icons.append(icon_name)
    for child in node.get("children", []):
        icons.extend(_find_icons_in_subtree(child))
    return icons


def _group_sections(sections: list[dict]) -> list[dict]:
    """
    Tekrar eden section'ları grupla.
    Örn: 5 tane benzer '.datatable column' → tek entry, count: 5
    """
    if not sections:
        return []

    # Type + cellType bazında grupla
    groups = {}
    ungrouped = []

    for section in sections:
        sec_type = section.get("type", "")
        cell_type = section.get("cellType", "")
        key = f"{sec_type}|{cell_type}"

        if sec_type in ("column", "row"):
            if key not in groups:
                groups[key] = {
                    "type": sec_type,
                    "items": [],
                }
            groups[key]["items"].append(section)
        else:
            ungrouped.append(section)

    result = []

    for key, group in groups.items():
        items = group["items"]
        if len(items) == 1:
            result.append(items[0])
        else:
            # Grup özeti
            summary = {
                "type": group["type"],
                "count": len(items),
                "details": [],
            }
            for item in items:
                detail = {}
                if item.get("header"):
                    detail["header"] = item["header"]
                if item.get("cellType"):
                    detail["cellType"] = item["cellType"]
                if item.get("icon"):
                    detail["icon"] = item["icon"]
                if item.get("sampleValue"):
                    detail["sampleValue"] = item["sampleValue"]
                if detail:
                    summary["details"].append(detail)
            result.append(summary)

    result.extend(ungrouped)
    return result


def prune_unused_styles(styles: dict, nodes: list) -> dict:
    """Kullanılmayan style key'leri globalVars'tan sil."""
    used_keys = set()
    _collect_style_keys(nodes, used_keys)
    return {k: v for k, v in styles.items() if k in used_keys}


def _collect_style_keys(nodes: list, keys: set):
    for node in nodes:
        for field in ("layout", "textStyle", "fills", "strokes", "effects"):
            val = node.get(field)
            if isinstance(val, str):
                keys.add(val)
        if "children" in node:
            _collect_style_keys(node["children"], keys)


# ══════════════════════════════════════════════════════════════════
# Design Rules Generator
# ══════════════════════════════════════════════════════════════════

def generate_design_rules(simplified: dict) -> str:
    rules = []
    nodes = simplified.get("nodes", [])
    styles = simplified.get("globalVars", {}).get("styles", {})
    components = simplified.get("components", {})

    # 1. Root layout
    root = nodes[0] if nodes else {}
    root_layout = styles.get(root.get("layout", ""), {})
    if root_layout:
        rules.append(f"## Root Container: \"{root.get('name', '')}\"")
        rules.append(f"- Direction: {root_layout.get('mode', 'column')}")
        if root_layout.get("justifyContent"):
            rules.append(f"- Main axis: {root_layout['justifyContent']}")
        if root_layout.get("alignItems"):
            rules.append(f"- Cross axis: {root_layout['alignItems']}")
        if root_layout.get("gap"):
            rules.append(f"- Gap: {root_layout['gap']}")
        if root_layout.get("padding"):
            rules.append(f"- Padding: {root_layout['padding']}")
        rules.append("")

    # 2. Color palette
    colors = set()
    _extract_colors_from_styles(styles, colors)
    if colors:
        rules.append("## Color Palette")
        for color in sorted(colors):
            rules.append(f"- {color}")
        rules.append("")

    # 3. Typography
    text_styles = {k: v for k, v in styles.items() if isinstance(v, dict) and "fontSize" in v}
    if text_styles:
        rules.append("## Typography")
        for key, ts in text_styles.items():
            parts = []
            if ts.get("fontFamily"): parts.append(ts["fontFamily"])
            if ts.get("fontWeight"): parts.append(f"weight {ts['fontWeight']}")
            if ts.get("fontSize"): parts.append(f"{ts['fontSize']}px")
            if ts.get("lineHeight"): parts.append(f"line-height {ts['lineHeight']}")
            rules.append(f"- {key}: {', '.join(parts)}")
        rules.append("")

    # 4. Component structure
    rules.append("## Component Structure")
    _describe_node_tree(nodes, styles, rules, indent=0)
    rules.append("")

    # 5. Component library refs
    if components:
        rules.append("## Component Library References")
        for cid, comp in components.items():
            rules.append(f"- \"{comp.get('name', '')}\" (id: {cid})")
        rules.append("")

    return "\n".join(rules)


def _extract_colors_from_styles(styles: dict, colors: set):
    for value in styles.values():
        _walk_for_colors(value, colors)


def _walk_for_colors(value, colors: set):
    if isinstance(value, str):
        if value.startswith("#") or value.startswith("rgba("):
            colors.add(value)
    elif isinstance(value, list):
        for item in value:
            _walk_for_colors(item, colors)
    elif isinstance(value, dict):
        for v in value.values():
            _walk_for_colors(v, colors)


def _describe_node_tree(nodes: list, styles: dict, rules: list, indent: int):
    prefix = "  " * indent
    for node in nodes:
        name = node.get("name", "")
        node_type = node.get("type", "")
        layout = styles.get(node.get("layout", ""), {})

        desc = f"{prefix}- \"{name}\" ({node_type})"

        mode = layout.get("mode") if isinstance(layout, dict) else None
        if mode and mode != "none":
            gap = layout.get("gap", "")
            gap_str = f", gap: {gap}" if gap else ""
            desc += f" -> flex {mode}{gap_str}"

        dims = layout.get("dimensions", {}) if isinstance(layout, dict) else {}
        sizing = layout.get("sizing", {}) if isinstance(layout, dict) else {}
        size_parts = []
        if dims.get("width"):
            size_parts.append(f"w:{dims['width']}px")
        elif sizing.get("horizontal") == "fill":
            size_parts.append("w:fill")
        if dims.get("height"):
            size_parts.append(f"h:{dims['height']}px")
        elif sizing.get("vertical") == "fill":
            size_parts.append("h:fill")
        if size_parts:
            desc += f" [{', '.join(size_parts)}]"

        if node.get("text"):
            desc += f" text=\"{node['text'][:50]}\""

        if node.get("componentId"):
            desc += " (component instance)"

        rules.append(desc)

        children = node.get("children", [])
        if children:
            _describe_node_tree(children, styles, rules, indent + 1)


# ══════════════════════════════════════════════════════════════════
# Extractor Presets
# ══════════════════════════════════════════════════════════════════

ALL_EXTRACTORS: list[ExtractorFn] = [
    layout_extractor, text_extractor, visuals_extractor, component_extractor
]


# ══════════════════════════════════════════════════════════════════
# Main Entry Point
# ══════════════════════════════════════════════════════════════════

def simplify_figma_response(
    api_response: dict,
    extractors: list[ExtractorFn] = None,
    max_depth: Optional[int] = None,
    component_prefixes: tuple[str, ...] = DEFAULT_COMPONENT_PREFIXES,
    apply_smart_filter: bool = True,
    include_design_rules: bool = False,
) -> dict:
    """
    Ana entry point.

    Args:
        api_response: Figma REST API'den gelen raw JSON
        extractors: kullanılacak extractor listesi (default: hepsi)
        max_depth: tree traversal derinlik limiti (None = sınırsız)
        component_prefixes: component prefix'leri (default: ("efa-", "cfa-", "wsp-"))
        apply_smart_filter: component'lerin iç yapısını at (default: True)
        include_design_rules: sözel design rules ekle (default: False)
    """
    if extractors is None:
        extractors = ALL_EXTRACTORS

    # 1. Parse API response
    raw_nodes = []
    components = {}
    component_sets = {}
    extra_styles = {}
    name = api_response.get("name", "")

    if "nodes" in api_response:
        for node_data in api_response["nodes"].values():
            if node_data and node_data.get("document"):
                raw_nodes.append(node_data["document"])
            if node_data and node_data.get("components"):
                components.update(node_data["components"])
            if node_data and node_data.get("componentSets"):
                component_sets.update(node_data["componentSets"])
            if node_data and node_data.get("styles"):
                extra_styles.update(node_data["styles"])
    else:
        doc = api_response.get("document", {})
        raw_nodes = doc.get("children", [])
        components = api_response.get("components", {})
        component_sets = api_response.get("componentSets", {})
        extra_styles = api_response.get("styles", {})

    # 2. Extract
    global_vars = {"styles": {}, "extraStyles": extra_styles}
    context: TraversalContext = {
        "globalVars": global_vars,
        "currentDepth": 0,
        "parent": None,
    }

    simplified_nodes = []
    for node in raw_nodes:
        if is_visible(node):
            result = _traverse_node(node, extractors, context, max_depth, vector_collapse_hook)
            if result:
                simplified_nodes.append(result)

    # 3. Smart filter (component iç yapısını at)
    if apply_smart_filter:
        filtered_nodes = []
        for node in simplified_nodes:
            r = smart_filter(node, component_prefixes)
            if r is not None:
                if isinstance(r, list):
                    filtered_nodes.extend(r)
                else:
                    filtered_nodes.append(r)
        simplified_nodes = filtered_nodes

        # Kullanılmayan style'ları temizle
        global_vars["styles"] = prune_unused_styles(
            global_vars["styles"], simplified_nodes
        )

    # 4. Build result
    simplified_components = {
        cid: {
            "id": cid, "key": c.get("key", ""),
            "name": c.get("name", ""),
            "componentSetId": c.get("componentSetId"),
        }
        for cid, c in components.items()
    }
    simplified_sets = {
        sid: {
            "id": sid, "key": s.get("key", ""),
            "name": s.get("name", ""),
            "description": s.get("description"),
        }
        for sid, s in component_sets.items()
    }

    output = {
        "name": name,
        "nodes": simplified_nodes,
        "components": simplified_components,
        "componentSets": simplified_sets,
        "globalVars": {"styles": global_vars["styles"]},
    }

    # 5. Design rules (opsiyonel)
    if include_design_rules:
        output["design_rules"] = generate_design_rules(output)

    return output