"""Invariants that hold across every Alembic revision.

These are static checks on the migration sources rather than runs against a
database. The failure they exist for only appears on a cluster where the
application role is absent — which is every managed Postgres, and none of the
developer machines or CI databases where the role is created up front. A test
that needed such a cluster would not be run; this one runs everywhere.
"""

from __future__ import annotations

import pathlib
import re

VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _migrations() -> list[pathlib.Path]:
    files = sorted(p for p in VERSIONS.glob("*.py") if not p.name.startswith("__"))
    assert files, "no migrations found — has the path moved?"
    return files


def test_every_grant_is_guarded_by_a_role_check():
    """A GRANT to a role that may not exist must be behind _role_exists().

    Managed Postgres (Render, Supabase, RDS) hands you a single owner role, so
    balaji_app does not exist there. An unguarded GRANT does not degrade — it
    aborts the migration, which fails the deploy with a message about a role
    the operator never heard of. 0002 shipped without the guard 0001 had and
    did exactly that on Render.
    """
    offenders = []
    for path in _migrations():
        source = path.read_text()
        if not re.search(r"\bGRANT\b|\bREVOKE\b", source):
            continue
        if "_role_exists" not in source:
            offenders.append(path.name)

    assert offenders == [], (
        "these migrations grant privileges without checking the role exists, "
        f"and will fail on managed Postgres: {offenders}"
    )


def test_revisions_form_one_unbroken_chain():
    """One line of history, correctly linked.

    A duplicated revision id or a missing down_revision produces "Multiple head
    revisions" at deploy time, in an environment far less convenient to debug
    than this one.
    """
    revisions: dict[str, str] = {}
    downs: dict[str, str | None] = {}

    for path in _migrations():
        source = path.read_text()
        rev = re.search(r'^revision = "([^"]+)"', source, re.M)
        down = re.search(r"^down_revision = (?:\"([^\"]+)\"|None)", source, re.M)
        assert rev, f"{path.name} has no revision id"
        assert down, f"{path.name} has no down_revision"

        assert rev.group(1) not in revisions, (
            f"{path.name} reuses revision id {rev.group(1)!r} "
            f"already used by {revisions.get(rev.group(1))}"
        )
        revisions[rev.group(1)] = path.name
        downs[rev.group(1)] = down.group(1)

    roots = [r for r, d in downs.items() if d is None]
    assert len(roots) == 1, f"expected exactly one root migration, found {roots}"

    heads = set(revisions) - {d for d in downs.values() if d}
    assert len(heads) == 1, f"expected exactly one head, found {sorted(heads)}"

    for rev, parent in downs.items():
        if parent is not None:
            assert parent in revisions, (
                f"{revisions[rev]} points at down_revision {parent!r}, "
                "which no migration defines"
            )
