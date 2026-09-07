"""Run the full completion gate and write only measured audit results.

Usage: python audit.py
Exit status is nonzero when tests, integrity, or offline checks fail.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from engine.rule_integrity import validate_database
from engine.ollama_client import ollama_status, pick_vision_model

ROOT=Path(__file__).resolve().parent


def main():
    rules_path=ROOT/'data/mcode_rules.json'
    try:
        integrity=validate_database(json.loads(rules_path.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        integrity={'errors':[str(exc)],'total_authoritative_codes':0,'total_trigger_phrases':0,
                   'duplicate_codes':[],'conflicting_triggers':[],'verify_rules':[]}
    with tempfile.TemporaryDirectory(prefix='tenet-audit-') as folder:
        junit=Path(folder)/'results.xml'
        run=subprocess.run([sys.executable,'-m','pytest','tests','-q',f'--junitxml={junit}'],cwd=ROOT)
        cases=ET.parse(junit).getroot().findall('.//testcase') if junit.exists() else []
    def passed(case):
        return not any(case.find(tag) is not None for tag in ('failure','error','skipped'))
    offline=[c for c in cases if c.get('classname')=='tests.test_offline']
    expected_offline={'test_offline_core','test_offline_server_startup'}
    offline_ok=bool(offline) and expected_offline.issubset({c.get('name') for c in offline}) and all(passed(c) for c in offline)
    # This probe measures optional functionality on the actual host, separately
    # from the network-denied offline tests. It never downloads models.
    import database.db as db
    status=ollama_status(db.get_setting('ollama_url','http://127.0.0.1:11434'))
    vision=pick_vision_model(status['models']) if status['available'] else None
    failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
    def verified(name):
        selected = [c for c in cases if c.get('name', '').startswith(name)]
        return bool(selected) and all(passed(c) for c in selected)
    gates = {
        'server_starts': verified('test_offline_server_startup'),
        'no_startup_traceback': verified('test_offline_server_startup'),
        'mcode_json_validates': not integrity['errors'],
        'search_works': verified('test_offline_core'),
        'manual_analyzer_works': verified('test_offline_core'),
        'paste_analyzer_works': verified('test_offline_core'),
        'mm_engine_works': verified('test_acceptance_basic_mappings'),
        'reference_extraction_works': verified('test_required_regressions'),
        'appointment_logic_works': verified('test_required_regressions'),
        'call_before_logic_works': verified('test_required_regressions'),
        'mock_test_works': verified('test_offline_core'),
        'wrong_answer_tracking_works': verified('test_offline_core'),
        'history_works': verified('test_offline_core'),
        'offline_core_works': offline_ok,
        'all_automated_tests_pass': run.returncode == 0 and bool(cases) and all(passed(c) for c in cases),
        'acceptance_bol_expected_results': verified('test_acceptance_suggested_entries'),
    }
    report={
        'total_authoritative_codes':integrity['total_authoritative_codes'],
        'total_trigger_phrases':integrity['total_trigger_phrases'],
        'duplicate_codes':integrity['duplicate_codes'],
        'conflicting_triggers':integrity['conflicting_triggers'],
        'verify_rules':integrity['verify_rules'],
        'tests_total':len(cases),
        'tests_passed':sum(passed(c) for c in cases),
        'tests_failed':failed,
        'ollama_available':bool(status['available']),
        'vision_model_available':bool(vision),
        'offline_core_test_passed':offline_ok,
        'tests_skipped':sum(c.find('skipped') is not None for c in cases),
        'test_exit_code':run.returncode,
        'integrity_errors':integrity['errors'],
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'rule_database_sha256':hashlib.sha256(rules_path.read_bytes()).hexdigest(),
        'offline_test_method':'Application outbound sockets denied (including Ollama), API keys/tokens removed from test environment, isolated SQLite storage. Windows internal asyncio socketpair is permitted. Host network settings are unchanged.',
        'completion_status':'COMPLETE' if run.returncode==0 and offline_ok and not integrity['errors'] and all(passed(c) for c in cases) else 'PARTIALLY COMPLETE',
        'test_results':[{'test':c.get('classname','')+'.'+c.get('name',''),'passed':passed(c)} for c in cases],
        'completion_gates': gates,
    }
    if not all(gates.values()):
        report['completion_status'] = 'PARTIALLY COMPLETE'
    path=ROOT/'audit_report.json'
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f"{report['completion_status']}: {report['tests_passed']}/{report['tests_total']} tests passed; audit: {path}")
    return 0 if report['completion_status']=='COMPLETE' else 1


if __name__=='__main__':
    raise SystemExit(main())
