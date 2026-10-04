"""A tiny, dependency-free HTML tree.

Only used for *reading*: measurement (copy slots), proof generation (the tree
signature that shows a restyle did not move the DOM) and test assertions. The
restyler never re-serialises a page from this tree -- it edits the original
bytes -- so this module cannot itself move markup.
"""

from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser

VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
)

#: Attributes that belong to the page skeleton, not to the copy inside it.
STRUCTURAL_ATTRS = ("class", "data-band", "data-block", "data-repeat", "data-slot")


class Node:
    """One element. ``children`` holds :class:`Node` and ``str`` (text) items."""

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: Node | None = None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Node | str] = []
        self.parent = parent

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    def elements(self) -> list[Node]:
        return [c for c in self.children if isinstance(c, Node)]

    def text(self) -> str:
        """Concatenated descendant text, whitespace-normalised."""
        parts: list[str] = []

        def rec(node: Node) -> None:
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                else:
                    rec(child)

        rec(self)
        return " ".join(" ".join(parts).split())

    def find_all(self, tag: str | None = None, **attr_match: str) -> list[Node]:
        found: list[Node] = []

        def rec(node: Node) -> None:
            for child in node.elements():
                if (tag is None or child.tag == tag) and all(
                    child.get(k) == v for k, v in attr_match.items()
                ):
                    found.append(child)
                rec(child)

        rec(self)
        return found

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Node {self.tag} {self.attrs}>"


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: (v or "") for k, v in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: (v or "") for k, v in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def parse(html: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def element_count(root: Node) -> int:
    return sum(1 for _ in iter_elements(root))


def iter_elements(root: Node):
    for child in root.children:
        if isinstance(child, Node):
            yield child
            yield from iter_elements(child)


def band_list(root: Node) -> list[dict[str, str]]:
    """Ordered list of every element carrying ``data-band``."""
    bands = []
    for node in iter_elements(root):
        if node.get("data-band"):
            bands.append({"band": node.get("data-band"), "block": node.get("data-block")})
    return bands


def repeat_counts(root: Node) -> dict[str, int]:
    """``{data-repeat value: number of direct child elements}``."""
    counts: dict[str, int] = {}
    for node in iter_elements(root):
        key = node.get("data-repeat")
        if key:
            counts[key] = len(node.elements())
    return counts


def slot_keys(root: Node) -> list[str]:
    """Every ``data-slot`` value in document order."""
    return [n.get("data-slot") for n in iter_elements(root) if n.get("data-slot")]


def structure_signature(root: Node) -> list[list[object]]:
    """Deterministic structural fingerprint of the page.

    Tags, their structural attributes, nesting depth and sibling index -- and
    nothing else. Text nodes are deliberately excluded: a restyle is allowed to
    change copy, but may not add, remove or reorder elements.
    """
    out: list[list[object]] = []

    def rec(node: Node, depth: int) -> None:
        for index, child in enumerate(node.children):
            if isinstance(child, Node):
                out.append(
                    [
                        child.tag,
                        *(child.get(attr) for attr in STRUCTURAL_ATTRS),
                        depth,
                        index,
                    ]
                )
                rec(child, depth + 1)

    rec(root, 0)
    return out


def signature_hash(root: Node) -> str:
    blob = json.dumps(structure_signature(root), separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()
