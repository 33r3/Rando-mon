"""
Encode/decode a 6-pokemon team into a 19-char URL-safe token.

Token layout (14 bytes → 19-char base64url, no padding):
  [0]      version byte (currently 0)
  [1..12]  6 × uint16 BE  (pokemon IDs)
  [13]     CRC-8 checksum over bytes [0..12]
"""
import struct
import base64


VERSION = 0


def _crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) if crc & 0x80 else crc << 1
            crc &= 0xFF
    return crc


def encode(ids: list) -> str:
    """Encode 6 pokemon IDs into a 19-char URL-safe token."""
    if len(ids) != 6:
        raise ValueError(f"Team must have exactly 6 pokemon, got {len(ids)}")
    if any(not (1 <= i <= 65535) for i in ids):
        raise ValueError("Pokemon IDs must be in range 1–65535")

    header = bytes([VERSION])
    payload = struct.pack(">6H", *ids)  # 12 bytes
    body = header + payload             # 13 bytes
    token_bytes = body + bytes([_crc8(body)])  # 14 bytes

    token = base64.urlsafe_b64encode(token_bytes).rstrip(b"=").decode("ascii")
    assert len(token) == 19
    return token


def decode(token: str) -> list:
    """Decode a 19-char token back into a list of 6 pokemon IDs."""
    padding = "=" * ((-len(token)) % 4)
    try:
        token_bytes = base64.urlsafe_b64decode(token + padding)
    except Exception as exc:
        raise ValueError(f"Invalid token: {exc}") from exc

    if len(token_bytes) != 14:
        raise ValueError(f"Invalid token length: expected 14 bytes, got {len(token_bytes)}")

    version = token_bytes[0]
    if version != VERSION:
        raise ValueError(f"Unknown token version {version}")

    if token_bytes[13] != _crc8(token_bytes[:13]):
        raise ValueError("Token checksum mismatch — corrupted or tampered token")

    return list(struct.unpack(">6H", token_bytes[1:13]))


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 2:
        try:
            ids = decode(sys.argv[1])
            print("Decoded IDs:", ids)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif len(sys.argv) == 7:
        ids = [int(x) for x in sys.argv[1:]]
        print(encode(ids))
    else:
        print("Usage: team_link.py <token>          — decode")
        print("       team_link.py id1 … id6        — encode")
        sys.exit(1)
