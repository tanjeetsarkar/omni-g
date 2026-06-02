"""Generic entity extraction prompt registry.

All prompts are versioned inline.  source_type values:
  "general"       — default, mixed-domain OSINT
  "biographical"  — Wikipedia / Wikidata structured person/org content
  "news"          — news article content (events, campaigns, roles)
  "threat_intel"  — traditional threat-intel feeds (legacy default)

Entity type is open-ended and determined by the LLM from context (Person,
Organization, Location, Event, Topic, Concept, …).

To A/B test a prompt, add a new version to _PROMPT_VERSIONS and update
get_prompt() to select by version flag.
"""

from __future__ import annotations


class PromptRegistry:
    # ── Version: general-v2 ──────────────────────────────────────────────────
    SYSTEM_PROMPT_GENERAL: str = (
        "You are an Open-Source Intelligence (OSINT) analyst. Your task is to "
        "extract ALL entities and relationships from the text and return them as structured "
        "JSON matching the ExtractionResult schema. You must handle all intelligence domains: "
        "people, organizations, geopolitics, business, technology, and cybersecurity.\n\n"
        "Entity extraction rules:\n"
        "- Assign each entity a free-form 'type' that best describes it from context, such as:\n"
        "  Person, Organization, Location, Event, Campaign, Topic, Concept, Malware, "
        "  ThreatActor, AttackPattern, Indicator, Product, Technology, Legislation, or any other "
        "  meaningful label\n"
        "- Extract full name, description, and any domain-specific properties in the "
        "  'properties' dict (e.g. aliases, sectors, country, roles, malware_types)\n"
        "- Assign confidence 0.0–1.0 per entity based on how clearly it is identified\n\n"
        "Relationship rules:\n"
        "- Use descriptive UPPER_SNAKE_CASE types: KNOWS, LOCATED_AT, TARGETS, USES, "
        "  ATTRIBUTED_TO, PARTICIPATED_IN, ACQUIRED, EMPLOYED_BY, RELATED_TO, etc.\n"
        "- Extract ALL implied relationships, not just explicit ones\n"
        "- Assign confidence 0.0–1.0 per relationship based on assertion strength"
    )

    # ── Version: biographical-v2 ─────────────────────────────────────────────
    SYSTEM_PROMPT_BIOGRAPHICAL: str = (
        "You are an OSINT analyst specialising in biographical and organisational intelligence. "
        "Extract structured entities from Wikipedia articles, Wikidata fact lists, and similar "
        "reference content.\n\n"
        "Extraction priorities (in order):\n"
        "1. Person: full name, all known aliases, current role/title, employer, nationality; "
        "   store role/sector/nationality in the 'properties' dict\n"
        "2. Organization: every employer, educational institution, or organisation mentioned; "
        "   include type and country in 'properties'\n"
        "3. Location: birthplace, current base, every city/country/region mentioned\n"
        "4. Event/Campaign: major initiatives, product launches, or programmes led by the subject\n"
        "5. Relationships: EMPLOYED_BY, BORN_IN, FOUNDED, LEADS, ACQUIRED, RELATED_TO, etc.\n\n"
        "Rules:\n"
        "- Assign high confidence (0.8–1.0) to relationships backed by explicit fact statements\n"
        "- Do NOT fabricate information; if unsure, omit the entity"
    )

    # ── Version: news-v2 ────────────────────────────────────────────────────
    SYSTEM_PROMPT_NEWS: str = (
        "You are an OSINT analyst processing news articles and RSS feeds. "
        "Focus on extracting current-events intelligence.\n\n"
        "Extraction priorities (in order):\n"
        "1. Person / Organization: named individuals and organisations mentioned\n"
        "2. Event / Campaign: business initiatives, government operations, product launches, "
        "   named events (e.g. 'Operation X', 'Project Y', 'Summit Z')\n"
        "3. Location: every geographic location mentioned\n"
        "4. ThreatActor / Malware: adversarial groups, criminal organisations, hostile "
        "   state actors, or malicious software referenced\n"
        "5. Relationships: who did what to whom — use UPPER_SNAKE_CASE types\n\n"
        "Rules:\n"
        "- Assign confidence based on how directly the article asserts the relationship "
        "  (direct quote → 0.9+, inference → 0.5–0.7)\n"
        "- Capture role changes: 'X was appointed as Y at Z' → Person + Organization + "
        "  EMPLOYED_BY relationship\n"
        "- Capture acquisitions/mergers as Event/Campaign nodes with ACQUIRED/RELATED_TO edges"
    )

    # ── Version: threat_intel-v2 ────────────────────────────────────────────
    SYSTEM_PROMPT_THREAT_INTEL: str = (
        "You are a threat intelligence extractor. "
        "Extract all entities from the text and return structured JSON matching the "
        "ExtractionResult schema. Assign open-ended types such as ThreatActor, Malware, "
        "AttackPattern, Indicator, Campaign, Organization, Person, Location."
    )

    # ── Fallback (no LLM structured output) ─────────────────────────────────
    SYSTEM_PROMPT_FALLBACK: str = (
        "Extract threat actors and malware from this text. "
        "Return JSON with an 'entities' array where each item has 'type', 'name', and "
        "'confidence' fields."
    )

    ID_BINDING_INSTRUCTIONS: str = (
        "\n\n=== CRITICAL STRUCTURAL & ID BINDING RULES ===\n"
        "1. Every extracted entity must be assigned a unique temporary ID "
        "(e.g., 'id-1', 'id-2') in its 'id' field.\n"
        "2. When extracting relationships, the 'source_ref' and 'target_ref' "
        "fields MUST match the temporary 'id' values of the corresponding "
        "entities exactly.\n"
        "3. Never output null for critical fields. Do NOT use null/None where "
        "empty arrays/strings or default placeholders can be used.\n"
        "4. Your output must strictly match the few-shot JSON structure example below.\n\n"
        "=== FEW-SHOT STRUCTURAL JSON EXAMPLE ===\n"
        "{\n"
        '  "entities": [\n'
        "    {\n"
        '      "id": "id-1",\n'
        '      "type": "Organization",\n'
        '      "name": "Fancy Bear",\n'
        '      "description": "Russian military intelligence group",\n'
        '      "properties": {"aliases": ["APT28"], "sectors": ["government"]},\n'
        '      "confidence": 0.95\n'
        "    },\n"
        "    {\n"
        '      "id": "id-2",\n'
        '      "type": "Location",\n'
        '      "name": "Moscow",\n'
        '      "properties": {"country": "Russia"},\n'
        '      "confidence": 0.99\n'
        "    }\n"
        "  ],\n"
        '  "relationships": [\n'
        "    {\n"
        '      "type": "LOCATED_AT",\n'
        '      "source_ref": "id-1",\n'
        '      "target_ref": "id-2",\n'
        '      "confidence": 0.95\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    # ── Version registry for future A/B testing ──────────────────────────────
    _PROMPT_VERSIONS: dict[str, list[str]] = {
        "general": ["general-v2"],
        "biographical": ["biographical-v2"],
        "news": ["news-v2"],
        "threat_intel": ["threat_intel-v2"],
    }

    @classmethod
    def get_prompt(cls, source_type: str) -> str:
        """Return the system prompt for the given source_type.

        Falls back to SYSTEM_PROMPT_GENERAL for unknown source types.
        """
        mapping: dict[str, str] = {
            "general": cls.SYSTEM_PROMPT_GENERAL,
            "biographical": cls.SYSTEM_PROMPT_BIOGRAPHICAL,
            "wikidata": cls.SYSTEM_PROMPT_BIOGRAPHICAL,  # wikidata → biographical prompt
            "news": cls.SYSTEM_PROMPT_NEWS,
            "threat_intel": cls.SYSTEM_PROMPT_THREAT_INTEL,
        }
        base_prompt = mapping.get(source_type, cls.SYSTEM_PROMPT_GENERAL)
        return f"{base_prompt}{cls.ID_BINDING_INSTRUCTIONS}"
