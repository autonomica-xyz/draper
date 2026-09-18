"""Idea Lab service — source material envelope validation, enrichment, and business logic."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import httpx
import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from data.models import ContentIdea, SourceMaterial
from data.sqlite_store import SQLiteStore

# ZAI Web Reader MCP endpoint for URL content extraction
ZAI_READER_URL = "https://api.z.ai/api/mcp/web_reader/mcp"
ZAI_READER_TIMEOUT = 30.0  # seconds
ALLOWED_SOURCE_URL_SCHEMES = {"http", "https"}
MAX_SOURCE_URL_LENGTH = 2048

_PATTERNS_MISSING = object()


class IdeaLabService:
    """Wraps SQLiteStore source_material methods with validation, enrichment, and auto-detection.

    Constructor takes a SQLiteStore instance. All mutations go through
    envelope validation before being persisted.  Enrichment (URL fetch,
    key-point extraction, auto-tagging) is optional and best-effort.
    """

    def __init__(self, sqlite_store: SQLiteStore):
        self.store = sqlite_store

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def add_source_material(
        self,
        project_id: str,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        note: Optional[str] = None,
        title: Optional[str] = None,
        source_attribution: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """Validate, auto-detect type, persist, and return the saved record."""
        # --- project_id required ---
        if not project_id:
            raise ValueError("project_id is required")

        # --- at least one content field required ---
        url = _normalize_source_url(url)
        has_url = bool(url and url.strip())
        has_text = bool(text_content and text_content.strip())
        has_note = bool(note and note.strip())
        if not (has_url or has_text or has_note):
            raise ValueError("At least one of url, text_content, or note is required")

        # --- auto-detect material_type ---
        if has_url:
            material_type = "url"
        elif has_text:
            material_type = "text"
        else:
            material_type = "note"

        # --- normalize tags ---
        normalized_tags = _normalize_tags(tags)

        # --- build dataclass ---
        material = SourceMaterial(
            project_id=project_id,
            material_type=material_type,
            title=title or "",
            url=url or "",
            text_content=text_content or "",
            note=note or "",
            source_attribution=source_attribution or "",
            tags=normalized_tags,
            metadata_json=metadata or {},
        )

        # --- persist ---
        self.store.save_source_material_record(material.to_dict())
        return self.store.get_source_material_record(material.material_id) or material.to_dict()

    def get_source_material(self, material_id: str) -> Optional[SourceMaterial]:
        """Retrieve a single source material by ID, or None."""
        record = self.store.get_source_material_record(material_id)
        if record is None:
            return None
        return SourceMaterial.from_dict(record)

    def list_source_material(
        self,
        project_id: str,
        material_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SourceMaterial]:
        """List source materials for a project, optionally filtered by type."""
        records = self.store.list_source_material_records(
            project_id=project_id,
            material_type=material_type,
            limit=limit,
        )
        return [SourceMaterial.from_dict(r) for r in records]

    def update_source_material(self, material_id: str, **kwargs) -> Dict:
        """Merge *kwargs* into an existing record and persist.

        Raises ValueError if the material_id does not exist.
        """
        existing = self.store.get_source_material_record(material_id)
        if existing is None:
            raise ValueError(f"Source material '{material_id}' not found")
        if "url" in kwargs:
            kwargs["url"] = _normalize_source_url(kwargs.get("url"))

        merged = dict(existing)
        # Auto-detect material_type if url/text_content/note changed
        has_url = bool(
            (kwargs.get("url") if "url" in kwargs else existing.get("url") or "").strip()
        )
        has_text = bool(
            (
                kwargs.get("text_content")
                if "text_content" in kwargs
                else existing.get("text_content") or ""
            ).strip()
        )
        has_note = bool(
            (kwargs.get("note") if "note" in kwargs else existing.get("note") or "").strip()
        )

        if not (has_url or has_text or has_note):
            raise ValueError("At least one of url, text_content, or note is required")

        if has_url:
            merged["material_type"] = "url"
        elif has_text:
            merged["material_type"] = "text"
        else:
            merged["material_type"] = "note"

        allowed_fields = {
            "title",
            "hook_angle",
            "target_platforms",
            "content_pillar",
            "rationale",
            "suggested_format",
            "source_material_ids",
            "tags",
            "metadata_json",
        }
        for key, value in kwargs.items():
            if key not in allowed_fields and key != "status":
                continue
            if key == "tags":
                merged["tags"] = _normalize_tags(value)
            elif key == "metadata_json":
                merged["metadata_json"] = value
            else:
                merged[key] = value

        merged["updated_at"] = datetime.now(timezone.utc).isoformat()

        self.store.save_source_material_record(merged)
        return self.store.get_source_material_record(material_id) or merged

    def delete_source_material(self, material_id: str) -> bool:
        """Delete a source material entry. Returns True if deleted."""
        return self.store.delete_source_material_record(material_id)

    # ------------------------------------------------------------------
    # Source material enrichment
    # ------------------------------------------------------------------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _call_llm_for_enrichment(self, prompt: str, max_tokens: int = 1500) -> str:
        """Call litellm.completion() with the project LLM model and fallback chain.

        Uses the same model/fallback pattern as LLMContentGenerator._call_llm().
        """
        model = os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022")
        fallbacks_str = os.getenv("LLM_FALLBACKS", "")
        fallbacks = [f.strip() for f in fallbacks_str.split(",") if f.strip()] or [
            "gpt-4o",
            "gemini-2.0-flash-exp",
        ]

        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            num_retries=2,
            fallbacks=fallbacks,
        )
        return response.choices[0].message.content

    def _fetch_url_content(self, url: str) -> str:
        """Fetch URL content via the ZAI Web Reader MCP endpoint.

        Sends a JSON-RPC tools/call request to the ZAI Reader.
        Returns the extracted text content, or raises on failure.
        """
        api_key = os.getenv("ZAI_API_KEY", "")
        if not api_key:
            raise ValueError("ZAI_API_KEY not configured — cannot fetch URL content")

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "read_web_page",
                "arguments": {"url": url},
            },
            "id": 1,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        with httpx.Client(timeout=ZAI_READER_TIMEOUT) as client:
            resp = client.post(ZAI_READER_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # JSON-RPC response: result.content is a list of text blocks
        result = data.get("result", {})
        content_blocks = result.get("content", [])
        if isinstance(content_blocks, list):
            parts = []
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            text = "\n".join(parts).strip()
        elif isinstance(result, str):
            text = result.strip()
        else:
            text = str(result).strip()

        if not text:
            raise ValueError(f"ZAI Reader returned empty content for {url}")
        return text

    def _extract_key_points(self, content: str) -> List[str]:
        """Call LLM to extract 3-7 key points from content. Returns a list of strings."""
        prompt = (
            "Extract 3 to 7 key points from the following content. "
            "Return ONLY a JSON array of strings, no other text.\n\n"
            f"Content:\n{content[:6000]}"
        )
        raw = self._call_llm_for_enrichment(prompt, max_tokens=1000)
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            first_newline = raw.index("\n") if "\n" in raw else len(raw)
            raw = raw[first_newline + 1 :]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        try:
            points = json.loads(raw)
            if isinstance(points, list):
                return [str(p) for p in points if p][:7]
        except json.JSONDecodeError:
            pass
        # Fallback: split by newlines, take non-empty lines
        lines = [line.strip().lstrip("-•*0-9. ") for line in raw.split("\n") if line.strip()]
        return [line for line in lines if line][:7]

    def _generate_auto_tags(
        self, content: str, existing_tags: Optional[List[str]] = None
    ) -> List[str]:
        """Call LLM to generate 3-5 relevant tags for the content. Returns a list of tag strings."""
        existing_str = ", ".join(existing_tags) if existing_tags else "(none)"
        prompt = (
            "Generate 3 to 5 concise tags (1-3 words each) that categorize the following content. "
            "Do NOT repeat existing tags. "
            "Return ONLY a JSON array of lowercase tag strings, no other text.\n"
            f"Existing tags: {existing_str}\n\n"
            f"Content:\n{content[:4000]}"
        )
        raw = self._call_llm_for_enrichment(prompt, max_tokens=500)
        raw = raw.strip()
        if raw.startswith("```"):
            first_newline = raw.index("\n") if "\n" in raw else len(raw)
            raw = raw[first_newline + 1 :]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        try:
            tags = json.loads(raw)
            if isinstance(tags, list):
                return [str(t).lower().strip() for t in tags if t][:5]
        except json.JSONDecodeError:
            pass
        lines = [line.strip().lstrip("-•*0-9. ") for line in raw.split("\n") if line.strip()]
        return [line.lower() for line in lines if line][:5]

    def enrich_source_material(self, material_id: str) -> Dict:
        """Orchestrate the full enrichment pipeline for a single source material.

        URL materials: fetch content → extract key points → auto-tag.
        Text materials: extract key points → auto-tag.
        Notes: auto-tag only.

        Idempotent: skips if already enrichment_status == "enriched".
        Updates metadata_json in place and returns the enriched record.
        """
        record = self.store.get_source_material_record(material_id)
        if record is None:
            raise ValueError(f"Source material '{material_id}' not found")

        metadata = dict(record.get("metadata_json", {}) or {})

        # Idempotency: skip if already fully enriched
        if metadata.get("enrichment_status") == "enriched":
            return self.store.get_source_material_record(material_id) or record

        material_type = record.get("material_type", "")
        errors: List[str] = []
        key_points: List[str] = []
        auto_tags: List[str] = []
        fetched_content_length: Optional[int] = None
        content_for_tagging = ""

        # Step 1: URL fetch
        if material_type == "url":
            url = record.get("url", "")
            if url:
                try:
                    fetched_content = self._fetch_url_content(url)
                    fetched_content_length = len(fetched_content)
                    content_for_tagging = fetched_content
                    metadata["fetched_content_length"] = fetched_content_length
                except Exception as e:
                    errors.append(f"URL fetch failed: {e}")

        # Step 2: Key point extraction (URL and text types)
        if material_type in ("url", "text"):
            source_content = content_for_tagging or record.get("text_content", "")
            if not source_content and material_type == "url":
                # URL fetch may have failed — nothing to extract
                if not errors:
                    errors.append("No content available for key point extraction")
            if source_content:
                try:
                    key_points = self._extract_key_points(source_content)
                    metadata["key_points"] = key_points
                except Exception as e:
                    errors.append(f"Key point extraction failed: {e}")

            if not content_for_tagging:
                content_for_tagging = record.get("text_content", "")

        elif material_type == "note":
            content_for_tagging = record.get("note", "")

        # Step 3: Auto-tagging (all types)
        if content_for_tagging:
            try:
                existing_tags = record.get("tags", [])
                auto_tags = self._generate_auto_tags(content_for_tagging, existing_tags)
                metadata["auto_tags"] = auto_tags
            except Exception as e:
                errors.append(f"Auto-tagging failed: {e}")

        # Step 4: Determine status
        has_key_points = bool(key_points)
        has_auto_tags = bool(auto_tags)

        if material_type == "note":
            # Notes only get auto-tags
            if has_auto_tags and not errors:
                metadata["enrichment_status"] = "enriched"
            elif has_auto_tags:
                metadata["enrichment_status"] = "partial"
            else:
                metadata["enrichment_status"] = "failed"
        else:
            # URL and text expect both key_points and auto_tags
            if has_key_points and has_auto_tags and not errors:
                metadata["enrichment_status"] = "enriched"
            elif has_key_points or has_auto_tags:
                metadata["enrichment_status"] = "partial"
            else:
                metadata["enrichment_status"] = "failed"

        if errors:
            metadata["enrichment_error"] = "; ".join(errors)
        else:
            metadata.pop("enrichment_error", None)

        metadata["enriched_at"] = datetime.now(timezone.utc).isoformat()

        # Persist updated metadata
        record_copy = dict(record)
        record_copy["metadata_json"] = metadata
        record_copy["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.store.save_source_material_record(record_copy)

        return self.store.get_source_material_record(material_id) or record_copy

    def enrich_all_pending(self, project_id: str) -> Dict:
        """Batch-enrich all source materials for a project that have not been enriched.

        Returns a summary dict with counts: total, enriched, partial, failed, skipped.
        """
        records = self.store.list_source_material_records(project_id=project_id)
        counts = {"total": 0, "enriched": 0, "partial": 0, "failed": 0, "skipped": 0}

        for rec in records:
            counts["total"] += 1
            meta = rec.get("metadata_json", {}) or {}
            status = meta.get("enrichment_status", "")
            if status == "enriched":
                counts["skipped"] += 1
                continue

            try:
                result = self.enrich_source_material(rec["material_id"])
                result_meta = result.get("metadata_json", {}) or {}
                final_status = result_meta.get("enrichment_status", "failed")
                if final_status == "enriched":
                    counts["enriched"] += 1
                elif final_status == "partial":
                    counts["partial"] += 1
                else:
                    counts["failed"] += 1
            except Exception as e:
                counts["failed"] += 1
                print(f"  Enrichment failed for {rec['material_id']}: {e}")

        return counts

    # ------------------------------------------------------------------
    # Idea generation from enriched material
    # ------------------------------------------------------------------

    def _load_brand_voice(self, project_id: str) -> str:
        """Best-effort load of project brand voice markdown."""
        voice_path = Path(self.store.data_dir) / "projects" / project_id / "brand_voice.md"
        if voice_path.exists():
            return voice_path.read_text(encoding="utf-8")
        return ""

    def _load_learning_patterns(self, project_id: str) -> str:
        """Best-effort load and format of project learning patterns.

        Reads from SQLite project_kv first; falls back to the legacy
        ``data/projects/{id}/learning_patterns.json`` file (transitional,
        emits DeprecationWarning) when the SQLite value is missing.
        """
        sqlite_payload = self.store.get_project_value(
            project_id, "learning_patterns", default=_PATTERNS_MISSING
        )
        if sqlite_payload is _PATTERNS_MISSING:
            patterns_path = (
                Path(self.store.data_dir)
                / "projects"
                / project_id
                / "learning_patterns.json"
            )
            if not patterns_path.exists():
                return ""
            import warnings

            warnings.warn(
                f"learning_patterns reads from {patterns_path.name} - SQLite snapshot missing",
                DeprecationWarning,
                stacklevel=2,
            )
            try:
                data = json.loads(patterns_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return ""
        else:
            data = sqlite_payload

        patterns = data.get("patterns", {}) if isinstance(data, dict) else {}
        effective = []
        avoid = []
        for p in patterns.values():
            if not isinstance(p, dict):
                continue
            ptype = p.get("pattern_type", "")
            pattern_text = p.get("pattern", "")
            score = p.get("effectiveness_score", 0)
            if not pattern_text:
                continue
            if ptype in ("hook_style", "structure", "tone") and score >= 0.5:
                effective.append(f"- {pattern_text}")
            elif "avoid" in ptype or ptype.startswith("negative"):
                avoid.append(f"- {pattern_text}")
        parts = []
        if effective:
            parts.append("Effective patterns:\n" + "\n".join(effective[:10]))
        if avoid:
            parts.append("Patterns to avoid:\n" + "\n".join(avoid[:10]))
        return "\n\n".join(parts)

    def _build_idea_generation_prompt(self, material_record: Dict, project_id: str) -> str:
        """Build the LLM prompt for generating content ideas from enriched material."""
        # Source material content
        text_content = material_record.get("text_content", "") or ""
        note = material_record.get("note", "") or ""
        title = material_record.get("title", "") or ""
        url = material_record.get("url", "") or ""
        metadata = material_record.get("metadata_json", {}) or {}
        key_points = metadata.get("key_points", [])
        auto_tags = metadata.get("auto_tags", [])

        # Brand voice and learning patterns
        brand_voice = self._load_brand_voice(project_id)
        learning_patterns = self._load_learning_patterns(project_id)

        sections = []
        sections.append(
            "Generate 2 to 5 content ideas from the following source material.\n"
            "Return ONLY a JSON array of objects. Each object must have these keys:\n"
            '- "title": a compelling content title (string)\n'
            '- "hook_angle": the attention-grabbing angle or opening hook (string)\n'
            '- "target_platforms": array of platforms like ["twitter", "linkedin"] (array of strings)\n'
            '- "content_pillar": the strategic content pillar, e.g. "thought-leadership", "educational", "growth" (string)\n'
            '- "rationale": why this idea works for the audience (string)\n'
            '- "suggested_format": e.g. "thread", "single-post", "carousel", "long-form" (string)\n'
        )

        if brand_voice:
            sections.append(f"Brand voice:\n{brand_voice[:2000]}")

        if learning_patterns:
            sections.append(f"Learning patterns from past content:\n{learning_patterns[:1500]}")

        source_parts = []
        if title:
            source_parts.append(f"Title: {title}")
        if url:
            source_parts.append(f"URL: {url}")
        if text_content:
            source_parts.append(f"Content:\n{text_content[:4000]}")
        if note:
            source_parts.append(f"Note: {note[:2000]}")
        if key_points:
            source_parts.append("Key points:\n" + "\n".join(f"- {p}" for p in key_points[:7]))
        if auto_tags:
            source_parts.append(f"Tags: {', '.join(auto_tags)}")

        sections.append("Source material:\n" + "\n\n".join(source_parts))

        return "\n\n".join(sections)

    def generate_ideas_from_material(self, material_id: str, project_id: str) -> Dict:
        """Generate 2-5 content ideas from an enriched source material.

        Returns {"ideas": [...], "count": N}.
        Raises ValueError if material not found or not enriched.
        """
        record = self.store.get_source_material_record(material_id)
        if record is None:
            raise ValueError(f"Source material '{material_id}' not found")

        metadata = record.get("metadata_json", {}) or {}
        if metadata.get("enrichment_status") != "enriched":
            raise ValueError(
                f"Source material '{material_id}' is not enriched "
                f"(status: {metadata.get('enrichment_status', 'none')}). "
                "Enrich it first before generating ideas."
            )

        # Check idempotency: skip if ideas already generated for this material
        existing_ideas = self.store.list_content_idea_records(project_id=project_id)
        for idea in existing_ideas:
            sm_ids = idea.get("source_material_ids", [])
            if material_id in sm_ids:
                idea_meta = idea.get("metadata_json", {}) or {}
                if idea_meta.get("generation_status") == "generated":
                    already = [
                        i
                        for i in existing_ideas
                        if material_id in i.get("source_material_ids", [])
                        and i.get("metadata_json", {}).get("generation_status") == "generated"
                    ]
                    return {
                        "ideas": already,
                        "count": len(already),
                        "skipped": True,
                        "reason": "Ideas already generated for this material",
                    }

        prompt = self._build_idea_generation_prompt(record, project_id)

        try:
            raw = self._call_llm_for_enrichment(prompt, max_tokens=2000)
        except Exception as e:
            return {
                "ideas": [],
                "count": 0,
                "error": f"LLM call failed: {e}",
            }

        # Strip markdown code fences
        raw = raw.strip()
        if raw.startswith("```"):
            first_newline = raw.index("\n") if "\n" in raw else len(raw)
            raw = raw[first_newline + 1 :]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        # Parse JSON array
        try:
            ideas_data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to find JSON array in the response
            start = raw.find("[")
            end = raw.rfind("]")
            if start >= 0 and end > start:
                try:
                    ideas_data = json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    return {
                        "ideas": [],
                        "count": 0,
                        "error": "Failed to parse LLM response as JSON",
                    }
            else:
                return {"ideas": [], "count": 0, "error": "Failed to parse LLM response as JSON"}

        if not isinstance(ideas_data, list):
            return {"ideas": [], "count": 0, "error": "LLM response is not a JSON array"}

        # Create ContentIdea records
        created = []
        now = datetime.now(timezone.utc).isoformat()
        for idea_obj in ideas_data[:5]:
            if not isinstance(idea_obj, dict) or not idea_obj.get("title"):
                continue
            try:
                idea = self.add_content_idea(
                    project_id=project_id,
                    title=str(idea_obj.get("title", "")),
                    hook_angle=str(idea_obj.get("hook_angle", "")),
                    target_platforms=idea_obj.get("target_platforms", []),
                    content_pillar=str(idea_obj.get("content_pillar", "")),
                    rationale=str(idea_obj.get("rationale", "")),
                    suggested_format=str(idea_obj.get("suggested_format", "")),
                    source_material_ids=[material_id],
                    tags=record.get("tags", []) + (idea_obj.get("target_platforms", [])),
                    metadata={
                        "generation_status": "generated",
                        "generated_at": now,
                        "source_material_id": material_id,
                    },
                )
                created.append(idea)
            except Exception:
                continue  # Skip individual idea creation failures

        return {"ideas": created, "count": len(created)}

    def generate_ideas_for_project(self, project_id: str) -> Dict:
        """Generate ideas for all enriched materials in a project that don't have ideas yet.

        Returns {"generated": N, "skipped": M, "errors": E, "total_materials": T}.
        """
        records = self.store.list_source_material_records(project_id=project_id)
        counts = {"generated": 0, "skipped": 0, "errors": 0, "total_materials": len(records)}

        for rec in records:
            meta = rec.get("metadata_json", {}) or {}
            if meta.get("enrichment_status") != "enriched":
                counts["skipped"] += 1
                continue

            material_id = rec["material_id"]
            try:
                result = self.generate_ideas_from_material(material_id, project_id)
                if result.get("error"):
                    counts["errors"] += 1
                elif result.get("skipped"):
                    counts["skipped"] += 1
                else:
                    counts["generated"] += 1
            except Exception:
                counts["errors"] += 1

        return counts

    def mine_ideas(
        self,
        project_id: str,
        source_material_id: Optional[str] = None,
        max_ideas: int = 5,
    ) -> List[Dict]:
        """Typed-envelope backing for the ``mine_ideas`` job kind (D-4).

        Composes the existing single-material (``generate_ideas_from_material``)
        and multi-material (``generate_ideas_for_project``) idea-generation
        paths behind one typed contract. ``max_ideas`` is clamped to the same
        1-20 range ``MineIdeasPayload`` enforces at enqueue time.

        LLM failures degrade gracefully: if the underlying path returns an
        empty ``ideas`` list (with or without an ``error`` key) this method
        returns ``[]`` -- it never raises for downstream LLM trouble.
        """
        if not project_id:
            raise ValueError("project_id is required")
        max_ideas = max(1, min(int(max_ideas), 20))

        if source_material_id:
            result = self.generate_ideas_from_material(
                material_id=source_material_id, project_id=project_id
            )
            ideas = (result or {}).get("ideas", []) or []
        else:
            self.generate_ideas_for_project(project_id=project_id)
            ideas = self.store.list_content_idea_records(project_id=project_id) or []

        return ideas[:max_ideas]

    # ------------------------------------------------------------------
    # Content idea CRUD + evaluation lifecycle
    # ------------------------------------------------------------------

    _VALID_TRANSITIONS = {
        ("draft", "approved"),
        ("draft", "rejected"),
        ("approved", "draft"),
        ("rejected", "draft"),
    }

    def add_content_idea(
        self,
        project_id: str,
        title: str,
        hook_angle: str = "",
        target_platforms: Optional[List[str]] = None,
        content_pillar: str = "",
        rationale: str = "",
        suggested_format: str = "",
        source_material_ids: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """Validate, build, persist, and return a new content idea."""
        if not project_id:
            raise ValueError("project_id is required")

        normalized_tags = _normalize_tags(tags)

        idea = ContentIdea(
            idea_id="",  # Let store.normalize_content_idea_record generate ci_ prefixed ID
            project_id=project_id,
            title=title,
            hook_angle=hook_angle,
            target_platforms=target_platforms or [],
            content_pillar=content_pillar,
            rationale=rationale,
            suggested_format=suggested_format,
            source_material_ids=source_material_ids or [],
            status="draft",
            tags=normalized_tags,
            metadata_json=metadata or {},
        )

        # Normalize to get the store-generated ID before persisting
        normalized = self.store.normalize_content_idea_record(idea.to_dict())
        idea_id = normalized["idea_id"]

        self.store.save_content_idea_record(normalized)
        return self.store.get_content_idea_record(idea_id) or normalized

    def get_content_idea(self, idea_id: str) -> Optional[ContentIdea]:
        """Retrieve a single content idea by ID, or None."""
        record = self.store.get_content_idea_record(idea_id)
        if record is None:
            return None
        return ContentIdea.from_dict(record)

    def list_content_ideas(
        self,
        project_id: str,
        status: Optional[str] = None,
        content_pillar: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[ContentIdea]:
        """List content ideas for a project with optional filters."""
        records = self.store.list_content_idea_records(
            project_id=project_id,
            status=status,
            content_pillar=content_pillar,
            limit=limit,
        )
        return [ContentIdea.from_dict(r) for r in records]

    def update_content_idea(self, idea_id: str, **kwargs) -> Dict:
        """Merge *kwargs* into an existing content idea and persist.

        Raises ValueError if the idea_id does not exist.
        """
        existing = self.store.get_content_idea_record(idea_id)
        if existing is None:
            raise ValueError(f"Content idea '{idea_id}' not found")

        merged = dict(existing)

        allowed_fields = {
            "title",
            "hook_angle",
            "target_platforms",
            "content_pillar",
            "rationale",
            "suggested_format",
            "source_material_ids",
            "tags",
            "metadata_json",
        }
        for key, value in kwargs.items():
            if key not in allowed_fields and key != "status":
                continue
            if key == "tags":
                merged["tags"] = _normalize_tags(value)
            elif key == "status":
                # Status changes must go through evaluate_content_idea
                raise ValueError("Use evaluate_content_idea() to change status")
            else:
                merged[key] = value

        merged["updated_at"] = datetime.now(timezone.utc).isoformat()

        self.store.save_content_idea_record(merged)
        return self.store.get_content_idea_record(idea_id) or merged

    def evaluate_content_idea(
        self,
        idea_id: str,
        new_status: str,
        evaluation_notes: Optional[str] = None,
    ) -> Dict:
        """Transition a content idea's status through the evaluation lifecycle.

        Allowed transitions: draft→approved, draft→rejected,
        approved→draft, rejected→draft.

        Raises ValueError if the idea is not found or the transition is invalid.
        """
        existing = self.store.get_content_idea_record(idea_id)
        if existing is None:
            raise ValueError(f"Content idea '{idea_id}' not found")

        old_status = existing.get("status", "draft")
        transition = (old_status, new_status)

        if transition not in self._VALID_TRANSITIONS:
            raise ValueError(f"Invalid status transition: {old_status} → {new_status}")

        merged = dict(existing)
        merged["status"] = new_status
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        if evaluation_notes is not None:
            merged["evaluation_notes"] = evaluation_notes

        self.store.save_content_idea_record(merged)
        return self.store.get_content_idea_record(idea_id) or merged

    # ------------------------------------------------------------------
    # Idea → content bridge
    # ------------------------------------------------------------------

    def _clean_generated_content(self, content: str) -> str:
        """Strip prompt metadata lines and separators echoed back by the LLM."""
        import re

        lines = content.strip().splitlines()
        cleaned = []
        started = False
        metadata_pattern = re.compile(
            r"^(Platform|Content Type|Content Pillar|Hook Type|"
            r"PLATFORM|CONTENT TYPE|CONTENT PILLAR|HOOK TYPE|"
            r"LEARNING PATTERNS|What Works|What to Avoid)\s*:",
            re.IGNORECASE,
        )
        for line in lines:
            stripped = line.strip()
            if not started:
                if not stripped or metadata_pattern.match(stripped) or stripped == "---":
                    continue
                started = True
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    def _build_content_from_idea_prompt(
        self, idea_record: Dict, platform: str, project_id: str
    ) -> str:
        """Build a platform-specific LLM prompt to generate content from an approved idea."""
        # Brand voice and learning patterns
        brand_voice = self._load_brand_voice(project_id)
        learning_patterns = self._load_learning_patterns(project_id)

        # Source material key points from linked materials
        key_points: List[str] = []
        for sm_id in idea_record.get("source_material_ids", []):
            sm = self.store.get_source_material_record(sm_id)
            if sm:
                meta = sm.get("metadata_json", {}) or {}
                key_points.extend(meta.get("key_points", []))
        # Deduplicate preserving order
        seen_kp = set()
        unique_kps = []
        for kp in key_points:
            if kp not in seen_kp:
                seen_kp.add(kp)
                unique_kps.append(kp)
        key_points = unique_kps[:10]

        # Platform-specific instructions
        platform_limits = {
            "twitter": 280,
            "linkedin": 3000,
            "nostr": 1000,
        }
        char_limit = platform_limits.get(platform, 3000)

        platform_format_hints = {
            "twitter": (
                "Write a concise, punchy tweet. "
                "Use 1-2 relevant hashtags max. "
                "Hook in the first line."
            ),
            "linkedin": (
                "Write a professional LinkedIn post. "
                "Use short paragraphs with line breaks. "
                "Start with an attention-grabbing hook. "
                "End with a clear CTA or thought-provoking question."
            ),
            "nostr": (
                "Write a direct, authentic post for Nostr. No hashtags. Conversational tone."
            ),
        }
        format_hint = platform_format_hints.get(platform, "Write engaging social media content.")

        sections = []
        sections.append(
            f"Generate content for {platform.upper()} (max {char_limit} characters).\n"
            f"{format_hint}\n\n"
            "Return ONLY the raw content text. No labels, no metadata, no JSON."
        )

        # Idea details
        idea_parts = []
        title = idea_record.get("title", "")
        hook_angle = idea_record.get("hook_angle", "")
        rationale = idea_record.get("rationale", "")
        content_pillar = idea_record.get("content_pillar", "")
        suggested_format = idea_record.get("suggested_format", "")

        if title:
            idea_parts.append(f"Content Idea Title: {title}")
        if hook_angle:
            idea_parts.append(f"Hook Angle: {hook_angle}")
        if rationale:
            idea_parts.append(f"Rationale: {rationale}")
        if content_pillar:
            idea_parts.append(f"Content Pillar: {content_pillar}")
        if suggested_format:
            idea_parts.append(f"Suggested Format: {suggested_format}")

        if idea_parts:
            sections.append("Content idea:\n" + "\n".join(idea_parts))

        if key_points:
            sections.append(
                "Key points from source material:\n" + "\n".join(f"- {p}" for p in key_points)
            )

        if brand_voice:
            sections.append(f"Brand voice:\n{brand_voice[:2000]}")

        if learning_patterns:
            sections.append(f"Learning patterns from past content:\n{learning_patterns[:1500]}")

        return "\n\n".join(sections)

    def approve_and_generate_content(
        self,
        idea_id: str,
        project_id: str,
        feedback_manager,
    ) -> Dict:
        """Approve a content idea, generate platform-specific content via LLM,
        and create review records via FeedbackManager.

        Args:
            idea_id: The content idea ID to approve and generate from.
            project_id: The project context for brand voice and learning patterns.
            feedback_manager: A FeedbackManager instance (passed per-call to avoid
                changing __init__ signature).

        Returns:
            Dict with keys: success, idea_id, generated_platforms, review_ids, errors.
        """
        # --- Validate idea exists ---
        idea_record = self.store.get_content_idea_record(idea_id)
        if idea_record is None:
            raise ValueError(f"Content idea '{idea_id}' not found")

        now = datetime.now(timezone.utc).isoformat()
        metadata = dict(idea_record.get("metadata_json", {}) or {})

        # --- Transition to approved (idempotent) ---
        current_status = idea_record.get("status", "draft")
        if current_status == "approved":
            pass  # Already approved — skip re-approval
        elif current_status == "draft":
            idea_record = self.evaluate_content_idea(idea_id, "approved")
        else:
            # rejected → draft → approved not a single hop; try via draft
            if current_status == "rejected":
                self.evaluate_content_idea(idea_id, "draft")
                idea_record = self.evaluate_content_idea(idea_id, "approved")
            else:
                raise ValueError(f"Cannot approve idea in status '{current_status}'")

        # Refresh record after potential status change
        idea_record = self.store.get_content_idea_record(idea_id)
        metadata = dict(idea_record.get("metadata_json", {}) or {})

        # --- Determine target platforms ---
        target_platforms = idea_record.get("target_platforms", []) or []
        if not target_platforms:
            target_platforms = ["twitter", "linkedin"]

        # --- Generate content for each platform ---
        generated_platforms: List[str] = []
        review_ids: List[str] = []
        errors: List[Dict] = []

        for platform in target_platforms:
            try:
                prompt = self._build_content_from_idea_prompt(idea_record, platform, project_id)
                raw_content = self._call_llm_for_enrichment(prompt, max_tokens=1000)
                content = self._clean_generated_content(raw_content)

                # Create review record
                post_data = {
                    "content": content,
                    "platform": platform,
                    "publish_channel": platform,
                    "project_id": project_id,
                    "idea_id": idea_id,
                    "source_material_ids": idea_record.get("source_material_ids", []),
                    "content_type": "social",
                    "pillar": idea_record.get("content_pillar", ""),
                }
                review = feedback_manager.add_for_review(post_data=post_data, channel="idea_bridge")
                review_id = review.get("review_id", "")

                generated_platforms.append(platform)
                review_ids.append(review_id)

            except Exception as e:
                errors.append({"platform": platform, "error": str(e)})

        # --- Update idea metadata ---
        if errors and not generated_platforms:
            # Complete failure — idea stays approved, record error
            metadata["generation_status"] = "bridge_failed"
            metadata["bridge_error"] = "; ".join(f"{e['platform']}: {e['error']}" for e in errors)
            metadata["bridge_error_at"] = now
        else:
            # Full or partial success
            metadata["generation_status"] = "content_generated"
            metadata["generated_at"] = now
            metadata["review_ids"] = review_ids
            metadata["generated_platforms"] = generated_platforms
            if errors:
                metadata["bridge_errors"] = errors

        # Persist metadata update
        idea_record_copy = dict(self.store.get_content_idea_record(idea_id))
        idea_record_copy["metadata_json"] = metadata
        idea_record_copy["updated_at"] = now
        self.store.save_content_idea_record(idea_record_copy)

        return {
            "success": len(generated_platforms) > 0,
            "idea_id": idea_id,
            "generated_platforms": generated_platforms,
            "review_ids": review_ids,
            "errors": errors,
        }

    def delete_content_idea(self, idea_id: str) -> bool:
        """Delete a content idea. Returns True if deleted."""
        return self.store.delete_content_idea_record(idea_id)

    # ------------------------------------------------------------------
    # Carousel generation via Gamma.app
    # ------------------------------------------------------------------

    async def generate_carousel_for_review(
        self,
        review_id: str,
        num_cards: int = 5,
        structured: bool = True,
    ) -> Dict:
        """Generate a carousel for a review item using Gamma.app.

        When structured=True (default), uses the LLM to produce slide-by-slide
        copy with a cover/context/body/CTA structure before sending to Gamma.
        Falls back to raw text splitting when structured=False or on LLM failure.

        Args:
            review_id: The review record ID.
            num_cards: Number of carousel cards (default 5, max 12).
            structured: Use LLM-structured slide copy (default True).

        Returns:
            Dict with success, gamma_url, export_url, error.
        """
        from integrations.gamma_api import GammaAPIClient

        gamma = GammaAPIClient()
        if not gamma.is_configured():
            return {"success": False, "error": "Gamma.app not configured. Set GAMMA_APP_API_KEY."}

        # Load review record
        record = self.store.get_review_record(review_id)
        if record is None:
            return {"success": False, "error": f"Review '{review_id}' not found"}

        post_data = record.get("post_data", {}) or {}
        content = post_data.get("content", "")
        platform = post_data.get("platform", "linkedin")
        title = post_data.get("title", "")
        pillar = post_data.get("pillar", "")
        topic = post_data.get("topic", "")

        if not content:
            return {"success": False, "error": "Review has no content to generate carousel from"}

        # Determine card count from content length
        if num_cards < 1:
            num_cards = 5
        num_cards = min(num_cards, 12)

        carousel_input = None
        carousel_slides = None
        archetype = None

        if structured:
            # Use LLM to produce structured slide-by-slide copy
            carousel_slides, archetype = self._build_structured_carousel(
                content, title, pillar, topic, num_cards
            )
            if carousel_slides:
                carousel_input = self._slides_to_gamma_input(carousel_slides, title)

        # Fallback to raw text splitting if structured generation failed
        if not carousel_input:
            carousel_input = self._build_carousel_input(content, title)

        result = await gamma.generate_carousel(
            content=carousel_input,
            title=title or "Social Carousel",
            num_cards=num_cards,
            platform=platform,
        )

        if result.get("success"):
            # Attach media URLs to the review record
            media = record.get("media", [])
            media_entry = {
                "type": "carousel",
                "gamma_url": result["gamma_url"],
                "export_url": result["export_url"],
                "generation_id": result["generation_id"],
                "platform": platform,
                "num_cards": num_cards,
                "structured": carousel_slides is not None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if archetype:
                media_entry["carousel_archetype"] = archetype
            if carousel_slides:
                media_entry["slides"] = carousel_slides
            media.append(media_entry)
            record["media"] = media
            self.store.save_review_record(record)

        return result

    def _build_carousel_input(self, content: str, title: str = "") -> str:
        """Transform post content into carousel-friendly input for Gamma.

        Adds card break markers (\\n---\\n) between logical sections so Gamma
        produces clean slide breaks. This is the fallback when structured
        LLM-based generation is unavailable.
        """
        # If content already has explicit breaks, pass through
        if "\n---\n" in content:
            parts = content.split("\n---\n")
        else:
            # Split on double newlines (paragraph breaks)
            parts = [p.strip() for p in content.split("\n\n") if p.strip()]

        # Rebuild with Gamma card-break markers
        cards = []
        if title:
            cards.append(f"# {title}")
        for i, part in enumerate(parts, start=1):
            # Add slide number for visual clarity
            cards.append(part)

        return "\n---\n".join(cards)

    def _build_structured_carousel(
        self,
        content: str,
        title: str,
        pillar: str,
        topic: str,
        num_slides: int,
    ) -> tuple:
        """Use the LLM to generate structured slide-by-slide carousel copy.

        Returns:
            Tuple of (slides_list, archetype) or (None, None) on failure.
        """
        try:
            from generator.llm_content_generator import LLMContentGenerator

            generator = LLMContentGenerator()
            result = generator.generate_carousel_copy(
                topic=topic or title or None,
                archetype=None,  # auto-select
                pillar=pillar or None,
                num_slides=num_slides,
            )

            slides = result.get("slides")
            archetype = result.get("archetype")
            if slides and isinstance(slides, list):
                return slides, archetype
        except Exception as e:
            print(f"Warning: Structured carousel generation failed, falling back: {e}")

        return None, None

    def _slides_to_gamma_input(self, slides: list, title: str = "") -> str:
        """Convert structured slide data to Gamma-compatible text input.

        Each slide becomes a card section separated by \\n---\\n markers.
        The headline and body are combined for each card.
        """
        cards = []
        for slide in slides:
            headline = slide.get("headline", "").strip()
            body = slide.get("body", "").strip()
            slide_type = slide.get("type", "content")

            parts = []
            if headline:
                if slide_type == "cover":
                    parts.append(f"# {headline}")
                else:
                    parts.append(f"**{headline}**")
            if body:
                parts.append(body)

            if parts:
                cards.append("\n\n".join(parts))

        return "\n---\n".join(cards)


# ------------------------------------------------------------------
# Tag normalization utility
# ------------------------------------------------------------------


def _normalize_source_url(url: Optional[str]) -> str:
    """Allow only fetchable HTTP(S) source URLs."""
    if not url:
        return ""
    normalized = str(url).strip()
    if not normalized:
        return ""
    if len(normalized) > MAX_SOURCE_URL_LENGTH:
        raise ValueError("URL is too long")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in ALLOWED_SOURCE_URL_SCHEMES or not parsed.netloc:
        raise ValueError("URL must use http or https")
    return normalized


def _normalize_tags(tags) -> List[str]:
    """Accept list or comma-separated string, strip, deduplicate preserving order."""
    if tags is None:
        return []

    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    else:
        tags = [str(t).strip() for t in tags]

    seen = set()
    result = []
    for tag in tags:
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result
