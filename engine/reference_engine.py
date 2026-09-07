"""Extract values from declarative authoritative rules, resolving overlapping labels."""
import re
from .rules_loader import load_mcodes, get_code_map

RULE_SOURCE = 'data/mcode_rules.json'


def analyze_line(line, section='any'):
    text = line.strip()
    candidates = []
    for rule in load_mcodes():
        for expression in rule.get('value_patterns', []):
            for match in re.finditer(expression, text, re.I):
                if not match.groups() or not match.group(1):
                    continue
                value = match.group(1).strip()
                label = text[match.start():match.start(1)]
                qualifier = bool(re.search(r'#|\bno\.?\b|\bnumber\b', label, re.I))
                if not rule.get('allow_text_value') and not qualifier and not re.match(r'[+\d(]', value):
                    continue
                code = rule.get('section_codes', {}).get(section, rule['code'])
                priority = min(rule['priority'], 3) if code != rule['code'] else rule['priority']
                candidates.append(dict(code=code, value=value, start=match.start(), end=match.end(),
                                       value_start=match.start(1), priority=priority,
                                       label_length=match.start(1)-match.start(), matched_trigger=label.strip()))
    # Specific labels contain their generic suffix: resolve those as one group.
    groups = []
    for candidate in sorted(candidates, key=lambda c: c['start']):
        group = next((g for g in groups if any(c['start'] <= candidate['start'] < c['value_start'] or candidate['start'] <= c['start'] < candidate['value_start'] for c in g)), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    selected = []
    for group in groups:
        rank = min((c['priority'], -c['label_length']) for c in group)
        winners = [c for c in group if (c['priority'], -c['label_length']) == rank]
        seen = set()
        for candidate in winners:
            if candidate['code'] not in seen:
                seen.add(candidate['code'])
                selected.append({**candidate, 'status': 'CONFLICT' if len({c['code'] for c in winners}) > 1 else 'CONFIRMED'})
    selected.sort(key=lambda c:c['start'])
    results = []
    for i, candidate in enumerate(selected):
        stop = next((c['start'] for c in selected[i+1:] if c['start'] >= candidate['value_start']), candidate['end'])
        value = text[candidate['value_start']:min(stop, candidate['end'])].strip().rstrip(';|').rstrip()
        if not value:
            continue
        results.append(dict(code=candidate['code'], value=value, source_text=text,
                            matched_trigger=candidate['matched_trigger'], priority=candidate['priority'],
                            rule_source=RULE_SOURCE, confidence='Exact Rule Match',
                            status=candidate['status'], section=section))
    return results


def get_meaning(code):
    entry = get_code_map().get(code.upper())
    return entry['meaning'] if entry else code
