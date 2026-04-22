"""
main.py — CLI entry point.
Usage: python main.py <repo_path>
"""
from __future__ import annotations

import argparse
import logging
import sys
from dotenv import load_dotenv
from ingestion.walker import walk_repository

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("amrit-graphrag")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AMRIT GraphRAG — ingest a Java Spring Boot repo into Neo4j"
    )
    parser.add_argument(
        "repo_path",
        help="Path to the root of the Java repository to ingest",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug-level logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("Starting ingestion for: %s", args.repo_path)

    try:
        summary = walk_repository(args.repo_path)
    except FileNotFoundError as e:
        log.error("%s", e)
        sys.exit(1)
    except RuntimeError as e:
        log.error("Neo4j error: %s", e)
        sys.exit(1)

    print("\n" + "═" * 50)
    print("  AMRIT GraphRAG — Ingestion Summary")
    print("═" * 50)
    print(f"  Total .java files found : {summary.total_files}")
    print(f"  Successfully processed  : {summary.success_files}")
    print(f"  Failed / skipped        : {summary.failed_files}")
    print(f"  Classes indexed         : {summary.total_classes}")
    print(f"  Methods indexed         : {summary.total_methods}")

    if summary.errors:
        print(f"\n  Errors ({len(summary.errors)}):")
        for path, msg in summary.errors:
            print(f"    • {path}: {msg}")

    print("═" * 50 + "\n")

    if summary.failed_files:
        sys.exit(1)


if __name__ == "__main__":
    main()