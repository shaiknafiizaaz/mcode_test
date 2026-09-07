"""User-specified regressions and additional ambiguity/value boundaries."""
import copy
import pytest
from engine.bol_parser import parse_text
from engine.mcode_engine import analyze_lines
from engine.rules_loader import load_rules
from engine.rule_integrity import validate_database

CASES = [
 ('CALL FOR APPOINTMENT 48 HOURS BEFORE DELIVERY', 'M48', None),
 ('CALL 48 HOURS BEFORE DELIVERY 555-123-4567', 'M48H', '555-123-4567'),
 ('CALL FOR APPOINTMENT 555-123-4567', 'MCA', '555-123-4567'),
 ('CALL FOR APPOINTMENT', 'MCFA', None),
 ('CALL BEFORE DELIVERY 555-123-4567', 'MCALLB', '555-123-4567'),
 ('CALL BEFORE DELIVERY', 'MBEFOR', None),
 ('CALL 24 HOURS BEFORE DELIVERY\n555-123-4567', 'M24', '555-123-4567'),
 ('CALL 1 HOUR BEFORE DELIVERY', 'M1HO', None),
 ('CALL 2 HOURS BEFORE DELIVERY', 'M2B4', None),
 ('NO APPOINTMENT NECESSARY', 'MNDA', None),
 ('LIFT GATE PICKUP', 'LIFTP', None),
 ('LIFT GATE AT PICKUP', 'LIFTP', None),
 ('LIFT GATE DELIVERY', 'MLIFT', None),
 ('RESIDENTIAL PICKUP', 'RPU', None),
 ('RESIDENTIAL DELIVERY', 'RC', None),
 ('INSIDE PICKUP', 'IPU', None),
 ('INSIDE DELIVERY', 'ID', None),
 ('SHIPPER PHONE 555-1111', 'MSPH', '555-1111'),
 ('CUSTOMER PHONE 555-2222', 'MCPH', '555-2222'),
 ('PHONE 555-3333', 'MPHONE', '555-3333'),
 ('PO # 12345', 'MPO', '12345'),
 ('PACKING LIST # 987', 'MPKS', '987'),
 ('PACKING LIST ENCLOSED', 'MPACK', None),
 ('SHIPPER REFERENCE # 100', 'MSHRE', '100'),
 ('REFERENCE # 100', 'MRF', '100'),
 ('SHIPPER ORDER # 200', 'MSORD', '200'),
 ('CUSTOMER ORDER # 300', 'MCORD', '300'),
 ('ORDER # 400', 'MORD', '400'),
 ('STORE #: 145', 'MSTO', '145'),
 ('SUITE 200', 'MSUI', '200'),
 ('CUSTOMER #: 99821', 'MCN', '99821'),
 ('ATTN: John Smith', 'MA', 'John Smith'),
 ('2 SKIDS', 'MM', '2 SKDS'),
 ('PO #: AbC-001', 'MPO', 'AbC-001'),
]

@pytest.mark.parametrize('text,code,value', CASES)
def test_required_regressions(text, code, value):
    entries = analyze_lines(parse_text(text)['lines'])['entries']
    assert [e['code'] for e in entries] == [code], entries
    assert entries[0]['status'] == 'CONFIRMED'
    if value is not None:
        assert entries[0]['value'] == value

@pytest.mark.parametrize('section,code', [('shipper','MSPH'),('consignee','MCPH'),('any','MPHONE')])
def test_generic_phone_uses_section(section, code):
    entries = analyze_lines([dict(section=section,text='PHONE # 555-3333')])['entries']
    assert [(e['code'],e['value']) for e in entries] == [(code,'555-3333')]


def test_unrelated_shipper_phone_is_not_delivery_contact():
    lines = [dict(section='shipper',text='SHIPPER PHONE 555-1111'),dict(section='delivery',text='CALL 24 HOURS BEFORE DELIVERY')]
    entry = next(e for e in analyze_lines(lines)['entries'] if e['code']=='M24')
    assert entry['status']=='VERIFY'
    assert entry['value']==''
    assert 'phone' not in entry


def test_conflicting_phones_are_not_arbitrarily_selected():
    result = analyze_lines(parse_text('CALL 24 HOURS BEFORE DELIVERY 555-1111 OR 555-2222')['lines'])
    entry = next(e for e in result['entries'] if e['code']=='M24')
    assert entry['status']=='CONFLICT'
    assert entry['value']==''
    assert result['conflicts']


