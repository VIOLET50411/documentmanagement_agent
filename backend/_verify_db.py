"""Verify database columns exist."""
import psycopg2
from app.config import settings

conn = psycopg2.connect(settings.postgres_dsn_sync)
cur = conn.cursor()

cur.execute("""
    SELECT column_name FROM information_schema.columns 
    WHERE table_name = 'documents' AND column_name IN ('file_hash','version','parent_doc_id') 
    ORDER BY column_name
""")
print("Document columns:", [r[0] for r in cur.fetchall()])

cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'training_qa_pairs'")
print("training_qa_pairs exists:", cur.fetchone()[0] > 0)

conn.close()
print("Verification OK")
