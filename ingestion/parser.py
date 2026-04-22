"""
parser.py — Tree-sitter-based Java parser. No Neo4j imports.
Input: raw Java source string + file path
Output: ClassData
"""
from __future__ import annotations

import re
import logging
from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node

from ingestion.models import ClassData, MethodData

log = logging.getLogger(__name__)

JAVA_LANGUAGE = Language(tsjava.language())

STEREOTYPE_ANNOTATIONS = {
    "RestController", "Controller", "Service",
    "Repository", "Component",
}

HTTP_ANNOTATIONS = {
    "GetMapping", "PostMapping", "PutMapping",
    "DeleteMapping", "RequestMapping",
}


def _build_parser() -> Parser:
    p = Parser(JAVA_LANGUAGE)
    return p


def _node_text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _get_class_name(root: Node, src: bytes) -> str | None:
    for node in root.children:
        if node.type == "class_declaration":
            for child in node.children:
                if child.type == "identifier":
                    return _node_text(child, src)
    return None


def _get_stereotype(root: Node, src: bytes) -> str | None:
    """Extract stereotype from class-level annotations."""
    for node in root.children:
        if node.type == "class_declaration":
            for child in node.children:
                if child.type == "modifiers":
                    for mod in child.children:
                        if mod.type == "marker_annotation" or mod.type == "annotation":
                            name_node = mod.child_by_field_name("name")
                            if name_node:
                                name = _node_text(name_node, src)
                                if name in STEREOTYPE_ANNOTATIONS:
                                    return name
    return None


def _get_autowired_deps(root: Node, src: bytes) -> list[str]:
    """Extract @Autowired field types."""
    deps: list[str] = []
    for class_node in root.children:
        if class_node.type != "class_declaration":
            continue
        body = class_node.child_by_field_name("body")
        if not body:
            continue
        for member in body.children:
            if member.type != "field_declaration":
                continue
            # Check for @Autowired modifier
            has_autowired = False
            for child in member.children:
                if child.type == "modifiers":
                    for mod in child.children:
                        if mod.type in ("marker_annotation", "annotation"):
                            name_node = mod.child_by_field_name("name")
                            if name_node and _node_text(name_node, src) == "Autowired":
                                has_autowired = True
            if has_autowired:
                type_node = member.child_by_field_name("type")
                if type_node:
                    deps.append(_node_text(type_node, src))
    return deps


def _extract_annotation_info(modifiers: Node, src: bytes) -> tuple[str | None, str | None]:
    """Return (http_method, endpoint) from method-level mapping annotations only."""
    for mod in modifiers.children:
        if mod.type not in ("marker_annotation", "annotation"):
            continue
        name_node = mod.child_by_field_name("name")
        if not name_node:
            continue
        name = _node_text(name_node, src)
        if name not in HTTP_ANNOTATIONS:
            continue
            
        endpoint: str | None = None
        args = mod.child_by_field_name("arguments")
        if args:
            # Walk only direct children of the annotation arguments
            for arg in args.children:
                # Matches: @GetMapping("/route")
                if arg.type == "string_literal":
                    endpoint = _node_text(arg, src).strip('"')
                    break
                
                # Matches: @GetMapping(value = "/route", headers = "...")
                elif arg.type == "element_value_pair":
                    key_node = arg.child_by_field_name("key")
                    if key_node:
                        key_name = _node_text(key_node, src)
                        # ONLY grab the string if the key is 'value' or 'path'
                        if key_name in ("value", "path"):
                            val_node = arg.child_by_field_name("value")
                            if val_node and val_node.type == "string_literal":
                                endpoint = _node_text(val_node, src).strip('"')
                                break
                                
        return name, endpoint
    return None, None


def _get_methods(root: Node, src: bytes) -> list[MethodData]:
    methods: list[MethodData] = []
    for class_node in root.children:
        if class_node.type != "class_declaration":
            continue
        body = class_node.child_by_field_name("body")
        if not body:
            continue
        for member in body.children:
            if member.type != "method_declaration":
                continue
            name_node = member.child_by_field_name("name")
            if not name_node:
                continue
            method_name = _node_text(name_node, src)
            http_method: str | None = None
            endpoint: str | None = None

            # Only look at modifiers node, NOT method parameters
            for child in member.children:
                if child.type == "modifiers":
                    http_method, endpoint = _extract_annotation_info(child, src)
                    break  # stop after modifiers, never touch parameters

            source_code = _node_text(member, src)
            methods.append(MethodData(
                name=method_name,
                http_method=http_method,
                endpoint=endpoint,
                source_code=source_code,
            ))
    return methods


def parse_java_source(source: str, file_path: str) -> ClassData:
    """Parse a Java source string and return ClassData."""
    parser = _build_parser()
    src_bytes = source.encode("utf-8")
    tree = parser.parse(src_bytes)
    root = tree.root_node

    class_name = _get_class_name(root, src_bytes) or Path(file_path).stem
    stereotype = _get_stereotype(root, src_bytes)
    autowired_deps = _get_autowired_deps(root, src_bytes)
    methods = _get_methods(root, src_bytes)

    return ClassData(
        name=class_name,
        file_path=file_path,
        stereotype=stereotype,
        autowired_deps=autowired_deps,
        methods=methods,
    )


def parse_java_file(file_path: str) -> ClassData:
    """Read a .java file from disk and return ClassData."""
    source = Path(file_path).read_text(encoding="utf-8", errors="replace")
    return parse_java_source(source, file_path)