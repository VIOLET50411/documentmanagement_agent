from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.enterprise_tuning_service import EnterpriseTuningService
from app.services.public_corpus_service import PublicCorpusService


def main() -> None:
    dataset_name = sys.argv[1] if len(sys.argv) > 1 else "swu_public_docs"
    tenant_id = sys.argv[2] if len(sys.argv) > 2 else "public_cold_start"
    dataset_root = ROOT / "datasets" / dataset_name
    reports_dir = ROOT / "reports"

    service = PublicCorpusService(dataset_root)
    records = service.build_records()
    result = EnterpriseTuningService(db=None, reports_dir=reports_dir).export_records_bundle(
        tenant_id=tenant_id,
        source_label=dataset_name,
        records=records,
        train_ratio=0.9,
    )
    print(json.dumps({"record_count": len(records), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
