#!/usr/bin/env python3
"""Convert the validated HTML body this skill builds into Confluence storage format.

Mapped constructs:

    div toc placeholder     ac:structured-macro toc, keeping macroId (from macroMetadata.macroId.value
                            in data-parameters, or data-macro-id) and every macroParams value
    img                     ac:image with ac:alt, ac:width, ac:height; an attachment download URL becomes
                            ri:attachment, any other src becomes ri:url
    figure media-single     ac:image with ac:align (center only), ac:layout, and ac:caption from figcaption
    table                   data-layout kept; data-colwidth of the first row becomes a colgroup
                            (a comma list splits across a colspan); thead rows move into tbody
    p, br, hr               empty paragraphs and in-paragraph line breaks are kept one for one
    a href="#name"          kept as a plain a href, the form Confluence stores for an in-page link
    a id="name"             anchor macro (the element must be empty)
    pre                     code macro with optional language from class="language-NAME"
    details/summary         expand macro
    p, h1-h6, ul, ol, li, blockquote, strong, b, em, i, u, s, del, sub, sup, code, a href
                            passed through

Anything else stops the conversion with an error that names the line and the construct: an unmapped
element, an unmapped attribute, a div that is not a toc placeholder, an HTML comment, mismatched or
unclosed tags, and ac:inline-comment-marker (comment markers are restored by comment_markers.py).
Nothing is dropped silently.

Usage:
    storage_body.py BODY_FILE [--output FILE]
    cat body.html | storage_body.py - [--output FILE]

Exit codes: 0 converted, 1 the body holds an unmapped construct, 2 usage or read error.
"""

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

VOID_ELEMENTS = frozenset({"br", "hr", "img", "col"})
PASSTHROUGH = {
    "p": (), "h1": (), "h2": (), "h3": (), "h4": (), "h5": (), "h6": (),
    "ul": (), "ol": ("start",), "li": (), "blockquote": (),
    "strong": (), "b": (), "em": (), "i": (), "u": (), "s": (), "del": (), "sub": (), "sup": (), "code": (),
}
TOC_EXTENSION_TYPE = "com.atlassian.confluence.macro.core"
ATTACHMENT_PATTERN = re.compile(r"/download/attachments/[^/]+/([^?#]+)")
CAPTION_INLINE = frozenset({"strong", "em", "code", "a"})
LANGUAGE_CLASS = re.compile(r"^language-([A-Za-z0-9_+#.-]+)$")


class ConversionError(Exception):
    """The body holds a construct this converter does not map."""


