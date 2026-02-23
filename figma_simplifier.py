"""
figma_simplifier.py — Figma-Context-MCP v0.6.4 Extractor Pattern, Python port
"""
import json
import string
import random
from typing import Any, Callable, Optional

# ══════════════════════════════════════════════════════════════════
# Types
# ══════════════════════════════════════════════════════════════════

SimplifiedNode = dict[str, Any]
GlobalVars = dict[str, dict[str, Any]]  # {"styles": {key: value}}
TraversalContext = dict[str, Any]       # {"globalVars", "currentDepth", "parent"}
ExtractorFn = Callable[[dict, SimplifiedNode, TraversalContext], None]


# ══════════════════════════════════════════════════════════════════
# Utility Functions
# ══════════════════════════════════════════════════════════════════

VECTOR_TYPES = frozenset({
    "IMAGE-SVG", "VECTOR", "STAR", "LINE",
    "ELLIPSE", "REGULAR_POLYGON", "RECTANGLE"
})


def is_visible(node: dict) -> bool:
    return node.get("visible", True)


def round_num(n: float) -> float:
    if n != n:  # NaN check
        raise TypeError("Input must be a valid number")
    return round(n, 2)


def format_padding(top: float, right: float, bottom: float, left: float) -> Optional[str]:
    if top == 0 and right == 0 and bottom == 0 and left == 0:
        return None
    vals = [top, right, bottom, left]
    if all(v == top for v in vals):
        return f"{top}px"
    if left == right and top == bottom:
        return f"{top}px {right}px"
    if left == right:
        return f"{top}px {right}px {bottom}px"
    return f"{top}px {right}px {bottom}px {left}px"


def clean_empty(obj: Any) -> Any:
    """Remove None, empty lists, empty dicts recursively."""
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
        hex_str = f"#{r:02X}{g:02X}{b:02X}"
        return hex_str
    return f"rgba({r}, {g}, {b}, {a})"


def get_or_create_style_key(
    global_vars: dict, style_value: Any, prefix: str = "var"
) -> str:
    """Style factoring: deduplicate identical styles."""
    serialized = json.dumps(style_value, sort_keys=True)
    for key, existing in global_vars["styles"].items():
        if json.dumps(existing, sort_keys=True) == serialized:
            return key
    new_key = generate_var_key(prefix)
    global_vars["styles"][new_key] = style_value
    return new_key


