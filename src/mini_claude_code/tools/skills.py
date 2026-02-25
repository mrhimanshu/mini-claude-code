"""Two-layer skill loading system (s05).

Layer 1: Short descriptions in the system prompt (cheap).
Layer 2: Full body loaded on-demand via load_skill tool.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

from mini_claude_code.config import SKILLS_DIR


class SkillLoader:
    """Loads .md skill files from the skills directory."""

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self.skills: dict[str, dict] = {}
        self.reload()

    # ------------------------------------------------------------------
    def reload(self) -> None:
        self.skills.clear()
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.glob("*.md")):
            text = f.read_text(errors="replace")
            meta, body = self._parse_frontmatter(text)
            self.skills[f.stem] = {"meta": meta, "body": body}

    # ------------------------------------------------------------------
    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta: dict[str, str] = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
        return meta, match.group(2).strip()

    # ------------------------------------------------------------------
    def get_descriptions(self) -> str:
        """Layer 1: short summaries for the system prompt."""
        if not self.skills:
            return "(no skills loaded)"
        lines: list[str] = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def get_content(self, name: str) -> str:
        """Layer 2: full body wrapped in <skill> tags."""
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(self.skills.keys()) or "none"
            return f"Error: Unknown skill '{name}'. Available: {available}"
        return f'<skill name="{name}">\n{skill["body"]}\n</skill>'


# Singleton
SKILL_LOADER = SkillLoader(SKILLS_DIR)


@tool
def load_skill(name: str) -> str:
    """Load a skill by name.  Returns the full skill instructions.

    Args:
        name: Name of the skill to load (without .md extension).

    Returns:
        Full skill content wrapped in <skill> tags, or error if not found.
    """
    return SKILL_LOADER.get_content(name)
