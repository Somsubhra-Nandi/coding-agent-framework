"""
graph.py — Neo4j-only module. All writes via MERGE (idempotent).
No tree-sitter imports. No parsing logic.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, AuthError
from dotenv import load_dotenv
load_dotenv()
from ingestion.models import ClassData

log = logging.getLogger(__name__)

_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
_NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        try:
            _driver = GraphDatabase.driver(
                _NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD)
            )
            _driver.verify_connectivity()
            log.info("Connected to Neo4j at %s", _NEO4J_URI)
        except ServiceUnavailable as e:
            raise RuntimeError(
                f"Cannot reach Neo4j at {_NEO4J_URI}. "
                "Is the database running? Check NEO4J_URI env var."
            ) from e
        except AuthError as e:
            raise RuntimeError(
                f"Neo4j authentication failed for user '{_NEO4J_USER}'. "
                "Check NEO4J_USER / NEO4J_PASSWORD env vars."
            ) from e
    return _driver


def ensure_fulltext_index(driver: Driver) -> None:
    """Create fulltext index on Method nodes if not already present."""
    with driver.session() as session:
        try:
            session.run(
                "CREATE FULLTEXT INDEX method_search IF NOT EXISTS "
                "FOR (m:Method) ON EACH [m.source_code, m.name]"
            )
        except Exception as e:
            log.warning("Could not create fulltext index: %s", e)


def push_to_neo4j(class_data: ClassData, driver: Driver | None = None) -> None:
    """Write ClassData into Neo4j using MERGE statements."""
    if driver is None:
        driver = get_driver()

    file_name = Path(class_data.file_path).name

    with driver.session() as session:
        # MERGE File node
        session.run(
            "MERGE (f:File {path: $path}) SET f.name = $name",
            path=class_data.file_path,
            name=file_name,
        )

        # MERGE Class node
        session.run(
            "MERGE (c:Class {name: $name, file_path: $file_path}) "
            "SET c.stereotype = $stereotype",
            name=class_data.name,
            file_path=class_data.file_path,
            stereotype=class_data.stereotype,
        )

        # MERGE File-[:CONTAINS]->Class
        session.run(
            "MATCH (f:File {path: $file_path}) "
            "MATCH (c:Class {name: $class_name, file_path: $file_path}) "
            "MERGE (f)-[:CONTAINS]->(c)",
            file_path=class_data.file_path,
            class_name=class_data.name,
        )

        # MERGE Method nodes + Class-[:DEFINES]->Method
        for method in class_data.methods:
            session.run(
                "MERGE (m:Method {name: $name, class_name: $class_name}) "
                "SET m.http_method = $http_method, "
                "    m.endpoint = $endpoint, "
                "    m.source_code = $source_code",
                name=method.name,
                class_name=class_data.name,
                http_method=method.http_method,
                endpoint=method.endpoint,
                source_code=method.source_code,
            )
            session.run(
                "MATCH (c:Class {name: $class_name, file_path: $file_path}) "
                "MATCH (m:Method {name: $method_name, class_name: $class_name}) "
                "MERGE (c)-[:DEFINES]->(m)",
                class_name=class_data.name,
                file_path=class_data.file_path,
                method_name=method.name,
            )

        # MERGE Class-[:DEPENDS_ON]->Class for @Autowired deps
        for dep in class_data.autowired_deps:
            session.run(
                "MERGE (dep:Class {name: $dep_name}) "
                "WITH dep "
                "MATCH (c:Class {name: $class_name, file_path: $file_path}) "
                "MERGE (c)-[:DEPENDS_ON]->(dep)",
                dep_name=dep,
                class_name=class_data.name,
                file_path=class_data.file_path,
            )

    log.debug("Pushed %s (%d methods) to Neo4j", class_data.name, len(class_data.methods))


def close_driver() -> None:
    global _driver
    if _driver:
        _driver.close()
        _driver = None