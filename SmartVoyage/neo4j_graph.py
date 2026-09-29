from __future__ import annotations

import os

from SmartVoyage.multimodal import GraphFact, StaticGraphLookup
from SmartVoyage.travel_knowledge import LANDMARK_ALIASES, TRAVEL_PROFILES


class Neo4jGraphLookup:
    backend = "neo4j"

    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._driver.verify_connectivity()

    def facts_for(self, landmark: str) -> list[GraphFact]:
        query = """
        MATCH (l:Landmark {name: $name})
        CALL (l) {
          MATCH (c:City)-[:CONTAINS]->(l) RETURN c.name AS subject, '包含' AS relation, l.name AS object
          UNION ALL
          MATCH (l)-[:NEARBY]->(p:Place) RETURN l.name AS subject, '附近' AS relation, p.name AS object
          UNION ALL
          MATCH (t:Transport)-[:REACHES]->(l) RETURN t.name AS subject, '可到达' AS relation, l.name AS object
          UNION ALL
          RETURN l.name AS subject, '特色' AS relation, l.feature AS object
        }
        RETURN subject, relation, object
        """
        with self._driver.session() as session:
            records = session.run(query, name=landmark)
            return [GraphFact(**record.data()) for record in records]

    def stats(self) -> dict[str, int | str]:
        with self._driver.session() as session:
            row = session.run(
                "MATCH (c:City) WITH count(c) AS cities MATCH (l:Landmark) RETURN cities, count(l) AS landmarks"
            ).single()
            return {"backend": self.backend, "cities": row["cities"], "landmarks": row["landmarks"]}

    def seed(self) -> None:
        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT city_name IF NOT EXISTS FOR (n:City) REQUIRE n.name IS UNIQUE")
            session.run("CREATE CONSTRAINT landmark_name IF NOT EXISTS FOR (n:Landmark) REQUIRE n.name IS UNIQUE")
            session.run("CREATE CONSTRAINT place_name IF NOT EXISTS FOR (n:Place) REQUIRE n.name IS UNIQUE")
            session.run("CREATE CONSTRAINT transport_name IF NOT EXISTS FOR (n:Transport) REQUIRE n.name IS UNIQUE")
            session.run("CREATE CONSTRAINT alias_name IF NOT EXISTS FOR (n:Alias) REQUIRE n.name IS UNIQUE")
            for name, profile in TRAVEL_PROFILES.items():
                session.run(
                    """
                    MERGE (c:City {name: $city})
                    MERGE (l:Landmark {name: $name}) SET l.feature = $feature
                    MERGE (p:Place {name: $nearby})
                    MERGE (t:Transport {name: $transport})
                    MERGE (c)-[:CONTAINS]->(l)
                    MERGE (l)-[:NEARBY]->(p)
                    MERGE (t)-[:REACHES]->(l)
                    """,
                    city=profile["city"], name=name, feature=profile["feature"],
                    nearby=profile["nearby"], transport=profile["transport"],
                )
            for alias, canonical in LANDMARK_ALIASES.items():
                session.run(
                    "MERGE (a:Alias {name: $alias}) WITH a MATCH (l:Landmark {name: $canonical}) MERGE (a)-[:REFERS_TO]->(l)",
                    alias=alias, canonical=canonical,
                )


def build_graph_lookup():
    uri = os.getenv("NEO4J_URI", "")
    password = os.getenv("NEO4J_PASSWORD", "")
    if not uri or not password:
        return StaticGraphLookup()
    try:
        return Neo4jGraphLookup(uri, os.getenv("NEO4J_USER", "neo4j"), password)
    except Exception:
        return StaticGraphLookup()
