"""
models.py — Pure dataclasses only. Zero logic.
"""
from dataclasses import dataclass, field


@dataclass
class MethodData:
    name: str
    http_method: str | None
    endpoint: str | None
    source_code: str


@dataclass
class ClassData:
    name: str
    file_path: str
    stereotype: str | None
    autowired_deps: list[str] = field(default_factory=list)
    methods: list[MethodData] = field(default_factory=list)