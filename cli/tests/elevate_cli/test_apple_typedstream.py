"""Tests for the ``attributedBody`` typedstream decoder.

Fixture blobs are synthesised byte-for-byte to the layout observed in a real
``chat.db`` (see ``apple_typedstream`` module docstring). No real message
content is used anywhere in this file.
"""

from __future__ import annotations

import pytest

from elevate_cli.source_connector_modules.apple_typedstream import (
    decode_attributed_body,
)

HEADER = b"\x04\x0bstreamtyped\x81\xe8\x03"
MARKER = b"\x84\x01\x2b"


def _length_bytes(n: int) -> bytes:
    """Encode a typedstream length the way NSArchiver does."""
    if n < 0x80:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\x81" + n.to_bytes(2, "little")
    return b"\x82" + n.to_bytes(4, "little")


# The two archive layouts observed in a real chat.db, captured byte-for-byte
# from the structural region that precedes the message payload. Hard-coding
# them makes this suite a regression pin on the actual Apple format rather than
# on our own idea of it.
PREFIX_ATTRIBUTED = (
    HEADER
    + b"\x84\x01\x40"
    + b"\x84\x84\x84\x12NSAttributedString\x00"
    + b"\x84\x84\x08NSObject\x00"
    + b"\x85\x92"
    + b"\x84\x84\x84\x08NSString\x01\x94"
)
PREFIX_MUTABLE = (
    HEADER
    + b"\x84\x01\x40"
    + b"\x84\x84\x84\x19NSMutableAttributedString\x00"
    + b"\x84\x84\x12NSAttributedString\x00"
    + b"\x84\x84\x08NSObject\x00"
    + b"\x85\x92"
    + b"\x84\x84\x84\x0fNSMutableString\x01"
    + b"\x84\x84\x08NSString\x01\x95"
)


def build_blob(text: str, *, mutable: bool = False, trailer: bytes = b"") -> bytes:
    """Build an NSAttributedString typedstream archive carrying ``text``."""
    payload = text.encode("utf-8")
    prefix = PREFIX_MUTABLE if mutable else PREFIX_ATTRIBUTED
    return prefix + MARKER + _length_bytes(len(payload)) + payload + trailer


# ─── Real-world layout pin ─────────────────────────────────────────────


def test_exact_real_world_header_and_marker_layout():
    """Pin the byte layout this decoder was derived from.

    If Apple ever changes the archive framing these constants are the first
    thing that must be revisited.
    """
    blob = build_blob("hi")
    assert blob.startswith(b"\x04\x0bstreamtyped")
    # The structural bytes immediately preceding the payload, as observed in
    # a real 230k-message chat.db.
    assert b"NSString\x01\x94\x84\x01\x2b\x02hi" in blob
    assert decode_attributed_body(blob) == "hi"


def test_mutable_attributed_string_variant():
    blob = build_blob("hello there", mutable=True)
    assert b"NSString\x01\x95\x84\x01\x2b" in blob
    assert decode_attributed_body(blob) == "hello there"


# ─── Happy paths across every length encoding ──────────────────────────


@pytest.mark.parametrize("size", [1, 2, 42, 0x7F])
def test_plain_single_byte_length(size):
    text = "a" * size
    assert decode_attributed_body(build_blob(text)) == text


@pytest.mark.parametrize("size", [0x80, 0x81, 1000, 0xFFFF])
def test_int16_length_tag(size):
    text = "b" * size
    blob = build_blob(text)
    assert blob[blob.find(MARKER) + 3] == 0x81
    assert decode_attributed_body(blob) == text


def test_int32_length_tag():
    text = "c" * 70000
    blob = build_blob(text)
    assert blob[blob.find(MARKER) + 3] == 0x82
    assert decode_attributed_body(blob) == text


def test_multibyte_utf8_is_decoded_by_bytes_not_characters():
    # Length prefix counts BYTES; a naive character-count reader truncates here.
    text = "café 🏡 déjà vu — 日本語"
    blob = build_blob(text)
    assert decode_attributed_body(blob) == text


def test_only_the_first_string_is_returned():
    """Later '+' values are attribute runs (link URLs, part names), not body."""
    blob = build_blob("real body", trailer=MARKER + _length_bytes(11) + b"attr-value!!")
    assert decode_attributed_body(blob) == "real body"


def test_accepts_memoryview_and_bytearray():
    blob = build_blob("buffered")
    assert decode_attributed_body(memoryview(blob)) == "buffered"
    assert decode_attributed_body(bytearray(blob)) == "buffered"


# ─── Fail-safe paths: every one must return "" and never raise ─────────


@pytest.mark.parametrize(
    "blob",
    [
        None,
        b"",
        b"not a typedstream at all",
        b"\x04\x0bstreamtyped\x81\xe8\x03",            # header only, no marker
        HEADER + b"\x84\x01\x2b",                      # marker, length truncated
        HEADER + b"\x84\x01\x2b\x81\x00",              # int16 length truncated
        HEADER + b"\x84\x01\x2b\x82\x00\x00",          # int32 length truncated
        HEADER + b"\x84\x01\x2b\x20short",             # length exceeds buffer
        HEADER + b"\x84\x01\x2b\x00",                  # zero length
        HEADER + b"\x84\x01\x2b\x83\x01\x02\x03\x04",  # float tag where length expected
        123,                                           # wrong type entirely
        object(),
    ],
)
def test_malformed_input_degrades_to_empty_string(blob):
    assert decode_attributed_body(blob) == ""


def test_absurd_length_is_rejected_rather_than_allocated():
    blob = HEADER + MARKER + b"\x82" + (1 << 30).to_bytes(4, "little")
    assert decode_attributed_body(blob) == ""


def test_undecodable_utf8_is_replaced_not_raised():
    payload = b"\xff\xfe\xfd"
    blob = HEADER + MARKER + _length_bytes(len(payload)) + payload
    out = decode_attributed_body(blob)
    assert isinstance(out, str) and out != ""


def test_truncated_real_blob_at_every_offset_never_raises():
    """Fuzz: ingestion must survive any partially-written blob."""
    blob = build_blob("a representative message body")
    for cut in range(len(blob)):
        assert isinstance(decode_attributed_body(blob[:cut]), str)
