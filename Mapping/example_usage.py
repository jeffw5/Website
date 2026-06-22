"""
example_usage.py
================
Two ways to drive the pipeline. Set ANTHROPIC_API_KEY, VOYAGE_API_KEY, and
PINECONE_API_KEY in your environment first.

    python example_usage.py
"""

import logging

from avatar2 import AvatarPipeline, Config, Document

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

DOCS = [
    Document(
        title="RDSG v2.0 Overview",
        text=(
            "The Requirements-Driven Semantic Gateway (RDSG) integrates STPA/STAMP "
            "hazard analysis with a Simplex Action Gateway. Unsafe Control Actions "
            "are covered across four modes. SHACL and SWRL enforce governance over "
            "the knowledge graph, and INCOSE RM provides four-level traceability.\n\n"
            "In practice, every requirement is traced from stakeholder need down to "
            "verification, so that a hazard discovered in operation can be linked "
            "back to the originating requirement and its governing constraints."
        ),
        source_path="docs/rdsg_v2.md",
    ),
    Document(
        title="AI Circuit Breaker Concept Note",
        text=(
            "The AI Circuit Breaker (AICB) interrupts unsafe model behavior before "
            "it propagates. Its core metric is Mean Time Between Hazards (MTBH). "
            "AICB extends the Simplex Action Gateway idea from RDSG into runtime "
            "AI governance, giving operators a deterministic fallback path."
        ),
        source_path="docs/aicb.md",
    ),
]


def full_run():
    # Production: ontology loaded live from value-kb and used to ground every stage.
    cfg = Config(
        ontology_source="graphdb",
        graphdb_base_url="http://localhost:7200",   # or your CORS proxy
        graphdb_repository="value-kb",
        # graphdb_named_graph="https://enablingvalue.com/graphs/frameworks",
    )
    pipe = AvatarPipeline(cfg)
    result = pipe.run(DOCS, namespace="avatar-2-0")
    print("STATS:", result.stats)
    if result.mining:
        for chain in result.mining.provenance_chains[:5]:
            print(f"  [{chain.framework_label}] <- {chain.claim_text[:80]}...")


def stage_by_stage():
    """Run stages individually to inspect intermediate state.

    Uses the JSON seed so it works offline without GraphDB; switch
    ontology_source to "graphdb" to ground against value-kb.
    """
    cfg = Config(ontology_source="json")
    pipe = AvatarPipeline(cfg)

    extractions = pipe.extraction.process_corpus(DOCS)
    mining = pipe.mining.process(extractions)
    pipe.enrichment.process(extractions)

    for ex in extractions:
        print(f"\n# {ex.title}")
        for ch in ex.chunks:
            enr = ch.enrichment
            fws = ", ".join(fl.framework_label for fl in ch.framework_links) or "-"
            print(f"  chunk {ch.sequence} [{enr.audience_level if enr else '?'}] frameworks: {fws}")
    print("\nCross-doc links:", len(mining.cross_document_links))
    # pipe.embedding.process(extractions, namespace="avatar-2-0")  # uncomment to upsert


if __name__ == "__main__":
    stage_by_stage()
    # full_run()
