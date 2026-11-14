#!/usr/bin/env python3
"""Inventory PC API wrappers and their direct IL callers without running the client.

Literal Hashtable writes are candidates, not a complete interprocedural request
schema: conditional paths, nested tables and computed keys need review. Existing
contract response keys are labelled as prior evidence, not newly inferred here.
All evidence offsets in these reports are relative to the standalone DLL.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.analyze_callbacks import simulate_body
from tools.classify_http_methods import classify_http_methods
from tools.oni_il import AssemblyModel
from app.business import contract
from app.main import build_registry


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)


def scan(assembly: Path, out: Path) -> dict[str, Any]:
    fingerprint = hashlib.sha256(assembly.read_bytes()).hexdigest()
    manifest = json.loads((ROOT/'docs/analysis/assembly_manifest.json').read_text(encoding='utf-8'))
    expected = next(row['sha256'] for row in manifest['assemblies'] if row['name'] == 'Assembly-CSharp.dll')
    if fingerprint != expected:
        raise ValueError(f'PC assembly fingerprint mismatch: expected {expected}, got {fingerprint}')
    model = AssemblyModel(assembly)
    bodies = list(model.iter_bodies())
    http_rows = classify_http_methods(model)
    known = {r['endpoint'] for r in http_rows}
    wrappers: dict[int, set[str]] = {}
    signatures: dict[int, str] = {}
    write_rows: list[dict[str, Any]] = []
    params_seen: dict[str, set[str]] = defaultdict(set)
    has_branches: set[str] = set()
    for body in bodies:
        if body.owner != 'WebApiClient' and not body.owner.startswith('WebApiClient/'):
            continue
        strings = {model.instruction_string(i) for i in body.body.instructions}
        endpoints = known & strings
        if not endpoints or not any(
            (target := model.instruction_target(i)) is not None
            and target.display_name == 'WebApiClient::httpCall'
            for i in body.body.instructions
        ):
            continue
        wrappers[body.token] = endpoints
        row = model.method_rows[(body.token & 0xFFFFFF) - 1]
        target = model.resolve_method_token(body.token)
        signature = target.signature
        param_names = {int(p.row.Sequence): str(p.row.Name) for p in row.ParamList}
        param_types = {index + 1: typ.clr_name for index, typ in enumerate(signature.parameter_types)} if signature else {}
        signatures[body.token] = f'{body.name}(' + ','.join(
            f'{param_types.get(n, "?")} {name}' for n, name in sorted(param_names.items()) if n
        ) + ')'
        branched = any(i.opcode.name.startswith(('br', 'beq', 'bne', 'bge', 'bgt', 'ble', 'blt')) or i.opcode.name == 'switch' for i in body.body.instructions)
        if branched:
            has_branches.update(endpoints)
        for call in simulate_body(model, body, {}).calls:
            if call.target.owner != 'System.Collections.Hashtable' or call.target.name not in {'set_Item', 'Add'} or len(call.args) != 2:
                continue
            key, value = call.args
            if key.kind != 'string':
                key_text = '<computed>'
            else:
                key_text = str(key.data)
            source = value.kind
            typ = ''
            if value.kind == 'arg':
                source = 'arg:' + param_names.get(value.data, str(value.data))
                typ = param_types.get(value.data, '')
            elif value.kind == 'string':
                source += ':' + str(value.data)
                typ = 'string'
            elif value.kind in {'int', 'number'}:
                # The shared delegate simulator does not decode every short
                # ldc form; don't publish its numeric placeholder as a value.
                source = 'numeric_constant_requires_IL_review'
                typ = 'numeric'
            elif value.data is not None:
                source += ':' + str(value.data)
            for api in sorted(endpoints):
                params_seen[api].add(key_text)
                write_rows.append({'endpoint': api, 'wrapper_token': f'0x{body.token:08X}',
                    'wrapper': signatures[body.token], 'key_candidate': key_text,
                    'value_origin_candidate': source, 'argument_clr_type': typ,
                    'dll_offset': f'0x{call.offset:X}', 'branched_wrapper': int(branched)})

    # One endpoint is emitted inside a compiler-generated callback belonging
    # to debugCreateQuestEncount. Preserve that evidence and bind the public
    # wrapper through its actual delegate pointer, rather than a name guess.
    emitter_count = len(wrappers)
    for body in bodies:
        if body.owner != 'WebApiClient' or body.token in wrappers:
            continue
        deferred: set[str] = set()
        for insn in body.body.instructions:
            if insn.opcode.name not in {'ldftn', 'ldvirtftn'}:
                continue
            target = model.instruction_target(insn)
            if target and target.owner.startswith('WebApiClient/'):
                deferred.update(wrappers.get(target.token, set()))
        if deferred:
            wrappers[body.token] = deferred
            signatures[body.token] = body.name + '(deferred callback; see emitter token)'

    callers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for body in bodies:
        for insn in body.body.instructions:
            if insn.opcode.name not in {'call', 'callvirt', 'ldftn', 'ldvirtftn'}:
                continue
            target = model.instruction_target(insn)
            if target is None or target.token not in wrappers:
                continue
            for api in sorted(wrappers[target.token]):
                callers[api].append({'endpoint': api, 'wrapper_token': f'0x{target.token:08X}',
                    'wrapper': signatures[target.token], 'caller_token': f'0x{body.token:08X}',
                    'caller': body.display_name, 'opcode': insn.opcode.name,
                    'caller_scope': 'webapi_internal' if body.owner == 'WebApiClient' or body.owner.startswith('WebApiClient/') else 'client_caller',
                    'dll_offset': f'0x{insn.offset:X}'})

    registry = build_registry()
    prior = contract.endpoints()
    review = []
    for api in sorted(known):
        keys = prior.get(api, {}).get('response', [])
        prior_params = set(prior.get(api, {}).get('request_params', []))
        handler = registry._handlers.get(api)
        kind = 'unregistered' if handler is None else 'contract_default' if handler.__name__.startswith('placeholder_') else 'dedicated_handler'
        review.append({'endpoint': api, 'handler_kind': kind,
            'http_methods': '|'.join(sorted({r['http_method'] for r in http_rows if r['endpoint'] == api})),
            'wrapper_tokens': '|'.join(f'0x{token:08X}' for token, apis in wrappers.items() if api in apis),
            'wrapper_signatures': '|'.join(signatures[token] for token, apis in wrappers.items() if api in apis),
            'direct_il_refs': len(callers[api]),
            'prior_request_keys': ','.join(sorted(prior_params)),
            'wrapper_literal_key_candidates': ','.join(sorted(params_seen[api] - {'<computed>'})),
            'prior_keys_without_literal_write': ','.join(sorted(prior_params - params_seen[api])),
            'new_literal_candidates': ','.join(sorted(params_seen[api] - prior_params - {'<computed>'})),
            'has_computed_key_candidate': int('<computed>' in params_seen[api]),
            'branched_wrapper': int(api in has_branches),
            'prior_typed_response_keys': sum(bool(k['type']) for k in keys),
            'prior_untyped_response_keys': sum(not k['type'] for k in keys),
            'analysis_scope': 'direct_IL_refs_only' if callers[api] else 'no_direct_ref_not_proof_of_unreachable'})

    out.mkdir(parents=True, exist_ok=True)
    write_tsv(out/'endpoints.tsv', list(review[0]), review)
    write_tsv(out/'request-write-candidates.tsv', list(write_rows[0]), write_rows)
    all_callers = [r for api in sorted(callers) for r in callers[api]]
    write_tsv(out/'direct-callers.tsv', list(all_callers[0]), all_callers)
    summary = {'assembly_sha256': fingerprint,
        'offset_basis': 'standalone DLL file offset, not decompressed bundle offset',
        'endpoints': len(known), 'http_emitter_methods': emitter_count, 'wrapper_methods_including_deferred': len(wrappers),
        'direct_reference_sites': len(all_callers),
        'with_direct_refs': sum(bool(callers[a]) for a in known),
        'without_direct_refs': sorted(a for a in known if not callers[a]),
        'placeholder_with_direct_refs': sum(r['handler_kind']=='contract_default' and bool(r['direct_il_refs']) for r in review),
        'placeholder_without_direct_refs': sum(r['handler_kind']=='contract_default' and not r['direct_il_refs'] for r in review),
        'prior_contract_only_endpoints': sorted(set(prior)-known),
        'assembly_only_endpoints': sorted(known-set(prior)),
        'handler_kinds': dict(Counter(r['handler_kind'] for r in review)),
        'branched_wrappers_endpoints': len(has_branches),
        'literal_write_candidate_rows': len(write_rows),
        'limitations': ['No client execution or server requests.',
            'Direct references do not establish UI reachability; reflection, native scripts and browser bridges are not resolved.',
            'Hashtable writes are linear-simulation candidates, not a path-sensitive or nested request schema.',
            'Prior contract response fields are retained for triage, not independently proven by this report.',
            'No original server-side rules, rewards, persistence or random distributions can be inferred solely from wrapper signatures.']}
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('assembly', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = scan(args.assembly, args.out)
    except (OSError, ValueError) as error:
        parser.exit(2, f'ERROR: {error}\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'without_direct_refs','limitations'}}, ensure_ascii=False))
