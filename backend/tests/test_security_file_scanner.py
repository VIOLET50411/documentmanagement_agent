from app.security.file_scanner import FileScanner


def test_file_scanner_blocks_eicar_marker():
    scanner = FileScanner()
    payload = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    result = scanner.scan_bytes(payload)
    assert result["safe"] is False
