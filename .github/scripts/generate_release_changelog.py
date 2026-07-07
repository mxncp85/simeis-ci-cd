#!/usr/bin/env python3
"""
Génère le changelog d'une release à partir des PR mergées sur release/x.

Catégories :
  - Features : branches feature/*
  - Bugfix   : branches bug/*
  - Autre    : tout le reste
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def fetch_merged_prs(repo: str, base_branch: str) -> list[dict]:
    # Récupère les PR mergées sur la branche release cible.
    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--base",
            base_branch,
            "--state",
            "merged",
            "--limit",
            "200",
            "--json",
            "number,title,headRefName,url,mergedAt",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def categorize_prs(prs: list[dict]) -> tuple[list[str], list[str], list[str]]:
    features: list[str] = []
    bugfixes: list[str] = []
    other: list[str] = []

    for pr in sorted(prs, key=lambda item: item.get("mergedAt") or ""):
        head = pr.get("headRefName", "")
        line = f"- {pr['title']} ([#{pr['number']}]({pr['url']}))"

        if head.startswith("feature/"):
            features.append(line)
        elif head.startswith("bug/"):
            bugfixes.append(line)
        else:
            other.append(line)

    return features, bugfixes, other


def render_markdown(
    version: str, features: list[str], bugfixes: list[str], other: list[str]
) -> str:
    lines = [f"# Simeis v{version}", ""]

    if features:
        lines.extend(["## Features", ""])
        lines.extend(features)
        lines.append("")

    if bugfixes:
        lines.extend(["## Bugfix", ""])
        lines.extend(bugfixes)
        lines.append("")

    if other:
        lines.extend(["## Autre", ""])
        lines.extend(other)
        lines.append("")

    if not features and not bugfixes and not other:
        lines.append("_Aucune pull request mergée sur cette branche pour le moment._")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY")
    base_branch = os.environ.get("RELEASE_BRANCH")
    version = os.environ.get("RELEASE_VERSION")
    output_path = os.environ.get("OUTPUT_PATH", "release-notes.md")

    if not repo or not base_branch or not version:
        print(
            "Variables requises: GITHUB_REPOSITORY, RELEASE_BRANCH, RELEASE_VERSION",
            file=sys.stderr,
        )
        return 1

    prs = fetch_merged_prs(repo, base_branch)
    features, bugfixes, other = categorize_prs(prs)
    content = render_markdown(version, features, bugfixes, other)

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(content)

    print(f"Changelog écrit dans {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
