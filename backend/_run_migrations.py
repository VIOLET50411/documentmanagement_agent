"""Run database migrations for new columns and tables."""
import psycopg2
from app.config import settings

conn = psycopg2.connect(settings.postgres_dsn_sync)
conn.autocommit = True
cur = conn.cursor()

# Add missing columns to documents table
migrations = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS parent_doc_id VARCHAR(36)",
    "CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash)",
]

for sql in migrations:
    print(f"Running: {sql[:60]}...")
    cur.execute(sql)
    print("  OK")

# Create training_qa_pairs table if missing
cur.execute("""
CREATE TABLE IF NOT EXISTS training_qa_pairs (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    doc_id VARCHAR(36) NOT NULL,
    chunk_id VARCHAR(36),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    doc_type VARCHAR(50) DEFAULT 'general',
    status VARCHAR(20) DEFAULT 'pending',
    reviewer_id VARCHAR(36),
    reviewed_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
)
""")
print("training_qa_pairs table: OK")

cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_pairs_tenant ON training_qa_pairs(tenant_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_pairs_doc ON training_qa_pairs(doc_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_pairs_status ON training_qa_pairs(status)")
print("Indexes: OK")

cur.close()
conn.close()
print("ALL MIGRATIONS DONE")
