"""Test fixtures.

Tests run against a dedicated database (``balaji_crm_test``) so they never touch
development data. The schema is built from the same Alembic migration the app
uses, including the grant that makes audit_log append-only -- testing against a
permissive schema would prove nothing about the real one.
"""

from __future__ import annotations

import os
import subprocess

import pytest

TEST_DB = "balaji_crm_test"
APP_URL = f"postgresql+psycopg://balaji_app:balaji_dev_pw@localhost:5432/{TEST_DB}"
MIGRATION_URL = (
    f"postgresql+psycopg://balaji_migrator:balaji_dev_pw@localhost:5432/{TEST_DB}"
)

os.environ["DATABASE_URL"] = APP_URL
os.environ["MIGRATION_DATABASE_URL"] = MIGRATION_URL
os.environ["JWT_SECRET"] = "test-secret-not-used-anywhere-real"
os.environ["LIST_RATE_LIMIT_PER_MINUTE"] = "10000"


def _psql(db: str, sql: str) -> None:
    subprocess.run(
        ["psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    exists = subprocess.run(
        ["psql", "-d", "postgres", "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname='{TEST_DB}'"],
        capture_output=True, text=True,
    ).stdout.strip()
    if exists != "1":
        subprocess.run(["createdb", TEST_DB], check=True)

    _psql(TEST_DB, "GRANT ALL ON SCHEMA public TO balaji_migrator")
    _psql(TEST_DB, "GRANT USAGE ON SCHEMA public TO balaji_app")
    _psql("postgres", f"GRANT CONNECT ON DATABASE {TEST_DB} TO balaji_app")

    env = {**os.environ, "MIGRATION_DATABASE_URL": MIGRATION_URL}
    subprocess.run(
        ["./.venv/bin/alembic", "downgrade", "base"], env=env, capture_output=True
    )
    result = subprocess.run(
        ["./.venv/bin/alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="session")
def app_module(database):
    from app.main import app

    return app


@pytest.fixture(scope="session")
def seeded(database):
    """Deterministic fixture data: one owner, two agents, one cold caller."""
    from app.db import SessionLocal, system_scope
    from app.models import Contact, Property, User
    from app.security import hash_password

    db = SessionLocal()
    with system_scope():
        owner = User(name="Owner", email="o@t.local", role="owner",
                     password_hash=hash_password("pw12345678"))
        alice = User(name="Alice", email="a@t.local", role="agent",
                     password_hash=hash_password("pw12345678"))
        bob = User(name="Bob", email="b@t.local", role="agent",
                   password_hash=hash_password("pw12345678"))
        carol = User(name="Carol", email="c@t.local", role="cold_caller",
                     password_hash=hash_password("pw12345678"))
        db.add_all([owner, alice, bob, carol])
        db.flush()

        alice_lead = Contact(first_name="Alice", last_name="Lead", phone="+919000000001",
                             phone_masked=True, owner_id=alice.id, stage="new")
        bob_lead = Contact(first_name="Bob", last_name="Lead", phone="+919000000002",
                           phone_masked=True, owner_id=bob.id, stage="new")
        carol_lead = Contact(first_name="Carol", last_name="Lead", phone="+919000000003",
                             phone_masked=True, owner_id=carol.id, stage="new")
        db.add_all([alice_lead, bob_lead, carol_lead])

        prop = Property(title="2 BHK Test", location="Powai", building="Test Tower",
                        listing_type="outright", price=15_000_000,
                        property_type="apartment", posted_by_agent_id=alice.id)
        db.add(prop)
        db.commit()

        data = {
            "owner_id": owner.id, "alice_id": alice.id, "bob_id": bob.id,
            "carol_id": carol.id, "alice_lead": alice_lead.id,
            "bob_lead": bob_lead.id, "carol_lead": carol_lead.id,
            "property_id": prop.id,
        }
    db.close()
    return data


@pytest.fixture
def client(app_module):
    from fastapi.testclient import TestClient

    with TestClient(app_module) as c:
        yield c


def _login(client, email: str) -> str:
    resp = client.post("/auth/login", json={"email": email, "password": "pw12345678"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def owner_h(client, seeded):
    return {"authorization": f"Bearer {_login(client, 'o@t.local')}"}


@pytest.fixture
def alice_h(client, seeded):
    return {"authorization": f"Bearer {_login(client, 'a@t.local')}"}


@pytest.fixture
def bob_h(client, seeded):
    return {"authorization": f"Bearer {_login(client, 'b@t.local')}"}


@pytest.fixture
def carol_h(client, seeded):
    return {"authorization": f"Bearer {_login(client, 'c@t.local')}"}
