"""Minimal, dependency-free reader for the NSString payload inside an Apple
``NSAttributedString`` typedstream archive.

Why this exists
---------------
On modern macOS (Ventura and newer) the Messages database stores message text
in ``message.attributedBody`` — an ``NSArchiver`` "typedstream" blob — and
leaves the legacy ``message.text`` column NULL for the overwhelming majority of
messages. A reader that only consults ``message.text`` silently drops most of
the user's message history.

Wire format (verified empirically against a 230k-message chat.db)::

    04 0b "streamtyped" 81 e8 03      header + system version (1000)
    84 01 40                          type-encoding "@" (an object follows)
    84 84 84 12 "NSAttributedString" 00   class chain, each: <len><name> 00
    84 84 08 "NSObject" 00
    85 92                             end-of-chain / object reference
    84 84 84 08 "NSString" 01 94      NSString class, version 1
    84 01 2b                          type-encoding "+" (a byte string follows)
    <varint length> <utf-8 bytes>     <-- the backing string we want

Class names are framed as ``84 84 <len> <name> 00`` (a bare length byte), so the
three-byte marker ``84 01 2b`` is unambiguous: it appears exactly once before
the backing string. The backing string is the first ``+`` value in the archive;
any later ``+`` values belong to attribute runs (link URLs, message-part names)
and are deliberately ignored.

This module is intentionally *scanning* rather than a full typedstream
unarchiver: it needs one well-known field out of a stable, Apple-controlled
format, and a narrow reader is far easier to keep fail-safe than a general one.
Every failure mode returns ``""`` — ingestion must never crash on a malformed
or unexpected blob.
"""

from __future__ import annotations

__all__ = ["decode_attributed_body"]

_HEADER = b"\x04\x0bstreamtyped"
# 0x84 = "new type-encoding follows", 0x01 = encoding string length,
# 0x2b = '+' (byte string).
_BYTE_STRING_MARKER = b"\x84\x01\x2b"

# typedstream variable-length integer tags.
_TAG_INT16 = 0x81
_TAG_INT32 = 0x82

# Defensive ceiling: the longest plausible iMessage body. Anything beyond this
# means we mis-parsed a length and must bail rather than allocate wildly.
_MAX_LEN = 1 << 22  # 4 MiB


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    """Read a typedstream length integer at ``pos``.

    Returns ``(value, new_pos)``; raises ``ValueError`` on a truncated buffer.
    """
    if pos >= len(buf):
        raise ValueError("truncated length")
    tag = buf[pos]
    pos += 1
    if tag == _TAG_INT16:
        if pos + 2 > len(buf):
            raise ValueError("truncated int16 length")
        return int.from_bytes(buf[pos : pos + 2], "little", signed=False), pos + 2
    if tag == _TAG_INT32:
        if pos + 4 > len(buf):
            raise ValueError("truncated int32 length")
        return int.from_bytes(buf[pos : pos + 4], "little", signed=False), pos + 4
    if tag >= 0x80:
        # Any other high tag here is a float/reference marker — not a length.
        raise ValueError(f"unexpected length tag 0x{tag:02x}")
    return tag, pos


def decode_attributed_body(blob: object) -> str:
    """Best-effort extraction of the message text from an ``attributedBody``.

    Accepts ``bytes``/``bytearray``/``memoryview`` (sqlite3 hands back ``bytes``)
    and returns the decoded string, or ``""`` when the blob is absent, not a
    typedstream, or cannot be parsed. Never raises.
    """
    if blob is None:
        return ""
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    elif isinstance(blob, bytearray):
        blob = bytes(blob)
    elif isinstance(blob, str):
        # Some drivers surface BLOBs as latin-1 text; recover the raw bytes.
        try:
            blob = blob.encode("latin-1")
        except Exception:
            return ""
    if not isinstance(blob, bytes) or not blob:
        return ""

    try:
        if not blob.startswith(_HEADER):
            return ""
        idx = blob.find(_BYTE_STRING_MARKER)
        if idx < 0:
            return ""
        pos = idx + len(_BYTE_STRING_MARKER)
        length, pos = _read_varint(blob, pos)
        if length <= 0 or length > _MAX_LEN or pos + length > len(blob):
            return ""
        return blob[pos : pos + length].decode("utf-8", errors="replace")
    except Exception:
        # Fail-safe: an undecodable blob must degrade to "no text", never to a
        # crashed ingest run.
        return ""
