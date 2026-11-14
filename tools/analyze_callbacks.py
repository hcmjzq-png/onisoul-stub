#!/usr/bin/env python3
"""Build the API -> responder -> callback -> subscriber fanout from IL.

The central query is ``regist``: for every callback hub that contains a
``callCallbacks`` method, this tool enumerates every call to the hub's
``regist`` method and records the method pointer wrapped in the delegate.
The periodic fanout therefore includes all subscribers, not only the
responder that ultimately invokes ``callCallbacks``.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import tempfile
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    from tools.oni_il import (
        AssemblyModel,
        MethodDecodeError,
        MethodTarget,
        OniAnalysisError,
        extract_container_entry,
        is_unity_web_data,
    )
except ModuleNotFoundError:
    from oni_il import (  # type: ignore
        AssemblyModel,
        MethodDecodeError,
        MethodTarget,
        OniAnalysisError,
        extract_container_entry,
        is_unity_web_data,
    )


FANOUT_FIELDS = [
    "endpoint",
    "webapi_method",
    "responder_source",
    "responder_method",
    "responder_evidence",
    "callback_hub",
    "callback_path",
    "callback_path_evidence",
    "subscriber_count",
]
SUBSCRIBER_FIELDS = [
    "hub",
    "subscriber",
    "subscriber_evidence",
    "keys_checked",
    "keys_read",
    "unguarded_reads",
    "key_types",
    "read_evidence",
]


@dataclass(frozen=True)
class Value:
    kind: str
    data: Any = None


@dataclass
class SimulatedCall:
    body: Any
    offset: int
    target: MethodTarget
    receiver: Value | None
    args: list[Value]


@dataclass
class Simulation:
    calls: list[SimulatedCall] = field(default_factory=list)
    field_assignments: list[tuple[str, Value]] = field(default_factory=list)


def _value(insn: Any) -> Any:
    return getattr(insn.operand, "value", insn.operand)


def _operand_index(insn: Any) -> int:
    value = _value(insn)
    if hasattr(value, "index"):
        return int(value.index)
    return int(value)


def _pop(stack: list[Value], count: int) -> list[Value]:
    if count <= 0:
        return []
    if count > len(stack):
        return [Value("unknown") for _ in range(count - len(stack))] + stack[:]
    if count == len(stack):
        values = stack[:]
        stack.clear()
        return values
    values = stack[-count:]
    del stack[-count:]
    return values


def _delegate_target(values: Iterable[Value]) -> MethodTarget | None:
    found = None
    for value in values:
        if value.kind == "method" and isinstance(value.data, MethodTarget):
            found = value.data
    return found


def _parameter_count(target: MethodTarget | None) -> int:
    if target is None:
        return 0
    if target.signature is not None:
        return len(target.signature.parameter_types)
    if target.display_name == "WebApiClient::httpCall":
        return 4
    if target.owner == "WebApiClient":
        # The endpoint wrappers in this client take one responder argument.
        return 1
    if target.name in ("regist", "unregist", "callCallbacks"):
        return 1
    if target.name == "Invoke" and target.owner.rsplit("/", 1)[-1] in (
        "Responder",
        "Callback",
    ):
        return 1
    return 0


def simulate_body(model: AssemblyModel, body: Any, field_values: dict[str, Value]) -> Simulation:
    stack: list[Value] = []
    locals_: dict[int, Value] = {}
    arguments: dict[int, Value] = {
        index: Value("arg", index) for index in range(16)
    }
    result = Simulation()

    def load_local(index: int) -> Value:
        return locals_.get(
            index, Value("arg", index) if False else Value("local", index)
        )

    def resolve(value: Value) -> Value:
        seen: set[str] = set()
        while value.kind == "field" and isinstance(value.data, str):
            if value.data in seen:
                return Value("unknown")
            seen.add(value.data)
            value = field_values.get(value.data, Value("unknown"))
        return value

    for insn in body.body.instructions:
        op = insn.opcode.name
        if op in ("ldarg.0", "ldarg.1", "ldarg.2", "ldarg.3"):
            stack.append(Value("arg", int(op.rsplit(".", 1)[1])))
        elif op in ("ldarg.s", "ldarga.s"):
            stack.append(Value("arg", _operand_index(insn)))
        elif op == "ldarga":
            stack.append(Value("arg", _operand_index(insn)))
        elif op in ("ldloc.0", "ldloc.1", "ldloc.2", "ldloc.3"):
            stack.append(load_local(int(op.rsplit(".", 1)[1])))
        elif op == "ldloc.s":
            stack.append(load_local(_operand_index(insn)))
        elif op == "ldloca.s":
            stack.append(Value("local-address", _operand_index(insn)))
        elif op == "ldloca":
            stack.append(Value("local-address", _operand_index(insn)))
        elif op in ("stloc.0", "stloc.1", "stloc.2", "stloc.3"):
            index = int(op.rsplit(".", 1)[1])
            locals_[index] = resolve(_pop(stack, 1)[0])
        elif op == "stloc.s":
            index = _operand_index(insn)
            locals_[index] = resolve(_pop(stack, 1)[0])
        elif op == "starg.s":
            arguments[_operand_index(insn)] = resolve(_pop(stack, 1)[0])
        elif op == "ldstr":
            stack.append(Value("string", model.instruction_string(insn)))
        elif op == "ldnull":
            stack.append(Value("null"))
        elif op.startswith("ldc.i4"):
            raw = _value(insn)
            stack.append(Value("int", raw if isinstance(raw, int) else 0))
        elif op in ("ldc.i8", "ldc.r4", "ldc.r8"):
            stack.append(Value("number", _value(insn)))
        elif op == "ldftn" or op == "ldvirtftn":
            target = model.instruction_target(insn)
            stack.append(Value("method", target))
        elif op == "ldfld":
            _pop(stack, 1)
            name = model.resolve_field_token(int(_value(insn)))
            stack.append(Value("field", name))
        elif op == "ldsfld":
            name = model.resolve_field_token(int(_value(insn)))
            stack.append(Value("field", name))
        elif op == "stfld":
            value = _pop(stack, 1)[0]
            _pop(stack, 1)
            name = model.resolve_field_token(int(_value(insn)))
            resolved = resolve(value)
            result.field_assignments.append((name, resolved))
        elif op == "stsfld":
            value = _pop(stack, 1)[0]
            name = model.resolve_field_token(int(_value(insn)))
            result.field_assignments.append((name, resolve(value)))
        elif op == "dup":
            if stack:
                stack.append(stack[-1])
            else:
                stack.append(Value("unknown"))
        elif op == "pop":
            _pop(stack, 1)
        elif op == "newobj":
            target = model.instruction_target(insn)
            count = _parameter_count(target)
            values = _pop(stack, count)
            delegate = _delegate_target(values)
            if delegate is not None and target and target.owner.rsplit("/", 1)[-1].endswith(
                ("Responder", "Callback", "Function", "AggregateCallback")
            ):
                stack.append(Value("delegate", delegate))
            else:
                stack.append(Value("object", target.owner if target else None))
        elif op in ("call", "callvirt"):
            target = model.instruction_target(insn)
            if target is None:
                continue
            count = _parameter_count(target)
            has_this = bool(target.signature and target.signature.has_this)
            if not target.signature:
                # dnfile cannot decode several obfuscated signatures in this
                # build. All of the call sites we need here target instance
                # methods, including WebApiClient.httpCall and PeriodicRounder.
                has_this = True
            if has_this:
                count += 1
            args = _pop(stack, count)
            receiver = args[0] if has_this and args else None
            if has_this and args:
                # Calls are recorded with explicit arguments only.
                args = args[1:]
            result.calls.append(SimulatedCall(body, insn.offset, target, receiver, args))
            if target.signature is None:
                stack.append(Value("result"))
            elif target.signature.return_type.full_name != "System.Void":
                stack.append(Value("result", target.signature.return_type.full_name))
        elif op in ("castclass", "isinst", "unbox.any", "box", "conv.i1", "conv.i2",
                   "conv.i4", "conv.i8", "conv.r4", "conv.r8", "conv.u"):
            value = _pop(stack, 1)[0]
            stack.append(value if value.kind != "unknown" else Value("result"))
        elif op == "newarr":
            _pop(stack, 1)
            stack.append(Value("result"))
        elif op in ("ldlen", "ldind.i1", "ldind.u1", "ldind.i2", "ldind.u2",
                    "ldind.i4", "ldind.u4", "ldind.i8", "ldind.r4", "ldind.r8",
                    "ldind.ref", "ldobj"):
            _pop(stack, 1)
            stack.append(Value("result"))
        elif op in ("stind.ref", "stind.i1", "stind.i2", "stind.i4", "stind.i8",
                    "stind.r4", "stind.r8", "stobj"):
            _pop(stack, 2)
        elif op in ("ldelema", "stelem.ref", "stelem.i1", "stelem.i2", "stelem.i4",
                    "stelem.i8", "stelem.r4", "stelem.r8"):
            if op == "ldelema":
                _pop(stack, 2)
                stack.append(Value("result"))
            else:
                _pop(stack, 3)
        elif op.startswith(("ldelem", "ldc.")):
            _pop(stack, 2)
            stack.append(Value("result"))
        elif op in ("add", "sub", "mul", "div", "rem", "and", "or", "xor",
                    "shl", "shr", "shr.un", "ceq", "cgt", "cgt.un", "clt",
                    "clt.un", "beq", "bge", "bgt", "ble", "blt", "bne.un",
                    "beq.s", "bge.s", "bgt.s", "ble.s", "blt.s", "bne.un.s"):
            _pop(stack, 2)
            if not op.startswith("b"):
                stack.append(Value("result"))
        elif op in ("neg", "not", "ldind.i", "localloc"):
            _pop(stack, 1)
            stack.append(Value("result"))
        elif op in ("brtrue", "brfalse", "brtrue.s", "brfalse.s", "switch"):
            _pop(stack, 1)
        elif op in ("ret", "throw", "rethrow", "endfinally", "leave", "leave.s", "br", "br.s"):
            pass
    return result


def resolve_delegate(value: Value, field_values: dict[str, Value]) -> MethodTarget | None:
    seen: set[str] = set()
    while True:
        if value.kind == "delegate" and isinstance(value.data, MethodTarget):
            return value.data
        if value.kind == "method" and isinstance(value.data, MethodTarget):
            return value.data
        if value.kind != "field" or not isinstance(value.data, str):
            return None
        if value.data in seen:
            return None
        seen.add(value.data)
        value = field_values.get(value.data, Value("unknown"))


def method_display(target: MethodTarget) -> str:
    return target.display_name


def webapi_wrapper_name(body: Any) -> str:
    if body.owner.startswith("WebApiClient/"):
        match = re.match(r"<([^>]+)>", body.name)
        if match:
            return match.group(1)
    return body.name


def read_keys(model: AssemblyModel, body: Any) -> dict[str, Any]:
    instructions = body.body.instructions
    checked: set[str] = set()
    keys: dict[str, dict[str, str]] = {}
    for index, insn in enumerate(instructions):
        key = model.instruction_string(insn)
        if key is None:
            continue
        for probe in range(index + 1, min(index + 7, len(instructions))):
            target = model.instruction_target(instructions[probe])
            if target is None:
                continue
            if target.name == "ContainsKey":
                checked.add(key)
                break
            if target.name != "get_Item":
                break
            type_name = ""
            for type_probe in range(probe + 1, min(probe + 9, len(instructions))):
                candidate = instructions[type_probe]
                if candidate.opcode.name in ("box", "castclass", "isinst", "unbox.any"):
                    sig = model.instruction_type(candidate)
                    if sig is not None:
                        type_name = sig.clr_name
                    break
                if candidate.opcode.name.startswith(("stloc", "stfld", "stsfld")):
                    break
            keys.setdefault(
                key,
                {
                    "type": type_name,
                    "guarded": "1" if key in checked else "0",
                    "evidence": (
                        f"{body.owner}::{body.name}"
                        f"@0x{model.image_offset(insn.offset):X}"
                    ),
                },
            )
            break
    return {
        "checked": checked,
        "keys": keys,
        "unguarded": {key for key, row in keys.items() if row["guarded"] == "0"},
    }


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze(model: AssemblyModel) -> tuple[
    list[dict[str, str]], list[dict[str, str]], Counter[str]
]:
    bodies = list(model.iter_bodies())
    body_by_display: dict[str, Any] = {}
    for body in bodies:
        body_by_display.setdefault(body.display_name, body)

    hub_owners = {
        body.owner
        for body in bodies
        if body.name == "callCallbacks" and f"{body.owner}::regist" in body_by_display
    }
    regist_targets = {f"{owner}::regist" for owner in hub_owners}
    hub_targets = {f"{owner}::callCallbacks" for owner in hub_owners}

    field_values: dict[str, Value] = {}
    simulations: dict[int, Simulation] = {}
    for _ in range(3):
        changed = False
        new_field_values: dict[str, Value] = {}
        for body in bodies:
            simulation = simulate_body(model, body, field_values)
            simulations[id(body)] = simulation
            for name, value in simulation.field_assignments:
                if value.kind in ("delegate", "method"):
                    new_field_values.setdefault(name, value)
        if new_field_values != field_values:
            field_values = new_field_values
            changed = True
        if not changed:
            break
    if changed:
        for body in bodies:
            simulations[id(body)] = simulate_body(model, body, field_values)

    adjacency: dict[str, set[str]] = defaultdict(set)
    regist_calls: dict[str, set[MethodTarget]] = defaultdict(set)
    calls_by_target: dict[str, list[SimulatedCall]] = defaultdict(list)
    for body in bodies:
        simulation = simulations[id(body)]
        for call in simulation.calls:
            target_name = method_display(call.target)
            adjacency[body.display_name].add(target_name)
            calls_by_target[target_name].append(call)
            if target_name in regist_targets:
                delegate = _delegate_target(call.args)
                if delegate is None:
                    for arg in call.args:
                        delegate = resolve_delegate(arg, field_values)
                        if delegate is not None:
                            break
                if delegate is not None:
                    regist_calls[target_name.rsplit("::", 1)[0]].add(delegate)

    def find_hub(seed: MethodTarget) -> tuple[str, list[str]] | None:
        start = seed.display_name
        queue = deque([(start, [start])])
        seen = {start}
        while queue:
            current, path = queue.popleft()
            if len(path) > 9:
                continue
            for target in sorted(adjacency.get(current, ())):
                if target in hub_targets:
                    return target.rsplit("::", 1)[0], path + [target]
                if target not in seen and target in body_by_display:
                    seen.add(target)
                    queue.append((target, path + [target]))
        return None

    def method_evidence(name: str) -> str:
        body = body_by_display.get(name)
        if body is None:
            return name
        return f"{name}@0x{model.image_offset(body.file_offset):X}"

    api_rows: list[dict[str, str]] = []
    api_records: dict[tuple[str, str], dict[str, Any]] = {}
    for body in bodies:
        if body.owner != "WebApiClient" and not body.owner.startswith("WebApiClient/"):
            continue
        for call in simulations[id(body)].calls:
            if method_display(call.target) != "WebApiClient::httpCall":
                continue
            if len(call.args) < 3:
                continue
            endpoint = call.args[0].data if call.args[0].kind == "string" else None
            if not isinstance(endpoint, str) or "/" not in endpoint:
                continue
            responder = call.args[2]
            wrapper_name = webapi_wrapper_name(body)
            key = (endpoint, wrapper_name)
            record = api_records.setdefault(
                key,
                {
                    "endpoint": endpoint,
                    "webapi_method": wrapper_name,
                    "responder_source": [],
                    "responder_methods": set(),
                    "external_index": None,
                },
            )
            if responder.kind == "delegate" and isinstance(responder.data, MethodTarget):
                record["responder_source"].append("inline-delegate")
                record["responder_methods"].add(responder.data)
                responder_body = body_by_display.get(responder.data.display_name)
                if responder_body is not None:
                    captured_args = {
                        field_name: value
                        for field_name, value in simulations[id(body)].field_assignments
                        if value.kind == "arg"
                    }
                    for nested_call in simulations[id(responder_body)].calls:
                        if nested_call.target.name != "Invoke":
                            continue
                        receiver = nested_call.receiver
                        if receiver is None or receiver.kind != "field":
                            continue
                        captured = captured_args.get(str(receiver.data))
                        if captured is not None and captured.kind == "arg":
                            record["external_index"] = int(captured.data) - 1
                            break
            elif responder.kind == "arg":
                record["responder_source"].append("method-argument")
                record["external_index"] = int(responder.data) - 1
            else:
                record["responder_source"].append(responder.kind)

    # Stack simulation can lose a branch-sensitive call site. Fill any remaining
    # literal endpoint -> wrapper mapping with the narrow httpCall instruction
    # pattern; the missing responder is reported as unresolved rather than guessed.
    for body in bodies:
        if body.owner != "WebApiClient" and not body.owner.startswith("WebApiClient/"):
            continue
        instructions = body.body.instructions
        for index, insn in enumerate(instructions):
            target = model.instruction_target(insn)
            if target is None or target.display_name != "WebApiClient::httpCall":
                continue
            for probe in range(index - 1, max(-1, index - 14), -1):
                endpoint = model.instruction_string(instructions[probe])
                if endpoint is None or "/" not in endpoint:
                    continue
                wrapper_name = webapi_wrapper_name(body)
                key = (endpoint, wrapper_name)
                api_records.setdefault(
                    key,
                    {
                        "endpoint": endpoint,
                        "webapi_method": wrapper_name,
                        "responder_source": ["httpCall-pattern-fallback"],
                        "responder_methods": set(),
                        "external_index": None,
                    },
                )
                break

    for (endpoint, webapi_method), record in api_records.items():
        external_index = record["external_index"]
        if external_index is not None:
            for call in calls_by_target.get(f"WebApiClient::{webapi_method}", ()):
                if call.body.owner == "WebApiClient":
                    continue
                if external_index >= len(call.args):
                    continue
                delegate = resolve_delegate(call.args[external_index], field_values)
                if delegate is not None:
                    record["responder_methods"].add(delegate)
        responders = sorted(record["responder_methods"], key=method_display)
        if not responders:
            api_rows.append(
                {
                    "endpoint": endpoint,
                    "webapi_method": webapi_method,
                    "responder_source": ",".join(sorted(set(record["responder_source"]))),
                    "responder_method": "",
                    "responder_evidence": "",
                    "callback_hub": "",
                    "callback_path": "",
                    "callback_path_evidence": "",
                    "subscriber_count": "0",
                }
            )
            continue
        for responder in responders:
            hub = find_hub(responder)
            if hub is None:
                api_rows.append(
                    {
                        "endpoint": endpoint,
                        "webapi_method": webapi_method,
                        "responder_source": ",".join(
                            sorted(set(record["responder_source"]))
                        ),
                        "responder_method": responder.display_name,
                        "responder_evidence": method_evidence(responder.display_name),
                        "callback_hub": "",
                        "callback_path": "",
                        "callback_path_evidence": "",
                        "subscriber_count": "0",
                    }
                )
                continue
            hub_name, path = hub
            subscribers = regist_calls.get(hub_name, set())
            api_rows.append(
                {
                    "endpoint": endpoint,
                    "webapi_method": webapi_method,
                    "responder_source": ",".join(sorted(set(record["responder_source"]))),
                    "responder_method": responder.display_name,
                    "responder_evidence": method_evidence(responder.display_name),
                    "callback_hub": hub_name,
                    "callback_path": " -> ".join(path),
                    "callback_path_evidence": " -> ".join(
                        method_evidence(name) for name in path
                    ),
                    "subscriber_count": str(len(subscribers)),
                }
            )

    subscriber_rows: list[dict[str, str]] = []
    for hub_name in sorted(hub_owners):
        for subscriber in sorted(
            regist_calls.get(hub_name, set()), key=method_display
        ):
            body = body_by_display.get(subscriber.display_name)
            if body is None:
                subscriber_rows.append(
                    {
                        "hub": hub_name,
                        "subscriber": subscriber.display_name,
                        "subscriber_evidence": "unresolved",
                        "keys_checked": "",
                        "keys_read": "",
                        "unguarded_reads": "",
                        "key_types": "",
                        "read_evidence": "",
                    }
                )
                continue
            reads = read_keys(model, body)
            keys = reads["keys"]
            subscriber_rows.append(
                {
                    "hub": hub_name,
                    "subscriber": subscriber.display_name,
                    "subscriber_evidence": (
                        f"{body.owner}::{body.name}"
                        f"@0x{model.image_offset(body.file_offset):X}"
                    ),
                    "keys_checked": ",".join(sorted(reads["checked"])),
                    "keys_read": ",".join(sorted(keys)),
                    "unguarded_reads": ",".join(sorted(reads["unguarded"])),
                    "key_types": ",".join(
                        f"{key}:{keys[key]['type'] or '?'}" for key in sorted(keys)
                    ),
                    "read_evidence": ";".join(
                        keys[key]["evidence"] for key in sorted(keys)
                    ),
                }
            )

    stats = Counter()
    stats["api_records"] = len(api_rows)
    stats["responders_resolved"] = sum(
        1 for row in api_rows if row["responder_method"]
    )
    stats["fanout_rows"] = sum(1 for row in api_rows if row["callback_hub"])
    stats["hubs"] = len(hub_owners)
    stats["subscribers"] = len(subscriber_rows)
    return (
        sorted(api_rows, key=lambda row: (row["endpoint"], row["webapi_method"], row["responder_method"])),
        subscriber_rows,
        stats,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="assembly DLL or UnityWebData container")
    parser.add_argument(
        "--entry", default="Assembly-CSharp.dll", help="UnityWebData entry name"
    )
    parser.add_argument("--out", required=True, help="API fanout TSV")
    parser.add_argument(
        "--subscribers-out", required=True, help="subscriber/key evidence TSV"
    )
    args = parser.parse_args(argv)

    temp: tempfile.TemporaryDirectory[str] | None = None
    try:
        source = Path(args.input).expanduser().resolve()
        if is_unity_web_data(source):
            temp = tempfile.TemporaryDirectory(prefix="onisoul-callbacks-")
            assembly = Path(temp.name) / args.entry
            extracted = extract_container_entry(source, args.entry, assembly)
            image_offset_base = int(extracted["offset"])
        else:
            assembly = source
            image_offset_base = 0
        model = AssemblyModel(assembly, image_offset_base=image_offset_base)
        fanout, subscribers, stats = analyze(model)
        write_tsv(Path(args.out), FANOUT_FIELDS, fanout)
        write_tsv(Path(args.subscribers_out), SUBSCRIBER_FIELDS, subscribers)
        print(
            "[callbacks] "
            f"api_rows={stats['api_records']} "
            f"responders={stats['responders_resolved']} "
            f"fanout_rows={stats['fanout_rows']} "
            f"hubs={stats['hubs']} subscribers={stats['subscribers']}"
        )
    except (OSError, OniAnalysisError, MethodDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        if temp is not None:
            temp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
