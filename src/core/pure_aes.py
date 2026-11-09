"""纯 Python AES-CBC 解密兜底。

用途：Windows 应用程序控制策略可能阻止 pycryptodome 的原生 .pyd，
导致 lark_oapi 导入 Crypto.Cipher.AES 失败。这里只实现 lark 需要的
AES-CBC 解密接口（block_size/new/decrypt），不依赖任何原生扩展。
"""

from __future__ import annotations


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _gmul(a: int, b: int) -> int:
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _ginv(a: int) -> int:
    if a == 0:
        return 0
    result = 1
    base = a
    exp = 254
    while exp:
        if exp & 1:
            result = _gmul(result, base)
        base = _gmul(base, base)
        exp >>= 1
    return result


def _rotl8(x: int, n: int) -> int:
    return ((x << n) | (x >> (8 - n))) & 0xFF


def _make_sbox() -> list[int]:
    box = []
    for x in range(256):
        y = _ginv(x)
        box.append(y ^ _rotl8(y, 1) ^ _rotl8(y, 2) ^ _rotl8(y, 3) ^ _rotl8(y, 4) ^ 0x63)
    return box


_SBOX = _make_sbox()
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i

_RCON = [0] * 15
_RCON[1] = 0x01
for _i in range(2, 15):
    _RCON[_i] = _xtime(_RCON[_i - 1])


def _sub_word(word: list[int]) -> list[int]:
    return [_SBOX[b] for b in word]


def _rot_word(word: list[int]) -> list[int]:
    return word[1:] + word[:1]


def _expand_key(key: bytes) -> list[list[int]]:
    nk = len(key) // 4
    nr = nk + 6
    words = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = words[i - 1][:]
        if i % nk == 0:
            temp = _sub_word(_rot_word(temp))
            temp[0] ^= _RCON[i // nk]
        elif nk > 6 and i % nk == 4:
            temp = _sub_word(temp)
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    return words


def _add_round_key(state: list[list[int]], words: list[list[int]], rnd: int) -> None:
    for c in range(4):
        w = words[rnd * 4 + c]
        for r in range(4):
            state[r][c] ^= w[r]


def _inv_sub_bytes(state: list[list[int]]) -> None:
    for r in range(4):
        for c in range(4):
            state[r][c] = _INV_SBOX[state[r][c]]


def _inv_shift_rows(state: list[list[int]]) -> None:
    for r in range(1, 4):
        row = [state[r][c] for c in range(4)]
        row = row[-r:] + row[:-r]
        for c in range(4):
            state[r][c] = row[c]


def _inv_mix_columns(state: list[list[int]]) -> None:
    for c in range(4):
        a0, a1, a2, a3 = state[0][c], state[1][c], state[2][c], state[3][c]
        state[0][c] = _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9)
        state[1][c] = _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13)
        state[2][c] = _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11)
        state[3][c] = _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)


def _decrypt_block(block: bytes, words: list[list[int]], nr: int) -> bytes:
    if len(block) != 16:
        raise ValueError("AES block must be 16 bytes")
    state = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    _add_round_key(state, words, nr)
    for rnd in range(nr - 1, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, words, rnd)
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, words, 0)
    return bytes(state[r][c] for c in range(4) for r in range(4))


class _Cipher:
    def __init__(self, key: bytes, iv: bytes):
        if len(key) not in (16, 24, 32):
            raise ValueError("AES key must be 16/24/32 bytes")
        if len(iv) != 16:
            raise ValueError("AES-CBC IV must be 16 bytes")
        self._key = key
        self._iv = iv

    def decrypt(self, data: bytes) -> bytes:
        if len(data) % 16:
            raise ValueError("ciphertext length must be a multiple of 16")
        words = _expand_key(self._key)
        nr = len(self._key) // 4 + 6
        out = bytearray()
        prev = self._iv
        for i in range(0, len(data), 16):
            block = data[i:i + 16]
            plain = _decrypt_block(block, words, nr)
            out.extend(p ^ q for p, q in zip(plain, prev))
            prev = block
        return bytes(out)


# 与 pycryptodome 的 Crypto.Cipher.AES 兼容的最小接口
block_size = 16
MODE_CBC = 2


def new(key: bytes, mode: int = MODE_CBC, iv: bytes | None = None):
    if mode != MODE_CBC:
        raise ValueError("pure_aes only supports AES.MODE_CBC")
    if iv is None:
        raise ValueError("AES-CBC requires an IV")
    return _Cipher(key, iv)