def test_appointment_conflict_marks_entries():
    result = analyze_lines(parse_text('CALL FOR APPOINTMENT\nNO APPOINTMENT NECESSARY')['lines'])
    assert all(e['status']=='CONFLICT' for e in result['entries'])


def test_multiple_reference_values_on_one_line():
    entries = analyze_lines(parse_text('PO # AbC-001; STORE # 145')['lines'])['entries']
    assert [(e['code'],e['value']) for e in entries] == [('MPO','AbC-001'),('MSTO','145')]


def test_plain_tie_is_conflict(monkeypatch):
    from engine import mcode_engine as engine
    monkeypatch.setattr(engine, '_TRIGGER_CACHE', {'MR':['urgent'], 'MPACK':['urgent']})
    result = engine.analyze_lines([dict(section='any',text='URGENT')])
    assert {e['code'] for e in result['entries']} == {'MR','MPACK'}
    assert all(e['status']=='CONFLICT' for e in result['entries'])
    assert result['conflicts']


def test_authoritative_database_validates():
    assert validate_database(load_rules('mcodes'))['errors']==[]

@pytest.mark.parametrize('mutation', ['duplicate','meaning','trigger','missing','category','regex','malformed'])
def test_database_rejects_invalid_rules(mutation):
    data=copy.deepcopy(load_rules('mcodes'))
    first=data['codes'][0]
    if mutation in ('duplicate','meaning'):
        data['codes'].append(copy.deepcopy(first))
        if mutation=='meaning': data['codes'][-1]['meaning']='Incompatible meaning'
    elif mutation=='trigger': data['codes'][1]['triggers'].append(first['triggers'][0])
    elif mutation=='missing': del first['meaning']
    elif mutation=='category': first['category']='invalid'
    elif mutation=='regex': first['value_patterns']=['[']
    elif mutation=='malformed': data['codes'].append(None)
    assert validate_database(data)['errors']

def test_long_reference_value_is_preserved():
    value='AbC-'+'0123456789'*12
    entry=analyze_lines(parse_text('PO #: '+value)['lines'])['entries'][0]
    assert entry['value']==value


@pytest.mark.parametrize('text', ['PO #', 'CUSTOMER #', 'PACKING LIST #'])
def test_missing_reference_value_is_not_invented(text):
    assert analyze_lines(parse_text(text)['lines'])['entries']==[]


def test_conflicts_are_excluded_from_copy_panel():
    from engine.validation import build_result
    lines=parse_text('CALL FOR APPOINTMENT\nNO APPOINTMENT NECESSARY')['lines']
    result=build_result(lines,analyze_lines(lines))
    assert result['conflicts']
    assert result['suggested_entries']==[]


def test_startup_rejects_invalid_authoritative_database(tmp_path):
    import subprocess,sys
    from pathlib import Path
    path=tmp_path/'rules.json'
    path.write_text('{"codes": []}')
    program="from engine import rules_loader; rules_loader.DATA_DIR="+repr(str(tmp_path))+"; rules_loader.RULE_FILES['mcodes']='rules.json'; import app"
    process=subprocess.run([sys.executable,'-c',program],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert process.returncode!=0
    assert 'Invalid authoritative M-Code database' in process.stderr


def test_no_independent_python_code_mappings():
    import ast
    from pathlib import Path
    authoritative={c['code'] for c in load_rules('mcodes')['codes']}
    for path in (Path(__file__).resolve().parents[1]/'engine').glob('*.py'):
        if path.name=='handling_units.py':
            continue
        literals={node.value for node in ast.walk(ast.parse(path.read_text())) if isinstance(node,ast.Constant) and isinstance(node.value,str)}
        assert not literals & authoritative, (path,literals & authoritative)


def test_conflicting_call_timings_are_not_silently_chosen():
    result=analyze_lines(parse_text('CALL 1 HOUR BEFORE DELIVERY OR CALL 2 HOURS BEFORE DELIVERY')['lines'])
    assert {e['code'] for e in result['entries']}=={'M1HO','M2B4'}
    assert all(e['status']=='CONFLICT' for e in result['entries'])
    assert result['conflicts']


def test_scheduled_date_does_not_create_appointment():
    result=analyze_lines(parse_text('SCHEDULE DELIVERY 09/16')['lines'])
    assert [(e['code'],e['value']) for e in result['entries']]==[('MSCHED','09/16')]


def test_reference_number_is_not_call_phone():
    result=analyze_lines(parse_text('CALL 24 HOURS BEFORE DELIVERY\nPO # 123-4567')['lines'])
    entry=next(e for e in result['entries'] if e['code']=='M24')
    assert entry['value']=='' and entry['status']=='VERIFY'
