"""
graphdb.py
==========
Thin RDF4J SPARQL client for your GraphDB `value-kb` repository. Uses only the
standard library so it adds no dependencies, and talks to whatever endpoint you
point `graphdb_base_url` at — set that to your CORS proxy if you front GraphDB
with one, or directly to GraphDB (e.g. http://localhost:7200).

Named-graph (RDF4J `context`) scoping is honored: when `graphdb_named_graph` is
set, queries run with that graph as the default graph, so the ontology load
respects the same named-graph governance you use elsewhere.

This module deliberately returns plain dicts (no Pydantic), so the transport and
result-parsing logic can be unit-tested without the model layer or a live server.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from .config import Config

logger = logging.getLogger("avatar2.graphdb")


class GraphDBClient:
    def __init__(self, config: Config):
        self.config = config
        config.require("graphdb_base_url", "graphdb_repository")
        self.endpoint = f"{config.graphdb_base_url.rstrip('/')}/repositories/{config.graphdb_repository}"
        self.named_graph: Optional[str] = config.graphdb_named_graph
        self.timeout = config.graphdb_timeout

    # ------------------------------------------------------------------ #
    def query(self, sparql: str) -> List[Dict[str, str]]:
        """Run a SELECT query, return a list of {var: value} dicts."""
        params = {"query": sparql}
        if self.named_graph:
            # scope the default graph to the configured named graph (context)
            params["default-graph-uri"] = self.named_graph
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/sparql-results+json",
            },
            method="POST",
        )
        logger.debug("SPARQL -> %s (graph=%s)", self.endpoint, self.named_graph)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return self.parse_select(payload)

    @staticmethod
    def parse_select(payload: dict) -> List[Dict[str, str]]:
        """Flatten SPARQL 1.1 JSON results into {var: value} rows."""
        rows: List[Dict[str, str]] = []
        for binding in payload.get("results", {}).get("bindings", []):
            rows.append({var: cell.get("value", "") for var, cell in binding.items()})
        return rows
