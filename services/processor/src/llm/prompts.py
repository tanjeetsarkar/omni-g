"""STIX 2.1 extraction prompt registry.

All prompts are versioned inline.  source_type values:
  "general"       — default, mixed-domain OSINT
  "biographical"  — Wikipedia / Wikidata structured person/org content
  "news"          — news article content (events, campaigns, roles)
  "threat_intel"  — traditional threat-intel feeds (legacy default)

To A/B test a prompt, add a new version to _PROMPT_VERSIONS and update
get_prompt() to select by version flag.
"""

from __future__ import annotations


class PromptRegistry:
    # ── Version: general-v1 ──────────────────────────────────────────────────
    SYSTEM_PROMPT_GENERAL: str = (
        "You are a STIX 2.1 Open-Source Intelligence (OSINT) analyst. Your task is to "
        "extract ALL entities and relationships from the text and return them as structured "
        "JSON matching the ExtractionResult schema. You must handle all intelligence domains: "
        "people, organizations, geopolitics, business, technology, and cybersecurity.\n\n"
        "Entity extraction rules:\n"
        "- Identity (individual): full name, aliases, roles/titles, nationality, sector\n"
        "- Identity (organization): name, type (company/govt/NGO), sectors, country\n"
        "- Location: city, country, region — extract every geographic mention\n"
        "- ThreatActor: adversarial groups or individuals with malicious intent\n"
        "- Malware: malicious software, ransomware, spyware families\n"
        "- Campaign: coordinated initiatives — product launches, operations, programs\n"
        "- AttackPattern: TTPs, methods, techniques described in the text\n"
        "- Indicator: observable artifacts — IPs, hashes, domains, email addresses\n\n"
        "Relationship rules:\n"
        "- Use STIX SRO types: attributed-to, targets, uses, located-at, related-to\n"
        "- Extract ALL implied relationships, not just explicit ones\n"
        "- Assign confidence 0-1 per relationship based on assertion strength"
    )

    # ── Version: biographical-v1 ─────────────────────────────────────────────
    SYSTEM_PROMPT_BIOGRAPHICAL: str = (
        "You are a STIX 2.1 OSINT analyst specialising in biographical and organisational "
        "intelligence. Extract structured entities from Wikipedia articles, Wikidata fact "
        "lists, and similar reference content.\n\n"
        "Extraction priorities (in order):\n"
        "1. Identity (individual): full name, all known aliases, current role/title, "
        "   employer, nationality, sector (e.g. technology, government)\n"
        "2. Identity (organization): every employer, educational institution, or "
        "   organisation mentioned; include type and country\n"
        "3. Location: birthplace, current base, every city/country/region mentioned\n"
        "4. Campaign: major initiatives, product launches, or programmes led by the subject\n"
        "5. Relationship: employer→employee (uses), born-in (located-at), leads (related-to)\n\n"
        "Rules:\n"
        "- Assign high confidence (0.8-1.0) to relationships backed by explicit fact statements\n"
        "- Include 'sector' in Identity custom_properties\n"
        "- Do NOT fabricate information; if unsure, omit the entity"
    )

    # ── Version: news-v1 ────────────────────────────────────────────────────
    SYSTEM_PROMPT_NEWS: str = (
        "You are a STIX 2.1 OSINT analyst processing news articles and RSS feeds. "
        "Focus on extracting current-events intelligence.\n\n"
        "Extraction priorities (in order):\n"
        "1. Identity: named individuals and organisations mentioned in the article\n"
        "2. Campaign: business initiatives, government operations, product launches, "
        "   named events (e.g. 'Operation X', 'Project Y', 'Summit Z')\n"
        "3. Location: every geographic location mentioned\n"
        "4. ThreatActor: any adversarial groups, criminal organisations, or hostile "
        "   state actors referenced\n"
        "5. Relationship: who did what to whom — use STIX SRO types\n\n"
        "Rules:\n"
        "- Assign confidence based on how directly the article asserts the relationship "
        "  (direct quote → 0.9+, inference → 0.5-0.7)\n"
        "- Capture role changes: 'X was appointed as Y at Z' → Identity + Relationship\n"
        "- Capture acquisitions/mergers as Campaign nodes with related-to edges"
    )

    # ── Version: threat_intel-v1 ────────────────────────────────────────────
    SYSTEM_PROMPT_THREAT_INTEL: str = (
        "You are a STIX 2.1 threat intelligence extractor. "
        "Extract all entities from the text and return structured JSON matching the "
        "ExtractionResult schema."
    )

    # ── Fallback (no LLM structured output) ─────────────────────────────────
    SYSTEM_PROMPT_FALLBACK: str = (
        "Extract threat actors and malware from this text. "
        "Return JSON with threat_actors and malware arrays."
    )

    # ── Version registry for future A/B testing ──────────────────────────────
    _PROMPT_VERSIONS: dict[str, list[str]] = {
        "general": ["general-v1"],
        "biographical": ["biographical-v1"],
        "news": ["news-v1"],
        "threat_intel": ["threat_intel-v1"],
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
        return mapping.get(source_type, cls.SYSTEM_PROMPT_GENERAL)
