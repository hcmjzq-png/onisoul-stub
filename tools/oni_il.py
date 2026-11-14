#!/usr/bin/env python3
"""Shared read-only helpers for OniSoul PC IL analysis.

The analysis path deliberately consumes the client assembly directly.  The
only optional dependencies are ``dnfile`` (metadata) and ``dncil`` (strict IL
decoding); neither is a runtime dependency of the Stub server.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

try:
    import dnfile
    from dncil.cil.body import CilMethodBody
    from dncil.cil.body.reader import CilMethodBodyReaderBase
except ModuleNotFoundError as error:  # pragma: no cover - exercised by CLI error path
    raise ModuleNotFoundError(
        "IL analysis requires dnfile and dncil; install requirements-analysis.txt"
    ) from error


UNITY_WEB_DATA_MAGIC_PREFIX = b"UnityWeb"
TABLE_NAMES = {
    0x01: "TypeRef",
    0x02: "TypeDef",
    0x04: "Field",
    0x06: "MethodDef",
    0x0A: "MemberRef",
    0x1B: "TypeSpec",
    0x2B: "MethodSpec",
}
PRIMITIVE_TYPES = {
    0x01: "System.Void",
    0x02: "System.Boolean",
    0x03: "System.Char",
    0x04: "System.SByte",
    0x05: "System.Byte",
    0x06: "System.Int16",
    0x07: "System.UInt16",
    0x08: "System.Int32",
    0x09: "System.UInt32",
    0x0A: "System.Int64",
    0x0B: "System.UInt64",
    0x0C: "System.Single",
    0x0D: "System.Double",
    0x0E: "System.String",
    0x16: "System.TypedReference",
    0x18: "System.IntPtr",
    0x19: "System.UIntPtr",
    0x1C: "System.Object",
}
CLR_TYPES = {
    "System.Boolean": "bool",
    "System.Byte": "int",
    "System.SByte": "int",
    "System.Int16": "int",
    "System.UInt16": "int",
    "System.Int32": "int",
    "System.UInt32": "int",
    "System.Int64": "long",
    "System.UInt64": "ulong",
    "System.Single": "float",
    "System.Double": "double",
    "System.Char": "char",
    "System.String": "string",
    "System.Object": "object",
    "System.Collections.Hashtable": "Hashtable",
    "System.Collections.ArrayList": "ArrayList",
}
TERMINATORS = frozenset({"ret", "throw", "leave", "leave.s", "endfinally"})


class OniAnalysisError(RuntimeError):
    """Base error for malformed containers or unsupported analysis input."""


class ContainerFormatError(OniAnalysisError):
    """Raised when the UnityWebData entry table is malformed."""


class MethodDecodeError(OniAnalysisError):
    """Raised when one method body cannot be decoded completely."""


@dataclass(frozen=True)
class UnityWebDataEntry:
    name: str
    offset: int
    size: int
    table_offset: int

    @property
    def end(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class UnityWebData:
    count: int
    data_offset: int
    entries: tuple[UnityWebDataEntry, ...]


@dataclass(frozen=True)
class TypeSignature:
    full_name: str
    token: int | None = None
    wrapper: str = ""

    @property
    def clr_name(self) -> str:
        if self.wrapper == "byref":
            inner = TypeSignature(self.full_name, self.token)
            return inner.clr_name + "&"
        return CLR_TYPES.get(self.full_name, self.full_name.rsplit(".", 1)[-1])


@dataclass(frozen=True)
class MethodSignature:
    has_this: bool
    generic_count: int
    parameter_types: tuple[TypeSignature, ...]
    return_type: TypeSignature


@dataclass(frozen=True)
class MethodTarget:
    token: int
    owner: str
    name: str
    signature: MethodSignature | None = None
    table: str = ""

    @property
    def display_name(self) -> str:
        owner = self.owner or "?"
        return f"{owner}::{self.name}"


@dataclass(frozen=True)
class BodyInfo:
    token: int
    owner: str
    name: str
    rva: int
    file_offset: int
    body: Any
    code_start: int
    code_end: int
    body_end: int
    non_returning: bool = False

    @property
    def display_name(self) -> str:
        return f"{self.owner}::{self.name}"


class BytesBodyReader(CilMethodBodyReaderBase):
    """Sequential reader over the original assembly bytes.

    Unlike an RVA-backed reader, this preserves exact image offsets in every
    instruction operand and makes any operand read beyond the method body
    observable to the verifier.
    """

    def __init__(self, data: bytes, offset: int):
        self.data = data
        self.offset = offset

    def read(self, size: int) -> bytes:
        end = self.offset + size
        if self.offset < 0 or end > len(self.data):
            raise MethodDecodeError(
                f"read 0x{size:x} bytes at file offset 0x{self.offset:x} is out of range"
            )
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def tell(self) -> int:
        return self.offset

    def seek(self, offset: int) -> None:
        if offset < 0 or offset > len(self.data):
            raise MethodDecodeError(f"invalid seek to file offset 0x{offset:x}")
        self.offset = offset


class SignatureReader:
    """Minimal ECMA-335 signature reader used for call/dataflow analysis."""

    def __init__(self, data: bytes, position: int = 0):
        self.data = data
        self.position = position

    def byte(self) -> int:
        if self.position >= len(self.data):
            raise OniAnalysisError("signature ended unexpectedly")
        value = self.data[self.position]
        self.position += 1
        return value

    def compressed_uint(self) -> int:
        first = self.byte()
        if first & 0x80 == 0:
            return first
        if first & 0xC0 == 0x80:
            return ((first & 0x3F) << 8) | self.byte()
        if first & 0xE0 == 0xC0:
            return (
                ((first & 0x1F) << 24)
                | (self.byte() << 16)
                | (self.byte() << 8)
                | self.byte()
            )
        raise OniAnalysisError(f"invalid compressed integer lead byte 0x{first:02x}")

    def token(self) -> int:
        raw = self.data[self.position : self.position + 4]
        if len(raw) != 4:
            raise OniAnalysisError("type/method token ended unexpectedly")
        self.position += 4
        return struct.unpack("<I", raw)[0]

    def type(self) -> TypeSignature:
        element = self.byte()
        if element in PRIMITIVE_TYPES:
            return TypeSignature(PRIMITIVE_TYPES[element])
        if element == 0x0F:
            return TypeSignature(self.type().full_name, wrapper="ptr")
        if element == 0x10:
            inner = self.type()
            return TypeSignature(inner.full_name, inner.token, "byref")
        if element in (0x11, 0x12):  # VALUETYPE / CLASS
            token = self.token()
            return TypeSignature(f"token(0x{token:08X})", token)
        if element == 0x13:  # VAR
            return TypeSignature(f"!{self.compressed_uint()}")
        if element == 0x1E:  # MVAR
            return TypeSignature(f"!!{self.compressed_uint()}")
        if element in (0x14, 0x15):  # ARRAY / GENERICINST
            inner = self.type()
            if element == 0x14:
                _rank = self.compressed_uint()
                _sizes = self.compressed_uint()
                for _ in range(_sizes):
                    self.compressed_uint()
                _bounds = self.compressed_uint()
                for _ in range(_bounds):
                    self.compressed_uint()
                return TypeSignature(inner.full_name + "[]", inner.token)
            count = self.compressed_uint()
            arguments: list[str] = []
            for _ in range(count):
                arguments.append(self.type().full_name)
            return TypeSignature(
                f"{inner.full_name}<{','.join(arguments)}>", inner.token
            )
        if element in (0x1F, 0x20):  # CMOD_REQD / CMOD_OPT
            self.token()
            return self.type()
        if element == 0x45:  # PINNED
            return self.type()
        if element == 0x1B:  # FNPTR
            self.method()
            return TypeSignature("<function pointer>")
        if element == 0x1D:  # SZARRAY
            inner = self.type()
            return TypeSignature(inner.full_name + "[]", inner.token)
        raise OniAnalysisError(f"unsupported signature element 0x{element:02x}")

    def method(self) -> MethodSignature:
        convention = self.byte()
        has_this = bool(convention & 0x20)
        generic_count = self.compressed_uint() if convention & 0x10 else 0
        parameter_count = self.compressed_uint()
        return_type = self.type()
        parameter_types = tuple(self.type() for _ in range(parameter_count))
        return MethodSignature(
            has_this=has_this,
            generic_count=generic_count,
            parameter_types=parameter_types,
            return_type=return_type,
        )


def parse_method_signature(blob: bytes) -> MethodSignature:
    return SignatureReader(blob).method()


def ensure_supported_opcodes(body: Any) -> None:
    """Reject dncil placeholder opcodes such as ``UNKNOWN1`` / ``UNKNOWN2``."""
    unknown = [
        insn
        for insn in body.instructions
        if insn.opcode.name.upper().startswith("UNKNOWN")
    ]
    if unknown:
        first = unknown[0]
        raw = bytes(getattr(first.opcode, "value", ())) if isinstance(
            getattr(first.opcode, "value", None), (bytes, bytearray)
        ) else b""
        encoded = f" ({raw.hex()})" if raw else ""
        raise MethodDecodeError(
            f"unknown opcode {first.opcode.name}{encoded} at IL_{first.offset:04X}"
        )


def read_unity_web_data(path: str | Path) -> UnityWebData:
    """Read a UnityWebData entry table without extracting any payload."""
    source = Path(path)
    data = source.read_bytes()
    return parse_unity_web_data(data)


def parse_unity_web_data(data: bytes) -> UnityWebData:
    if len(data) < 8:
        raise ContainerFormatError("file is too short for a UnityWebData header")
    count = struct.unpack_from(">I", data, 0)[0]
    if count == 0 or count > 10000:
        raise ContainerFormatError(f"implausible UnityWebData entry count: {count}")
    position = 4
    entries: list[UnityWebDataEntry] = []
    for _ in range(count):
        table_offset = position
        zero = data.find(b"\0", position)
        if zero < position:
            raise ContainerFormatError(f"entry {len(entries)} has no NUL-terminated name")
        if zero + 9 > len(data):
            raise ContainerFormatError(f"entry {len(entries)} has a truncated offset/size")
        raw_name = data[position:zero]
        try:
            name = raw_name.decode("utf-8")
        except UnicodeDecodeError:
            name = raw_name.decode("latin-1")
        offset, size = struct.unpack_from(">II", data, zero + 1)
        end = offset + size
        if end > len(data):
            raise ContainerFormatError(
                f"entry {name!r} exceeds the file: 0x{offset:x}+0x{size:x} > 0x{len(data):x}"
            )
        entries.append(UnityWebDataEntry(name, offset, size, table_offset))
        position = zero + 9
    data_offset = min((entry.offset for entry in entries), default=position)
    if position > data_offset:
        raise ContainerFormatError(
            f"entry table ends at 0x{position:x}, after first payload at 0x{data_offset:x}"
        )
    return UnityWebData(count=count, data_offset=data_offset, entries=tuple(entries))


def is_unity_web_data(path: str | Path) -> bool:
    with Path(path).open("rb") as stream:
        start = stream.read(32)
    if start.startswith(UNITY_WEB_DATA_MAGIC_PREFIX):
        return False
    if len(start) < 4:
        return False
    count = struct.unpack_from(">I", start, 0)[0]
    return 0 < count <= 10000


def extract_container_entry(
    container_path: str | Path, entry_name: str, output_path: str | Path
) -> dict[str, Any]:
    source = Path(container_path)
    data = source.read_bytes()
    container = parse_unity_web_data(data)
    matches = [entry for entry in container.entries if entry.name == entry_name]
    if len(matches) != 1:
        raise ContainerFormatError(
            f"expected exactly one entry named {entry_name!r}, found {len(matches)}"
        )
    entry = matches[0]
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data[entry.offset : entry.end])
    return {
        "entry": entry.name,
        "offset": entry.offset,
        "size": entry.size,
        "output": str(destination.resolve()),
    }


class AssemblyModel:
    """Resolve metadata names and decode method bodies with exact file offsets."""

    def __init__(self, path: str | Path, image_offset_base: int = 0):
        self.path = Path(path).expanduser().resolve()
        self.image_offset_base = image_offset_base
        self.data = self.path.read_bytes()
        if self.data[:2] != b"MZ":
            raise OniAnalysisError(f"not a PE assembly: {self.path}")
        # Parse from memory so temporary extractions are not kept open on Windows.
        self.pe = dnfile.dnPE(data=self.data)
        if not self.pe.net:
            raise OniAnalysisError("PE has no CLI metadata")
        self.md = self.pe.net.mdtables
        self.method_rows = self.md.MethodDef.rows
        self.type_rows = self.md.TypeDef.rows
        self._body_cache: dict[int, BodyInfo] = {}
        self._body_errors: dict[int, str] = {}
        self._method_owner: dict[int, str] = {}
        self._field_owner: dict[int, str] = {}
        self._nested_outer: dict[int, int] = {}
        self._type_names: dict[tuple[str, int], str] = {}
        self._method_display: dict[int, str] = {}
        self._build_owner_indexes()

    def image_offset(self, file_offset: int) -> int:
        """Map an offset inside the extracted DLL to the source-container offset."""
        return self.image_offset_base + file_offset

    def _build_owner_indexes(self) -> None:
        method_ids = {id(row): index + 1 for index, row in enumerate(self.method_rows)}
        field_ids = {id(row): index + 1 for index, row in enumerate(self.md.Field.rows)}
        for row in self.md.NestedClass.rows:
            inner = getattr(row.NestedClass, "row_index", 0)
            outer = getattr(row.EnclosingClass, "row_index", 0)
            if inner and outer:
                self._nested_outer[inner] = outer
        for type_rid, type_row in enumerate(self.type_rows, start=1):
            owner = self.type_full_name(type_rid)
            for member in type_row.MethodList:
                row = getattr(member, "row", member)
                rid = method_ids.get(id(row))
                if rid:
                    self._method_owner[rid] = owner
                    self._method_display[rid] = f"{owner}::{row.Name}"
            for member in type_row.FieldList:
                row = getattr(member, "row", member)
                rid = field_ids.get(id(row))
                if rid:
                    self._field_owner[rid] = owner

    def type_full_name(self, rid: int, table: int = 0x02) -> str:
        key = (TABLE_NAMES.get(table, str(table)), rid)
        cached = self._type_names.get(key)
        if cached is not None:
            return cached
        if table == 0x01:
            row = self.md.TypeRef.rows[rid - 1]
            namespace = str(row.TypeNamespace or "")
            name = str(row.TypeName or "")
            full = f"{namespace}.{name}" if namespace else name
        elif table == 0x02:
            row = self.type_rows[rid - 1]
            namespace = str(row.TypeNamespace or "")
            name = str(row.TypeName or "")
            full = f"{namespace}.{name}" if namespace else name
            nested = self._nested_outer.get(rid)
            if nested:
                full = self.type_full_name(nested, 0x02) + "/" + name
        elif table == 0x1B:
            row = self.md.TypeSpec.rows[rid - 1]
            try:
                sig = SignatureReader(row.Signature.value).type()
                token = sig.token
                if token:
                    full = self.resolve_type_token(token).full_name
                else:
                    full = sig.full_name
            except OniAnalysisError:
                full = f"TypeSpec(0x1B{rid:06X})"
        else:
            full = f"type-table-{table}[{rid}]"
        self._type_names[key] = full
        return full

    def resolve_type_token(self, token: int) -> TypeSignature:
        table = (token >> 24) & 0xFF
        rid = token & 0xFFFFFF
        if table in (0x01, 0x02, 0x1B):
            return TypeSignature(self.type_full_name(rid, table), token)
        return TypeSignature(f"token(0x{token:08X})", token)

    def resolve_method_token(self, token: int) -> MethodTarget | None:
        table = (token >> 24) & 0xFF
        rid = token & 0xFFFFFF
        if table == 0x06:
            row = self.method_rows[rid - 1]
            try:
                signature = parse_method_signature(row.Signature.value)
            except OniAnalysisError:
                signature = None
            return MethodTarget(
                token,
                self._method_owner.get(rid, self.type_full_name(1)),
                str(row.Name),
                signature,
                "MethodDef",
            )
        if table == 0x0A:
            row = self.md.MemberRef.rows[rid - 1]
            parent = row.Class
            parent_table = getattr(getattr(parent, "table", None), "number", 0)
            parent_rid = getattr(parent, "row_index", 0)
            if parent_table:
                owner = self.type_full_name(parent_rid, parent_table)
            else:
                owner = "?"
            try:
                signature = parse_method_signature(row.Signature.value)
            except OniAnalysisError:
                signature = None
            return MethodTarget(token, owner, str(row.Name), signature, "MemberRef")
        if table == 0x2B:
            row = self.md.MethodSpec.rows[rid - 1]
            target = row.Method
            inner_rid = getattr(target, "row_index", 0)
            inner_table = getattr(getattr(target, "table", None), "number", 0)
            inner_token = (inner_table << 24) | inner_rid
            resolved = self.resolve_method_token(inner_token)
            if resolved is None:
                return None
            return MethodTarget(
                token,
                resolved.owner,
                resolved.name,
                resolved.signature,
                "MethodSpec",
            )
        return None

    def resolve_field_token(self, token: int) -> str:
        table = (token >> 24) & 0xFF
        rid = token & 0xFFFFFF
        if table == 0x04:
            row = self.md.Field.rows[rid - 1]
            return f"{self._field_owner.get(rid, '?')}::{row.Name}"
        if table == 0x0A:
            row = self.md.MemberRef.rows[rid - 1]
            parent = row.Class
            parent_table = getattr(getattr(parent, "table", None), "number", 0)
            parent_rid = getattr(parent, "row_index", 0)
            owner = self.type_full_name(parent_rid, parent_table) if parent_table else "?"
            return f"{owner}::{row.Name}"
        return f"field-token(0x{token:08X})"

    def user_string(self, token: int) -> str | None:
        try:
            value = self.pe.net.user_strings.get(token & 0xFFFFFF)
        except (IndexError, KeyError):
            return None
        if value is None:
            return None
        return str(value.value)

    def iter_method_rows(self) -> Iterator[tuple[int, str, Any]]:
        for rid, row in enumerate(self.method_rows, start=1):
            owner = self._method_owner.get(rid, "?")
            yield rid, owner, row

    def method_token(self, rid: int) -> int:
        return 0x06000000 | rid

    def method_rva_to_offset(self, rva: int) -> int:
        try:
            offset = self.pe.get_offset_from_rva(rva)
        except Exception as error:  # dnfile exposes different exception classes
            raise OniAnalysisError(f"RVA 0x{rva:x} does not map to a file offset") from error
        if offset is None or offset < 0 or offset >= len(self.data):
            raise OniAnalysisError(f"RVA 0x{rva:x} maps outside the file")
        return offset

    def body_for_rid(self, rid: int, allow_nonreturning_br: bool = True) -> BodyInfo:
        if rid in self._body_cache:
            return self._body_cache[rid]
        if rid in self._body_errors:
            raise MethodDecodeError(self._body_errors[rid])
        row = self.method_rows[rid - 1]
        token = self.method_token(rid)
        if row.Rva == 0:
            message = "method has no IL body (Rva=0)"
            self._body_errors[rid] = message
            raise MethodDecodeError(message)
        try:
            file_offset = self.method_rva_to_offset(row.Rva)
            reader = BytesBodyReader(self.data, file_offset)
            body = CilMethodBody(reader)
            ensure_supported_opcodes(body)
            code_start = file_offset + body.header_size
            code_end = code_start + body.code_size
            body_end = file_offset + body.size
            if body_end > len(self.data):
                raise MethodDecodeError("method body exceeds the assembly image")
            if not body.instructions:
                raise MethodDecodeError("method body contains no instructions")
            last = body.instructions[-1]
            # dncil reports instruction offsets as absolute reader offsets.
            decoded_end = last.offset + last.size
            if decoded_end != code_end:
                raise MethodDecodeError(
                    f"instruction stream ends at 0x{decoded_end:x}, expected 0x{code_end:x}"
                )
            non_returning = False
            if last.opcode.name not in TERMINATORS:
                # A few compiler-generated state machines end in an unconditional
                # backward branch (an intentional infinite loop). It cannot fall
                # through, but it is not one of the return/leave terminators.
                branch_target = getattr(last.operand, "value", last.operand)
                if (
                    allow_nonreturning_br
                    and last.opcode.name == "br"
                    and isinstance(branch_target, int)
                    and code_start <= branch_target < last.offset
                ):
                    non_returning = True
                else:
                    raise MethodDecodeError(
                        f"last instruction {last.opcode.name!r} at IL_{last.offset:04X} "
                        "is not a permitted terminator"
                    )
        except MethodDecodeError as error:
            self._body_errors[rid] = str(error)
            raise
        except Exception as error:  # dncil and dnfile use several exception types
            message = f"{type(error).__name__}: {error}"
            self._body_errors[rid] = message
            raise MethodDecodeError(message) from error
        result = BodyInfo(
            token=token,
            owner=self._method_owner.get(rid, "?"),
            name=str(row.Name),
            rva=row.Rva,
            file_offset=file_offset,
            body=body,
            code_start=code_start,
            code_end=code_end,
            body_end=body_end,
            non_returning=non_returning,
        )
        self._body_cache[rid] = result
        return result

    def body_for_target(self, target: MethodTarget) -> BodyInfo | None:
        if (target.token >> 24) == 0x06:
            return self.body_for_rid(target.token & 0xFFFFFF)
        if (target.token >> 24) == 0x2B:
            row = self.md.MethodSpec.rows[(target.token & 0xFFFFFF) - 1]
            inner = row.Method
            table = getattr(getattr(inner, "table", None), "number", 0)
            rid = getattr(inner, "row_index", 0)
            if table == 0x06:
                return self.body_for_rid(rid)
        return None

    def iter_bodies(self) -> Iterator[BodyInfo]:
        for rid, _owner, row in self.iter_method_rows():
            if row.Rva:
                yield self.body_for_rid(rid)

    def instruction_target(self, insn: Any) -> MethodTarget | None:
        if insn.opcode.name not in ("call", "callvirt", "newobj", "ldftn", "ldvirtftn"):
            return None
        operand = getattr(insn.operand, "value", insn.operand)
        if not isinstance(operand, int):
            token = getattr(insn.operand, "token", None)
            operand = token
        if not isinstance(operand, int):
            return None
        return self.resolve_method_token(operand)

    def instruction_string(self, insn: Any) -> str | None:
        if insn.opcode.name != "ldstr":
            return None
        operand = getattr(insn.operand, "value", insn.operand)
        return self.user_string(operand) if isinstance(operand, int) else None

    def instruction_type(self, insn: Any) -> TypeSignature | None:
        if insn.opcode.name not in ("box", "castclass", "isinst", "unbox.any"):
            return None
        operand = getattr(insn.operand, "value", insn.operand)
        if not isinstance(operand, int):
            operand = getattr(insn.operand, "token", None)
        return self.resolve_type_token(operand) if isinstance(operand, int) else None


def method_targets(model: AssemblyModel, body: BodyInfo) -> Iterable[MethodTarget]:
    for insn in body.body.instructions:
        target = model.instruction_target(insn)
        if target is not None:
            yield target


def parse_tsv_rows(path: str | Path, required: Sequence[str]) -> list[dict[str, str]]:
    import csv

    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        missing = [name for name in required if name not in (reader.fieldnames or [])]
        if missing:
            raise OniAnalysisError(
                f"{path}: missing TSV columns: {', '.join(missing)}"
            )
        return list(reader)

