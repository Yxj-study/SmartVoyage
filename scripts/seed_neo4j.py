from SmartVoyage.neo4j_graph import Neo4jGraphLookup
import os


lookup = Neo4jGraphLookup(
    os.environ["NEO4J_URI"],
    os.getenv("NEO4J_USER", "neo4j"),
    os.environ["NEO4J_PASSWORD"],
)
lookup.seed()
print(lookup.stats())
