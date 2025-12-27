from app.services.osv_enrichment import _extract_packages_from_incident, _normalize_osv_response

def test_extract_packages_from_incident():
    incident = {
        "evidence": {
            "evidence_lines": [
                "npm ERR! lodash@4.17.21 has vulnerabilities",
                "see react@18.2.0 for details"
            ]
        },
        "summary": {
            "root_cause": ["Upgrade left-pad@1.3.0 to fix issue."],
            "impact": [],
            "next_steps": []
        }
    }
    pkgs = _extract_packages_from_incident(incident)
    assert ("lodash", "4.17.21") in pkgs
    assert ("react", "18.2.0") in pkgs
    assert ("left-pad", "1.3.0") in pkgs

def test_normalize_osv_response():
    data = {
        "vulns": [
            {
                "id": "OSV-2024-123",
                "summary": "Example vuln",
                "severity": [{"type": "CVSS_V3", "score": "9.8"}],
                "affected": [
                    {
                        "package": {"name": "lodash"},
                        "ranges": [{"events": [{"introduced": "0"}, {"fixed": "4.17.22"}]}],
                    }
                ],
                "references": [{"url": "https://example.com/vuln"}],
            }
        ]
    }
    top = _normalize_osv_response("lodash", "4.17.21", data)
    assert top[0]["package"] == "lodash"
    assert top[0]["osv_id"] == "OSV-2024-123"
    assert top[0]["severity"] == "9.8"