@dataclass(frozen=True)
class Node:
    tag: str
    attrs: tuple
    children: tuple
    line: int

    def attr(self, name, default=None):
        return dict(self.attrs).get(name, default)


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = [("#root", (), [], 1)]

    def _fail(self, message):
        raise ConversionError(f"line {self.getpos()[0]}: {message}")

    def _attach(self, item):
        self.stack[-1][2].append(item)

    def _make(self, tag, attrs, children, line):
        return Node(tag, tuple((name, "" if value is None else value) for name, value in attrs), tuple(children), line)

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        if tag in VOID_ELEMENTS:
            self._attach(self._make(tag, attrs, (), line))
        else:
            self.stack.append((tag, attrs, [], line))

    def handle_startendtag(self, tag, attrs):
        self._attach(self._make(tag, attrs, (), self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        name, attrs, children, line = self.stack[-1]
        if len(self.stack) == 1 or name != tag:
            self._fail(f"closing </{tag}> does not match open <{name}>")
        self.stack.pop()
        self._attach(self._make(name, attrs, children, line))

    def handle_data(self, data):
        self._attach(data)

    def handle_comment(self, data):
        self._fail("HTML comment is not mapped; remove it or move its content into the body")

    def handle_decl(self, decl):
        self._fail(f"declaration <!{decl}> is not mapped")

    def handle_pi(self, data):
        self._fail(f"processing instruction <?{data}> is not mapped")

    def unknown_decl(self, data):
        self._fail(f"declaration <![{data}]> is not mapped")

    def result(self):
        if len(self.stack) > 1:
            name, _, _, line = self.stack[-1]
            raise ConversionError(f"line {line}: <{name}> is never closed")
        return tuple(self.stack[0][2])


def parse_tree(body: str) -> tuple:
    builder = TreeBuilder()
    builder.feed(body)
    builder.close()
    return builder.result()


def fail(node: Node, message: str):
    raise ConversionError(f"line {node.line}: {message}")


def check_attrs(node: Node, allowed) -> None:
    for name, _ in node.attrs:
        if name not in allowed:
            fail(node, f"unmapped attribute {name} on <{node.tag}>")


def escape_text(text: str) -> str:
    return html.escape(text, quote=False)


def escape_attr(text: str) -> str:
    return html.escape(text, quote=True)


def attrs_markup(pairs) -> str:
    return "".join(f' {name}="{escape_attr(value)}"' for name, value in pairs)


def render_children(children) -> str:
    return "".join(render_item(child) for child in children)


def render_item(item) -> str:
    if isinstance(item, str):
        return escape_text(item)
    handler = HANDLERS.get(item.tag)
    if handler is not None:
        return handler(item)
    if item.tag in PASSTHROUGH:
        return render_passthrough(item)
    return fail(item, f"unmapped element <{item.tag}>" + comment_marker_hint(item.tag))


def comment_marker_hint(tag: str) -> str:
    if tag == "ac:inline-comment-marker":
        return "; build the body without markers and restore them with comment_markers.py"
    return ""


def render_passthrough(node: Node) -> str:
    check_attrs(node, PASSTHROUGH[node.tag])
    if not node.children:
        return f"<{node.tag} />" if node.tag == "p" else f"<{node.tag}{attrs_markup(node.attrs)}></{node.tag}>"
    return f"<{node.tag}{attrs_markup(node.attrs)}>{render_children(node.children)}</{node.tag}>"


def render_void(node: Node) -> str:
    check_attrs(node, ())
    return f"<{node.tag} />"


def plain_text(node: Node, what: str) -> str:
    parts = []
    for child in node.children:
        if not isinstance(child, str):
            fail(node, f"<{node.tag}> holds <{child.tag}>, which is not mapped inside {what}")
        parts.append(child)
    return "".join(parts)


def is_blank(item) -> bool:
    return isinstance(item, str) and not item.strip()


def macro(name: str, parameters, body: str = "", macro_id: str = "") -> str:
    identifier = f' ac:macro-id="{escape_attr(macro_id)}"' if macro_id else ""
    params = "".join(f'<ac:parameter ac:name="{escape_attr(key)}">{escape_text(value)}</ac:parameter>' for key, value in parameters)
    return f'<ac:structured-macro ac:name="{name}" ac:schema-version="1"{identifier}>{params}{body}</ac:structured-macro>'


def toc_macro(node: Node) -> str:
    extension_type = node.attr("data-extension-type", TOC_EXTENSION_TYPE)
    if extension_type != TOC_EXTENSION_TYPE:
        fail(node, f"unmapped div extension type {extension_type}")
    if node.attr("data-layout", "default") != "default":
        fail(node, f"unmapped div data-layout {node.attr('data-layout')}")
    if any(not is_blank(child) for child in node.children):
        fail(node, "table-of-contents div must be empty")
    allowed = {"data-type", "data-extension-key", "data-extension-type", "data-layout", "data-parameters", "data-macro-id"}
    check_attrs(node, allowed)
    parameters, macro_id = toc_parameters(node)
    return macro("toc", parameters, macro_id=macro_id)


def toc_parameters(node: Node):
    try:
        data = json.loads(node.attr("data-parameters", "{}"))
    except json.JSONDecodeError as error:
        fail(node, f"toc data-parameters is not JSON: {error}")
    if not isinstance(data, dict) or set(data) - {"macroParams", "macroMetadata"}:
        fail(node, "toc data-parameters holds keys other than macroParams and macroMetadata")
    params = data.get("macroParams", {})
    pairs = []
    for key, entry in params.items():
        if not isinstance(entry, dict) or set(entry) != {"value"}:
            fail(node, f"toc parameter {key} is not a plain value")
        pairs.append((key, str(entry["value"])))
    return pairs, toc_macro_id(node, data)


def toc_macro_id(node: Node, data: dict) -> str:
    from_metadata = data.get("macroMetadata", {}).get("macroId", {}).get("value", "")
    from_attribute = node.attr("data-macro-id", "")
    if from_metadata and from_attribute and from_metadata != from_attribute:
        fail(node, "toc macroId differs between data-parameters and data-macro-id")
    return from_metadata or from_attribute


def render_div(node: Node) -> str:
    key = node.attr("data-extension-key")
    if node.attr("data-type") != "extension" or key is None:
        fail(node, f"unmapped div (data-type={node.attr('data-type')})")
    if key != "toc":
        fail(node, f"unmapped macro div (data-extension-key={key})")
    return toc_macro(node)


def image_target(node: Node) -> str:
    check_attrs(node, {"src", "alt", "width", "height"})
    source = node.attr("src", "")
    if not source:
        fail(node, "<img> has no src")
    match = ATTACHMENT_PATTERN.search(source)
    if match:
        return f'<ri:attachment ri:filename="{escape_attr(unquote(match.group(1)))}" />'
    return f'<ri:url ri:value="{escape_attr(source)}" />'


def image_pairs(node: Node) -> list:
    return [(f"ac:{name}", node.attr(name)) for name in ("alt", "width", "height") if node.attr(name) is not None]


def render_image(node: Node) -> str:
    target = image_target(node)
    return f"<ac:image{attrs_markup(image_pairs(node))}>{target}</ac:image>"


def figure_parts(node: Node):
    images, captions = [], []
    for child in node.children:
        if is_blank(child):
            continue
        if isinstance(child, str) or child.tag not in {"img", "figcaption"}:
            shown = child.strip() if isinstance(child, str) else f"<{child.tag}>"
            fail(node, f"<figure> holds {shown}, which is not mapped; only one <img> and one <figcaption>")
        (images if child.tag == "img" else captions).append(child)
    if len(images) != 1 or len(captions) > 1:
        fail(node, f"<figure> holds {len(images)} images and {len(captions)} captions; it needs one image and at most one caption")
    return images[0], (captions[0] if captions else None)


def check_inline(node: Node, owner: Node) -> None:
    for child in node.children:
        if isinstance(child, str):
            continue
        if child.tag not in CAPTION_INLINE:
            fail(owner, f"<{owner.tag}> holds <{child.tag}>, which is not mapped; only text, strong, em, code, and links")
        if child.tag == "a" and (child.attr("id") is not None or child.attr("name") is not None):
            fail(owner, f"<{owner.tag}> holds an anchor <a>, which is not mapped")
        check_inline(child, owner)


def render_caption(caption: Node) -> str:
    check_attrs(caption, ())
    check_inline(caption, caption)
    return f"<ac:caption><p>{render_children(caption.children)}</p></ac:caption>"


def render_figure(node: Node) -> str:
    check_attrs(node, {"data-type", "data-layout"})
    if node.attr("data-type") != "media-single":
        fail(node, f"unmapped figure data-type {node.attr('data-type')}; use media-single")
    image, caption = figure_parts(node)
    layout = node.attr("data-layout")
    pairs = [("ac:align", "center")] if layout == "center" else []
    pairs += [("ac:layout", layout)] if layout else []
    markup = render_caption(caption) if caption is not None else ""
    return f"<ac:image{attrs_markup(pairs + image_pairs(image))}>{image_target(image)}{markup}</ac:image>"


def render_link(node: Node) -> str:
    anchor_name = node.attr("id") or node.attr("name")
    if anchor_name is not None:
        return render_anchor(node, anchor_name)
    check_attrs(node, {"href"})
    href = node.attr("href", "")
    if not href:
        fail(node, "<a> has no href")
    return f'<a href="{escape_attr(href)}">{render_children(node.children)}</a>'


def render_anchor(node: Node, name: str) -> str:
    check_attrs(node, {"id", "name"})
    if any(not is_blank(child) for child in node.children):
        fail(node, "<a id> that marks an anchor must be empty")
    return macro("anchor", [("", name)])


def cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def render_pre(node: Node) -> str:
    check_attrs(node, ())
    children = tuple(child for child in node.children if not is_blank(child))
    language = ""
    if len(children) == 1 and isinstance(children[0], Node) and children[0].tag == "code":
        code = children[0]
        check_attrs(code, {"class"})
        language = code_language(code)
        node = Node("pre", (), code.children, node.line)
    text = plain_text(node, "a code block")
    parameters = [("language", language)] if language else []
    return macro("code", parameters, f"<ac:plain-text-body>{cdata(text)}</ac:plain-text-body>")


def code_language(code: Node) -> str:
    value = code.attr("class")
    if value is None:
        return ""
    match = LANGUAGE_CLASS.match(value)
    if not match:
        fail(code, f"unmapped class {value} on <code>")
    return match.group(1)


def render_details(node: Node) -> str:
    check_attrs(node, ())
    children = list(node.children)
    while children and is_blank(children[0]):
        children.pop(0)
    if not children or not isinstance(children[0], Node) or children[0].tag != "summary":
        fail(node, "<details> must start with <summary>")
    summary = children[0]
    check_attrs(summary, ())
    body = f"<ac:rich-text-body>{render_children(children[1:])}</ac:rich-text-body>"
    return macro("expand", [("title", plain_text(summary, "a summary"))], body)


def column_widths(table_node: Node, rows) -> list:
    first = [cell for cell in rows[0].children if isinstance(cell, Node)] if rows else []
    widths = []
    declared = [cell.attr("data-colwidth") is not None for cell in first]
    if not any(declared):
        return []
    if not all(declared):
        fail(table_node, "data-colwidth is set on some cells of the first row but not all")
    for cell in first:
        parts = [part.strip() for part in cell.attr("data-colwidth").split(",")]
        span = int(cell.attr("colspan", "1") or "1")
        if len(parts) != span or not all(part.isdigit() for part in parts):
            fail(cell, f"data-colwidth {cell.attr('data-colwidth')} does not match colspan {span}")
        widths.extend(parts)
    return widths


def collect_rows(table_node: Node) -> list:
    rows = []
    for child in table_node.children:
        if is_blank(child):
            continue
        if isinstance(child, str) or child.tag not in {"thead", "tbody", "tr"}:
            fail(table_node, f"unmapped table child {child if isinstance(child, str) else '<' + child.tag + '>'}")
        if child.tag == "tr":
            rows.append(child)
            continue
        check_attrs(child, ())
        for row in child.children:
            if is_blank(row):
                continue
            if isinstance(row, str) or row.tag != "tr":
                fail(child, f"unmapped child of <{child.tag}>")
            rows.append(row)
    return rows


def render_cell(node: Node) -> str:
    check_attrs(node, {"colspan", "rowspan", "data-colwidth"})
    kept = [(name, value) for name, value in node.attrs if name != "data-colwidth"]
    return f"<{node.tag}{attrs_markup(kept)}>{render_children(node.children)}</{node.tag}>"


def render_row(node: Node) -> str:
    check_attrs(node, ())
    cells = []
    for child in node.children:
        if is_blank(child):
            continue
        if isinstance(child, str) or child.tag not in {"td", "th"}:
            fail(node, "unmapped child of <tr>")
        cells.append(render_cell(child))
    return f"<tr>{''.join(cells)}</tr>"


def render_table(node: Node) -> str:
    check_attrs(node, {"data-layout"})
    rows = collect_rows(node)
    widths = column_widths(node, rows)
    group = ""
    if widths:
        cols = "".join(f'<col style="width: {width}px;" />' for width in widths)
        group = f"<colgroup>{cols}</colgroup>"
    body = "".join(render_row(row) for row in rows)
    return f"<table{attrs_markup(node.attrs)}>{group}<tbody>{body}</tbody></table>"


HANDLERS = {
    "br": render_void,
    "hr": render_void,
    "div": render_div,
    "img": render_image,
    "figure": render_figure,
    "a": render_link,
    "pre": render_pre,
    "details": render_details,
    "table": render_table,
}


def convert(body: str) -> str:
    return render_children(parse_tree(body))


def read_input(name: str) -> str:
    if name == "-":
        return sys.stdin.read()
    return Path(name).read_text(encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Convert a validated HTML body to Confluence storage format.")
    parser.add_argument("body", help="HTML body file, or - for standard input")
    parser.add_argument("--output", help="write the storage body here instead of standard output")
    args = parser.parse_args(argv)
    try:
        body = read_input(args.body)
    except (OSError, UnicodeDecodeError) as error:
        print(f"error: cannot read {args.body}: {error}", file=sys.stderr)
        return 2
    try:
        storage = convert(body)
    except ConversionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(storage, encoding="utf-8")
    else:
        sys.stdout.write(storage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
