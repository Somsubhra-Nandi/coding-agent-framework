"""
walker.py — Orchestrator. Walks a repo, calls parser then graph per file.
No parsing logic. No Cypher.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ingestion.parser import parse_java_file
from ingestion.graph import get_driver, push_to_neo4j, ensure_fulltext_index

log = logging.getLogger(__name__)


@dataclass
class WalkSummary:
    total_files: int = 0
    success_files: int = 0
    failed_files: int = 0
    total_classes: int = 0
    total_methods: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def walk_repository(repo_root: str) -> WalkSummary:
    """
    Recursively find all .java files under repo_root,
    parse each, and push to Neo4j.
    Never crashes on individual file failures.
    """
    root = Path(repo_root)
    if not root.exists():
        raise FileNotFoundError(f"Repository root not found: {repo_root}")

    java_files = list(root.rglob("*.java"))
    log.info("Found %d .java files under %s", len(java_files), repo_root)

    driver = get_driver()
    ensure_fulltext_index(driver)

    summary = WalkSummary(total_files=len(java_files))

    for java_file in java_files:
        file_str = str(java_file)
        try:
            class_data = parse_java_file(file_str)
            push_to_neo4j(class_data, driver=driver)
            summary.success_files += 1
            summary.total_classes += 1
            summary.total_methods += len(class_data.methods)
            log.info("✓ %s  [class=%s, methods=%d]",
                     java_file.name, class_data.name, len(class_data.methods))
        except Exception as exc:
            summary.failed_files += 1
            summary.errors.append((file_str, str(exc)))
            log.error("✗ %s — %s", java_file.name, exc)

    return summary