def resolve_named_style(node: dict, context: TraversalContext, style_keys: list[str]) -> Optional[str]:
    """If Figma has a named style, use that name instead of auto-generated key."""
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
    # Eğer tüm children fill ise → stretch
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
    """Extract auto-layout properties from node."""
    layout_mode_raw = node.get("layoutMode")
    if not layout_mode_raw or layout_mode_raw == "NONE":
        mode = "none"
    elif layout_mode_raw == "HORIZONTAL":
        mode = "row"
    else:
        mode = "column"

    result = {"mode": mode}

    # Overflow scroll
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
        node.get("primaryAxisAlignItems", "MIN"),
        children, "primary", mode
    )
    result["alignItems"] = _map_primary_align(
        node.get("counterAxisAlignItems", "MIN"),
        children, "counter", mode
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
    """Extract sizing and position relative to parent."""
    result = {"mode": mode}
    result["sizing"] = {
        "horizontal": _map_sizing(node.get("layoutSizingHorizontal")),
        "vertical": _map_sizing(node.get("layoutSizingVertical")),
    }

    # Absolute positioning
    if node.get("layoutPositioning") == "ABSOLUTE":
        result["position"] = "absolute"

    bbox = node.get("absoluteBoundingBox", {})
    parent_bbox = (parent or {}).get("absoluteBoundingBox", {})

    # Location relative to parent:
    # - Explicit absolute positioned nodes → always
    # - Children of mode:none parents → always (no flex to determine position)
    needs_position = result.get("position") == "absolute"
    
    # Check if parent has no auto-layout (mode: none)
    parent_layout_mode = parent.get("layoutMode") if parent else None
    if parent and (not parent_layout_mode or parent_layout_mode == "NONE"):
        needs_position = True

    if needs_position and bbox and parent_bbox:
        result["locationRelativeToParent"] = {
            "x": round_num(bbox.get("x", 0) - parent_bbox.get("x", 0)),
            "y": round_num(bbox.get("y", 0) - parent_bbox.get("y", 0)),
        }
    
    # For mode:none nodes, also store own bounding box as fallback
    # (parent bbox may not always be available)
    if mode == "none" and bbox:
        w = bbox.get("width")
        h = bbox.get("height")
        if w is not None and h is not None:
            result["boundingBox"] = {
                "x": round_num(bbox.get("x", 0)),
                "y": round_num(bbox.get("y", 0)),
                "width": round_num(w),
                "height": round_num(h),
            }

    # Dimensions (contextual — depends on parent layout mode)
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
        else:  # none
            if not h_sizing or h_sizing == "FIXED":
                dims["width"] = round_num(w) if w else None
            if not v_sizing or v_sizing == "FIXED":
                dims["height"] = round_num(h) if h else None

        if dims:
            result["dimensions"] = dims

    return result


def layout_extractor(node: dict, result: SimplifiedNode, context: TraversalContext):
    """Extractor: layout mode, spacing, sizing, position."""
    layout_props = _extract_layout_props(node)
    dim_props = _extract_dimensions(
        node, context.get("parent"), layout_props.get("mode", "none")
    )
    merged = {**layout_props, **dim_props}

    # Sadece mode: none olan boş layout'ları kaydetme
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
    """Extractor: text content and typography styles."""
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
    """Convert a single Figma fill to simplified form."""
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
        # CSS mapping based on scaleMode
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

        # Crop transform
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
    """Extract shadow, blur, backdrop-blur as CSS values."""
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
    """Extractor: fills, strokes, effects, opacity, border-radius."""
    has_children = bool(node.get("children"))

    # Fills
    fills_raw = node.get("fills", [])
    if fills_raw:
        processed = [_process_fill(f, has_children) for f in fills_raw]
        processed = [f for f in processed if f is not None]
        # Figma'da fills ters sırada render edilir
        processed.reverse()
        if processed:
            named = resolve_named_style(node, context, ["fill", "fills"])
            if named:
                context["globalVars"]["styles"][named] = processed
                result["fills"] = named
            else:
                result["fills"] = get_or_create_style_key(context["globalVars"], processed, "fill")

    # Strokes
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
            # Individual stroke weights
            isw = node.get("individualStrokeWeights")
            if isw:
                stroke_data["strokeWeights"] = format_padding(isw.get("top",0), isw.get("right",0), isw.get("bottom",0), isw.get("left",0))

            named = resolve_named_style(node, context, ["stroke", "strokes"])
            if named:
                context["globalVars"]["styles"][named] = stroke_colors
                result["strokes"] = named
            else:
                result["strokes"] = get_or_create_style_key(context["globalVars"], stroke_data, "stroke")

    # Effects
    effects = _process_effects(node)
    if effects:
        named = resolve_named_style(node, context, ["effect", "effects"])
        if named:
            context["globalVars"]["styles"][named] = effects
            result["effects"] = named
        else:
            result["effects"] = get_or_create_style_key(context["globalVars"], effects, "effect")

    # Opacity
    opacity = node.get("opacity")
    if opacity is not None and opacity != 1:
        result["opacity"] = opacity

    # Border radius
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
    """Extractor: component instance info."""
    if node.get("type") != "INSTANCE":
        return

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
    """Recursively traverse and simplify a single node."""
    if not is_visible(node):
        return None

    # Base node
    node_type = node.get("type", "UNKNOWN")
    if node_type == "VECTOR":
        node_type = "IMAGE-SVG"

    result: SimplifiedNode = {
        "name": node.get("name", ""),
        "type": node_type,
    }

    # Run all extractors
    for extractor in extractors:
        extractor(node, result, context)

    # Traverse children (depth controlled)
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
    """afterChildren hook: collapse all-vector containers into IMAGE-SVG.
    
    INSTANCE node'ları collapse ETMEYİZ — çünkü component bilgisi (name, componentId,
    componentProperties) korunmalı. Özellikle efa-icons:* gibi icon component'leri
    tek bir Vector child'a sahiptir, bunları IMAGE-SVG'ye çevirmek bilgi kaybıdır.
    """
    if not children:
        return children
    parent_type = parent_node.get("type", "")
    all_vectors = all(c.get("type") in VECTOR_TYPES for c in children)
    # Sadece FRAME ve GROUP collapse edilir, INSTANCE asla
    is_collapsible = parent_type in ("FRAME", "GROUP")

    if is_collapsible and all_vectors:
        result["type"] = "IMAGE-SVG"
        return []  # Drop children
    
    # INSTANCE ise children'ı at ama type'ı koru
    if parent_type == "INSTANCE" and all_vectors:
        return []  # Vector children gereksiz, ama INSTANCE type'ı ve bilgileri korunur
    
    return children


# ══════════════════════════════════════════════════════════════════
# Main Entry Points
# ══════════════════════════════════════════════════════════════════

ALL_EXTRACTORS: list[ExtractorFn] = [
    layout_extractor, text_extractor, visuals_extractor, component_extractor
]


def extract_from_design(
    nodes: list[dict],
    extractors: list[ExtractorFn] = None,
    max_depth: Optional[int] = None,
    global_vars: Optional[dict] = None,
) -> dict:
    """Traverse multiple root nodes and extract simplified data."""
    if extractors is None:
        extractors = ALL_EXTRACTORS
    if global_vars is None:
        global_vars = {"styles": {}}

    context: TraversalContext = {
        "globalVars": global_vars,
        "currentDepth": 0,
        "parent": None,
    }

    simplified_nodes = []
    for node in nodes:
        if is_visible(node):
            result = _traverse_node(node, extractors, context, max_depth, vector_collapse_hook)
            if result:
                simplified_nodes.append(result)

    return {
        "nodes": simplified_nodes,
        "globalVars": {"styles": global_vars["styles"]},
    }


def simplify_figma_response(
    api_response: dict,
    extractors: list[ExtractorFn] = None,
    max_depth: Optional[int] = None,
) -> dict:
    """
    Ana entry point.
    Figma REST API response'unu (GetFile veya GetFileNodes) alır,
    SimplifiedDesign döner.
    
    api_response: Figma API'den gelen raw JSON
    extractors: kullanılacak extractor listesi (default: hepsi)
    max_depth: tree traversal derinlik limiti
    """
    if extractors is None:
        extractors = ALL_EXTRACTORS

    # Parse API response (GetFile vs GetFileNodes format)
    raw_nodes = []
    extra_styles = {}
    name = api_response.get("name", "")

    if "nodes" in api_response:
        # GetFileNodes response
        for node_data in api_response["nodes"].values():
            if node_data and node_data.get("document"):
                raw_nodes.append(node_data["document"])
            if node_data and node_data.get("styles"):
                extra_styles.update(node_data["styles"])
    else:
        # GetFile response
        doc = api_response.get("document", {})
        raw_nodes = doc.get("children", [])
        extra_styles = api_response.get("styles", {})

    # Global vars with extra styles for named style resolution
    global_vars = {"styles": {}, "extraStyles": extra_styles}

    # Run extraction
    result = extract_from_design(raw_nodes, extractors, max_depth, global_vars)

    return {
        "name": name,
        "nodes": result["nodes"],
        "globalVars": {"styles": result["globalVars"]["styles"]},
    }