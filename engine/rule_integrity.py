"""Validate the authoritative dataset without importing the rule engines."""
import re
from collections import defaultdict


def validate_database(data):
    report = dict(duplicate_codes=[], conflicting_triggers=[], conflicting_meanings=[],
                  verify_rules=[], errors=[], total_authoritative_codes=0, total_trigger_phrases=0)
    if not isinstance(data, dict) or not isinstance(data.get('codes'), list):
        report['errors'].append('codes must be a list')
        return report
    categories = data.get('categories', {})
    if not isinstance(categories, dict) or not categories:
        report['errors'].append('categories must be a nonempty object')
        categories = {}
    seen, triggers, roles, timings = {}, defaultdict(set), set(), set()
    precedence = data.get('contextual_precedence', [])
    if not isinstance(precedence, list) or any(not isinstance(p, dict) for p in precedence):
        report['errors'].append('malformed contextual_precedence')
        precedence = []
    expected_priorities = ['exact_contextual', 'time_specific', 'side_specific', 'exact_trigger', 'structured_label', 'partial_fuzzy', 'verify']
    if data.get('priority_order') != expected_priorities:
        report['errors'].append('invalid or missing priority_order')
    config_patterns = data.get('patterns', {})
    for key in ('appointment', 'no_appointment', 'callbefore', 'attention'):
        patterns = config_patterns.get(key) if isinstance(config_patterns, dict) else None
        patterns = [patterns] if key == 'attention' else patterns
        if not isinstance(patterns, list) or not patterns:
            report['errors'].append(f'missing or invalid patterns: {key}')
            continue
        for pattern in patterns:
            try:
                re.compile(pattern)
            except (TypeError, re.error):
                report['errors'].append(f'invalid contextual pattern: {key}')
    required = ('code', 'meaning', 'category', 'triggers', 'example', 'context',
                'priority', 'plain_enabled', 'display_rank')
    for index, rule in enumerate(data['codes']):
        if not isinstance(rule, dict):
            report['errors'].append(f'rule {index}: must be an object')
            continue
        missing = [k for k in required if k not in rule]
        if missing:
            report['errors'].append(f'rule {index}: missing {missing}')
            continue
        code = rule['code']
        if not isinstance(code, str) or not re.fullmatch('[A-Z][A-Z0-9]*', code):
            report['errors'].append(f'rule {index}: invalid code')
            continue
        if code in seen:
            report['duplicate_codes'].append(code)
            if seen[code]['meaning'] != rule['meaning']:
                report['conflicting_meanings'].append(code)
        seen[code] = rule
        if rule['category'] not in categories.values():
            report['errors'].append(f'{code}: invalid category')
        for field in ('meaning', 'context', 'example'):
            if not isinstance(rule[field], str) or not rule[field].strip():
                report['errors'].append(f'{code}: invalid {field}')
        if type(rule['priority']) is not int or rule['priority'] not in range(1, 8):
            report['errors'].append(f'{code}: invalid priority')
        if type(rule['plain_enabled']) is not bool or type(rule['display_rank']) is not int:
            report['errors'].append(f'{code}: malformed display/engine metadata')
        if 'role' in rule:
            if not isinstance(rule['role'], str):
                report['errors'].append(f'{code}: invalid role')
            elif rule['role'] in roles:
                report['errors'].append(f'{code}: duplicate role')
            else:
                roles.add(rule['role'])
        if 'hours' in rule and (type(rule['hours']) is not int or rule['hours'] <= 0 or rule.get('family') not in ('appointment', 'callbefore')):
            report['errors'].append(f'{code}: invalid timing rule')
        elif 'hours' in rule:
            timing = (rule['family'], rule['hours'])
            if timing in timings:
                report['errors'].append(f'{code}: incompatible duplicate timing rule')
            timings.add(timing)
        if not isinstance(rule['triggers'], list):
            report['errors'].append(f'{code}: triggers must be a list')
        else:
            for trigger in rule['triggers']:
                if not isinstance(trigger, str) or not trigger.strip():
                    report['errors'].append(f'{code}: malformed trigger')
                    continue
                report['total_trigger_phrases'] += 1
                triggers[re.sub(r'\s+', ' ', trigger.lower()).strip()].add(code)
        patterns = rule.get('value_patterns', [])
        if not isinstance(patterns, list):
            report['errors'].append(f'{code}: value_patterns must be a list')
            patterns = []
        exclusions = rule.get('exclude_patterns', [])
        if not isinstance(exclusions, list):
            report['errors'].append(f'{code}: exclude_patterns must be a list')
        else:
            patterns = patterns + exclusions
        if 'service' in rule:
            service = rule['service']
            if not isinstance(service, dict) or not service.get('directions') or any(s not in ('pickup', 'delivery') for s in service.get('directions', [])):
                report['errors'].append(f'{code}: invalid service')
            else:
                patterns = patterns + [service.get('pattern')]
        for pattern in patterns:
            try:
                re.compile(pattern)
            except (re.error, TypeError):
                report['errors'].append(f'{code}: malformed regex')
        if rule.get('priority') == 7 or rule.get('verify_conditions'):
            report['verify_rules'].append(code)
    for trigger, codes in triggers.items():
        if len(codes) > 1:
            documented = any(p.get('trigger') == trigger and isinstance(p.get('codes'), list) and all(isinstance(c, str) for c in p['codes']) and set(p['codes']) == codes and isinstance(p.get('reason'), str) and p['reason'].strip() for p in precedence)
            item = dict(trigger=trigger, codes=sorted(codes), context_documented=documented)
            report['conflicting_triggers'].append(item)
            if not documented:
                report['errors'].append(f'undocumented conflicting trigger: {trigger}')
    for code, rule in seen.items():
        sections = rule.get('section_codes', {})
        if not isinstance(sections, dict):
            report['errors'].append(f'{code}: invalid section_codes')
            continue
        for target in sections.values():
            if not isinstance(target, str) or target not in seen:
                report['errors'].append(f'{code}: unknown contextual code {target}')
    for role in ('attention', 'missing_address', 'no_appointment', 'appointment_phone', 'appointment_no_phone', 'callbefore_phone', 'callbefore_no_phone', 'notify', 'generic_order', 'generic_phone'):
        if role not in roles:
            report['errors'].append(f'missing required role: {role}')
    report['total_authoritative_codes'] = len(seen)
    if report['duplicate_codes']:
        report['errors'].append('duplicate codes: ' + ', '.join(report['duplicate_codes']))
    if report['conflicting_meanings']:
        report['errors'].append('conflicting meanings: ' + ', '.join(report['conflicting_meanings']))
    return report
