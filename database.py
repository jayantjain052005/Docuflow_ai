"""
DocuFlow AI — Database Layer (Phase 1: RBAC + Organizations + Clients)
Handles SQLite connections and schema initialization.
Designed for future PostgreSQL migration (no SQLite-specific syntax in queries).
"""

import sqlite3
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE = str(BASE_DIR / "docuflow.db")


def get_db():
    """Return a new database connection with row-factory and FK support."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # ── Users (RBAC-enabled) ───────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            username         TEXT    NOT NULL,
            email            TEXT,
            phone            TEXT    NOT NULL UNIQUE,
            password_hash    TEXT    NOT NULL,
            role             TEXT    NOT NULL DEFAULT 'self_user',
            organization_id  INTEGER,
            is_verified      INTEGER NOT NULL DEFAULT 0,
            is_active        INTEGER NOT NULL DEFAULT 1,
            created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                
            
        )
    """)

    # ── Organizations ──────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT    NOT NULL,
            owner_user_id     INTEGER NOT NULL,
            organization_type TEXT    NOT NULL DEFAULT 'General',
            created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ── Organization Members ───────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS organization_members (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            user_id         INTEGER NOT NULL,
            role            TEXT    NOT NULL DEFAULT 'viewer',
            joined_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id)         REFERENCES users(id)         ON DELETE CASCADE,
            UNIQUE (organization_id, user_id)
        )
    """)

    # ── Clients ────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            full_name       TEXT    NOT NULL,
            email           TEXT,
            primary_phone   TEXT,
            created_by      INTEGER NOT NULL,
            created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by)      REFERENCES users(id)
        )
    """)

    # ── Authorized Numbers (WhatsApp) ──────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS authorized_numbers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id  INTEGER NOT NULL,
            phone      TEXT    NOT NULL,
            label      TEXT    NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        )
    """)

    # ── Documents (unchanged) ──────────────────────────────────────────────
    # ── Documents ──────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,

        owner_user_id    INTEGER NOT NULL,
        uploaded_by_id   INTEGER NOT NULL,

        user_id          INTEGER,

        filename         TEXT NOT NULL,
        file_id          TEXT NOT NULL,

        document_type    TEXT NOT NULL DEFAULT 'Unknown',

        extracted_text   TEXT NOT NULL DEFAULT '',
        summary          TEXT NOT NULL DEFAULT '',

        detected_year    TEXT NOT NULL DEFAULT '',
        important_ids    TEXT NOT NULL DEFAULT '',

        upload_date      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

        is_deleted       INTEGER NOT NULL DEFAULT 0,

        visibility       TEXT NOT NULL DEFAULT 'private',

        organization_id  INTEGER,

        client_user_id   INTEGER,

        FOREIGN KEY (owner_user_id)
            REFERENCES users(id)
            ON DELETE CASCADE,

        FOREIGN KEY (uploaded_by_id)
            REFERENCES users(id)
    )
""")
        # ── Document Shares ──────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS document_shares (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            document_id INTEGER NOT NULL,

            shared_by_user_id INTEGER NOT NULL,

            shared_with_user_id INTEGER NOT NULL,

            permission TEXT NOT NULL DEFAULT 'viewer',

            expires_at DATETIME,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (document_id)
                REFERENCES documents(id)
                ON DELETE CASCADE,

            FOREIGN KEY (shared_by_user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            FOREIGN KEY (shared_with_user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    """)

    # ── Document Access (unchanged) ────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS document_access (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id      INTEGER NOT NULL,
            shared_by_id     INTEGER NOT NULL,
            shared_with_id   INTEGER NOT NULL,
            permission       TEXT    NOT NULL DEFAULT 'viewer',
            expires_at       DATETIME,
            created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (document_id)    REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY (shared_by_id)   REFERENCES users(id)     ON DELETE CASCADE,
            FOREIGN KEY (shared_with_id) REFERENCES users(id)     ON DELETE CASCADE,
            UNIQUE (document_id, shared_with_id)
        )
    """)

    # ── Audit Log (unchanged) ──────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            action      TEXT    NOT NULL,
            entity_type TEXT    NOT NULL,
            entity_id   INTEGER,
            detail      TEXT,
            ip_address  TEXT,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # ── Indexes ────────────────────────────────────────────────────────────
    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_documents_owner      ON documents (owner_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_documents_uploader   ON documents (uploaded_by_id)",
        "CREATE INDEX IF NOT EXISTS idx_access_shared_with   ON document_access (shared_with_id)",
        "CREATE INDEX IF NOT EXISTS idx_access_document      ON document_access (document_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_user           ON audit_log (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_org_members_org      ON organization_members (organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_org_members_user     ON organization_members (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_clients_org          ON clients (organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_auth_numbers_client  ON authorized_numbers (client_id)",
    ]:
        cur.execute(sql)

    conn.commit()
    conn.close()
    print("✅ Database initialized — docuflow.db ready.")


def migrate_db():
    """
    Idempotent migrations — safe to run on existing databases.
    Handles upgrade from is_admin boolean to role TEXT system.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
CREATE TABLE IF NOT EXISTS organization_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    invited_user_id INTEGER NOT NULL,
    invited_by_user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP,

    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (invited_user_id) REFERENCES users(id),
    FOREIGN KEY (invited_by_user_id) REFERENCES users(id)
)
""")

    # Phase 0 legacy: add is_admin if missing (very old DBs)
    try:
        cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback()

    # Phase 1: add role column
    try:
        cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'self_user'")
        conn.commit()
    except Exception:
        conn.rollback()

    # Phase 1: migrate is_admin=1 -> role='super_admin'
    try:
        cur.execute("""
            UPDATE users SET role = 'super_admin'
            WHERE is_admin = 1 AND (role IS NULL OR role = 'self_user')
        """)
        conn.commit()
    except Exception:
        conn.rollback()

    # Phase 1: add email column
    try:
        cur.execute("ALTER TABLE users ADD COLUMN email TEXT")
        conn.commit()
    except Exception:
        conn.rollback()

    # Phase 1: add organization_id column
    try:
        cur.execute("ALTER TABLE users ADD COLUMN organization_id INTEGER")
        conn.commit()
    except Exception:
        conn.rollback()

    # Phase 1: add is_active column
    try:
        cur.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        conn.commit()
    except Exception:
        conn.rollback()

    # Phase 1: add is_verified if missing
    try:
        cur.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback()

    # Legacy document column migrations
    for sql in [
    "ALTER TABLE documents ADD COLUMN owner_user_id INTEGER REFERENCES users(id)",
    "ALTER TABLE documents ADD COLUMN uploaded_by_id INTEGER REFERENCES users(id)",
    "ALTER TABLE documents ADD COLUMN detected_year TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE documents ADD COLUMN important_ids TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE documents ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0",

    "ALTER TABLE documents ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'",
    "ALTER TABLE documents ADD COLUMN organization_id INTEGER",
    "ALTER TABLE documents ADD COLUMN client_user_id INTEGER",
]:
        try:
            cur.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()

    # Backfill owner/uploader from legacy user_id
    try:
        cur.execute("""
            UPDATE documents
               SET owner_user_id  = user_id,
                   uploaded_by_id = user_id
             WHERE owner_user_id IS NULL
        """)
        conn.commit()
    except Exception:
        conn.rollback()

    conn.close()
    # Create new Phase 1 tables if they don't exist
     
    init_db()
    print("✅ Migrations applied.")
    


if __name__ == "__main__":
    init_db()
    migrate_db()
