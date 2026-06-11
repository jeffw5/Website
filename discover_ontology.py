#!/usr/bin/env python3
"""
discover_ontology.py — GraphDB Schema Discovery
The Value Enablement Group, LLC

Queries GraphDB to discover:
1. All named graphs (ontologies loaded)
2. All classes in the core domain ontology
3. Class hierarchy and relationships
4. Top-level taxonomy terms

Usage:
    python3 discover_ontology.py

Setup:
    Requires .env with GRAPHDB_ENDPOINT set
    Cloudflare tunnel must be running
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

GRAPHDB_ENDPOINT = os.getenv("GRAPHDB_ENDPOINT")

def sparql_query(query: str) -> list:
    """Run a SPARQL SELECT query and return rows as list of dicts."""
    try:
        r = requests.get(
            GRAPHDB_ENDPOINT,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            timeout=30
        )
        if r.status_code != 200:
            print(f"  ⚠ SPARQL error {r.status_code}: {r.text[:200]}")
            return []
        data = r.json()
        bindings = data.get("results", {}).get("bindings", [])
        return [
            {k: v.get("value", "") for k, v in row.items()}
            for row in bindings
        ]
    except Exception as e:
        print(f"  ⚠ Query error: {e}")
        return []


def discover():
    print("=" * 60)
    print("  GraphDB Schema Discovery")
    print(f"  Endpoint: {GRAPHDB_ENDPOINT}")
    print("=" * 60)

    # ── 1. Named graphs (loaded ontologies) ──
    print("\n## Named Graphs (Loaded Ontologies)\n")
    graphs = sparql_query("""
        SELECT DISTINCT ?graph (COUNT(?s) AS ?triples)
        WHERE { GRAPH ?graph { ?s ?p ?o } }
        GROUP BY ?graph
        ORDER BY DESC(?triples)
        LIMIT 30
    """)
    if graphs:
        for g in graphs:
            print(f"  {g.get('graph','?')}  ({g.get('triples','?')} triples)")
    else:
        print("  No named graphs found — trying default graph")

    # ── 2. Total triples ──
    print("\n## Triple Count\n")
    count = sparql_query("SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }")
    if count:
        print(f"  Total triples: {count[0].get('count','?')}")

    # ── 3. All ontologies declared ──
    print("\n## Declared Ontologies\n")
    ontologies = sparql_query("""
        SELECT DISTINCT ?ontology ?label
        WHERE {
            ?ontology a <http://www.w3.org/2002/07/owl#Ontology> .
            OPTIONAL { ?ontology <http://www.w3.org/2000/01/rdf-schema#label> ?label }
        }
        LIMIT 30
    """)
    for o in ontologies:
        print(f"  {o.get('ontology','?')}  {o.get('label','')}")

    # ── 4. All classes ──
    print("\n## OWL Classes (top 50)\n")
    classes = sparql_query("""
        SELECT DISTINCT ?class ?label
        WHERE {
            ?class a <http://www.w3.org/2002/07/owl#Class> .
            OPTIONAL { ?class <http://www.w3.org/2000/01/rdf-schema#label> ?label }
            FILTER(!isBlank(?class))
        }
        ORDER BY ?label
        LIMIT 50
    """)
    for c in classes:
        uri = c.get('class','?')
        label = c.get('label','')
        print(f"  {label or uri.split('#')[-1].split('/')[-1]}  <{uri}>")

    # ── 5. Class hierarchy ──
    print("\n## Class Hierarchy (subClassOf, top 30)\n")
    hierarchy = sparql_query("""
        SELECT DISTINCT ?child ?childLabel ?parent ?parentLabel
        WHERE {
            ?child <http://www.w3.org/2000/01/rdf-schema#subClassOf> ?parent .
            OPTIONAL { ?child <http://www.w3.org/2000/01/rdf-schema#label> ?childLabel }
            OPTIONAL { ?parent <http://www.w3.org/2000/01/rdf-schema#label> ?parentLabel }
            FILTER(!isBlank(?child) && !isBlank(?parent))
        }
        LIMIT 30
    """)
    for h in hierarchy:
        child  = h.get('childLabel')  or h.get('child','?').split('#')[-1]
        parent = h.get('parentLabel') or h.get('parent','?').split('#')[-1]
        print(f"  {child} → subClassOf → {parent}")

    # ── 6. Object properties ──
    print("\n## Object Properties (top 30)\n")
    props = sparql_query("""
        SELECT DISTINCT ?prop ?label ?domain ?range
        WHERE {
            ?prop a <http://www.w3.org/2002/07/owl#ObjectProperty> .
            OPTIONAL { ?prop <http://www.w3.org/2000/01/rdf-schema#label> ?label }
            OPTIONAL { ?prop <http://www.w3.org/2000/01/rdf-schema#domain> ?domain }
            OPTIONAL { ?prop <http://www.w3.org/2000/01/rdf-schema#range> ?range }
        }
        LIMIT 30
    """)
    for p in props:
        name   = p.get('label') or p.get('prop','?').split('#')[-1]
        domain = p.get('domain','?').split('#')[-1] if p.get('domain') else '?'
        range_ = p.get('range','?').split('#')[-1] if p.get('range') else '?'
        print(f"  {name}  ({domain} → {range_})")

    # ── 7. SKOS concepts (taxonomies) ──
    print("\n## SKOS Concepts / Taxonomy Terms (top 30)\n")
    concepts = sparql_query("""
        SELECT DISTINCT ?concept ?label ?broader
        WHERE {
            ?concept a <http://www.w3.org/2004/02/skos/core#Concept> .
            OPTIONAL { ?concept <http://www.w3.org/2004/02/skos/core#prefLabel> ?label }
            OPTIONAL { ?concept <http://www.w3.org/2004/02/skos/core#broader> ?broader }
        }
        LIMIT 30
    """)
    for c in concepts:
        label   = c.get('label','?')
        broader = c.get('broader','').split('#')[-1].split('/')[-1] if c.get('broader') else ''
        print(f"  {label}  {'← ' + broader if broader else ''}")

    # ── 8. Sample instances ──
    print("\n## Sample Instances (top 20)\n")
    instances = sparql_query("""
        SELECT DISTINCT ?instance ?type ?label
        WHERE {
            ?instance a ?type .
            OPTIONAL { ?instance <http://www.w3.org/2000/01/rdf-schema#label> ?label }
            FILTER(!isBlank(?instance))
            FILTER(?type != <http://www.w3.org/2002/07/owl#Class>)
            FILTER(?type != <http://www.w3.org/2002/07/owl#ObjectProperty>)
            FILTER(?type != <http://www.w3.org/2002/07/owl#Ontology>)
        }
        LIMIT 20
    """)
    for i in instances:
        label = i.get('label') or i.get('instance','?').split('#')[-1]
        type_ = i.get('type','?').split('#')[-1]
        print(f"  {label}  [{type_}]")

    print("\n" + "=" * 60)
    print("  Discovery complete")
    print("=" * 60)


if __name__ == "__main__":
    if not GRAPHDB_ENDPOINT:
        print("❌ GRAPHDB_ENDPOINT not set in .env")
    else:
        discover()
