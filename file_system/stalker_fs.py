#!/usr/bin/env python3
"""
STALKER X-Ray 引擎文件格式库 v3
支持 6 种 DB 格式 + sq_base 解密
纯 Python 实现，零外部依赖
"""
import struct, os, sys
from typing import Optional, Callable

# ═══════════════════════════════════════
# LZHUF: (c)1989 Okumura, MIT-licensed port
# ═══════════════════════════════════════

_LZ_N, _LZ_F, _LZ_THRESHOLD = 4096, 60, 2
_LZ_NCHAR = 256 - _LZ_THRESHOLD + _LZ_F  # 314
_LZ_T = _LZ_NCHAR * 2 - 1                 # 627
_LZ_R = _LZ_T - 1                          # 626
_LZ_MAXFREQ = 0x4000

_LZ_DCODE = bytes([0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x02,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x03,0x04,0x04,0x04,0x04,0x04,0x04,0x04,0x04,0x05,0x05,0x05,0x05,0x05,0x05,0x05,0x05,0x06,0x06,0x06,0x06,0x06,0x06,0x06,0x06,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x08,0x08,0x08,0x08,0x08,0x08,0x08,0x08,0x09,0x09,0x09,0x09,0x09,0x09,0x09,0x09,0x0A,0x0A,0x0A,0x0A,0x0A,0x0A,0x0A,0x0A,0x0B,0x0B,0x0B,0x0B,0x0B,0x0B,0x0B,0x0B,0x0C,0x0C,0x0C,0x0C,0x0D,0x0D,0x0D,0x0D,0x0E,0x0E,0x0E,0x0E,0x0F,0x0F,0x0F,0x0F,0x10,0x10,0x10,0x10,0x11,0x11,0x11,0x11,0x12,0x12,0x12,0x12,0x13,0x13,0x13,0x13,0x14,0x14,0x14,0x14,0x15,0x15,0x15,0x15,0x16,0x16,0x16,0x16,0x17,0x17,0x17,0x17,0x18,0x18,0x19,0x19,0x1A,0x1A,0x1B,0x1B,0x1C,0x1C,0x1D,0x1D,0x1E,0x1E,0x1F,0x1F,0x20,0x20,0x21,0x21,0x22,0x22,0x23,0x23,0x24,0x24,0x25,0x25,0x26,0x26,0x27,0x27,0x28,0x28,0x29,0x29,0x2A,0x2A,0x2B,0x2B,0x2C,0x2C,0x2D,0x2D,0x2E,0x2E,0x2F,0x2F,0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,0x38,0x39,0x3A,0x3B,0x3C,0x3D,0x3E,0x3F])
_LZ_DLEN = bytes([3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8])
_LZ_PLEN = bytes([3,4,4,4,5,5,5,5,5,5,5,5,6,6,6,6,6,6,6,6,6,6,6,6,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8])
_LZ_PCODE = bytes([0x00,0x20,0x30,0x40,0x50,0x58,0x60,0x68,0x70,0x78,0x80,0x88,0x90,0x94,0x98,0x9C,0xA0,0xA4,0xA8,0xAC,0xB0,0xB4,0xB8,0xBC,0xC0,0xC2,0xC4,0xC6,0xC8,0xCA,0xCC,0xCE,0xD0,0xD2,0xD4,0xD6,0xD8,0xDA,0xDC,0xDE,0xE0,0xE2,0xE4,0xE6,0xE8,0xEA,0xEC,0xEE,0xF0,0xF1,0xF2,0xF3,0xF4,0xF5,0xF6,0xF7,0xF8,0xF9,0xFA,0xFB,0xFC,0xFD,0xFE,0xFF])

class _Lzhuf:
    """LZHUF compressor/decompressor"""
    def __init__(self):
        self.freq = [0] * (_LZ_T + 1)
        self.prnt = [0] * (_LZ_T + _LZ_NCHAR)
        self.son = [0] * _LZ_T
        self.text_buf = [0] * (_LZ_N + _LZ_F - 1)
        self.lson = [0] * (_LZ_N + 1)
        self.rson = [0] * (_LZ_N + 257)
        self.dad = [0] * (_LZ_N + 1)
        self.match_position = 0; self.match_length = 0
        self.out = bytearray(); self.putbuf = 0; self.putlen = 0
        self.src = b""; self.spos = 0; self.slim = 0
        self.bbuf = 0; self.blen = 0

    # ─── Huffman ───
    def _starthuff(self):
        for i in range(_LZ_NCHAR):
            self.freq[i] = 1; self.son[i] = i + _LZ_T; self.prnt[i + _LZ_T] = i
        i, j = 0, _LZ_NCHAR
        while j <= _LZ_R:
            self.freq[j] = self.freq[i] + self.freq[i + 1]
            self.son[j] = i; self.prnt[i] = self.prnt[i + 1] = j
            i += 2; j += 1
        self.freq[_LZ_T] = 0xFFFF; self.prnt[_LZ_R] = 0

    def _reconst(self):
        j = 0
        for i in range(_LZ_T):
            if self.son[i] >= _LZ_T: self.freq[j] = (self.freq[i] + 1) >> 1; self.son[j] = self.son[i]; j += 1
        i = 0
        for jj in range(_LZ_NCHAR, _LZ_T):
            f = self.freq[i] + self.freq[i + 1]; self.freq[jj] = f; p = jj
            while p > 0 and self.freq[p - 1] > f: self.freq[p] = self.freq[p - 1]; self.son[p] = self.son[p - 1]; p -= 1
            self.freq[p] = f; self.son[p] = i; i += 2
        for i in range(_LZ_T):
            k = self.son[i]
            if k >= _LZ_T: self.prnt[k] = i
            else: self.prnt[k] = self.prnt[k + 1] = i

    def _update(self, c):
        if self.freq[_LZ_R] == _LZ_MAXFREQ: self._reconst()
        c = self.prnt[c + _LZ_T]
        # 原版是 do-while (先执行循环体再判断), 必须用 while True + break,
        # 否则 c == 0 (解码字符为 0) 时会跳过循环体导致 Huffman 树更新错误。
        while True:
            self.freq[c] += 1; k = self.freq[c]; l = c + 1
            if k > self.freq[l]:
                while k > self.freq[l + 1]: l += 1
                self.freq[c] = self.freq[l]; self.freq[l] = k
                i = self.son[c]; self.prnt[i] = l
                if i < _LZ_T: self.prnt[i + 1] = l
                j = self.son[l]; self.son[l] = i; self.prnt[j] = c
                if j < _LZ_T: self.prnt[j + 1] = c
                self.son[c] = j; c = l
            c = self.prnt[c]
            if c == 0: break

    # ─── Bit I/O ───
    def _getbit(self):
        while self.blen <= 8:
            b = self.src[self.spos] if self.spos < self.slim else 0; self.spos += 1
            self.bbuf |= b << (8 - self.blen); self.blen += 8
        self.blen -= 1; bit = (self.bbuf >> 15) & 1; self.bbuf = (self.bbuf << 1) & 0xFFFF; return bit

    def _getbyte(self):
        while self.blen <= 8:
            b = self.src[self.spos] if self.spos < self.slim else 0; self.spos += 1
            self.bbuf |= b << (8 - self.blen); self.blen += 8
        self.blen -= 8; r = (self.bbuf >> 8) & 0xFF; self.bbuf = (self.bbuf << 8) & 0xFFFF; return r

    def _putcode(self, l, c):
        self.putbuf |= c >> self.putlen; self.putlen += l
        if self.putlen >= 8:
            self.out.append((self.putbuf >> 8) & 0xFF); self.putlen -= 8
            if self.putlen >= 8:
                self.out.append(self.putbuf & 0xFF); self.putlen -= 8
                self.putbuf = (c << (l - self.putlen)) & 0xFFFF
            else:
                self.putbuf = (self.putbuf << 8) & 0xFFFF

    # ─── LZSS tree ───
    def _inittree(self):
        for i in range(_LZ_N + 1, _LZ_N + 257): self.rson[i] = _LZ_N
        for i in range(_LZ_N): self.dad[i] = _LZ_N

    def _insertnode(self, r):
        key = self.text_buf; p = _LZ_N + 1 + key[r]; cmp = 1
        self.lson[r] = self.rson[r] = _LZ_N; ml = 0
        while True:
            if cmp >= 0:
                if self.rson[p] != _LZ_N: p = self.rson[p]
                else: self.rson[p] = r; self.dad[r] = p; self.match_length = ml; return
            else:
                if self.lson[p] != _LZ_N: p = self.lson[p]
                else: self.lson[p] = r; self.dad[r] = p; self.match_length = ml; return
            i = 1
            while i < _LZ_F:
                cmp = key[r + i] - key[p + i]
                if cmp: break
                i += 1
            if i > _LZ_THRESHOLD:
                if i > ml:
                    self.match_position = ((r - p) & (_LZ_N - 1)) - 1; ml = i
                    if ml >= _LZ_F: break
                elif i == ml:
                    c = ((r - p) & (_LZ_N - 1)) - 1
                    if c < self.match_position: self.match_position = c
        self.dad[r] = self.dad[p]; self.lson[r] = self.lson[p]; self.rson[r] = self.rson[p]
        self.dad[self.lson[p]] = r; self.dad[self.rson[p]] = r
        if self.rson[self.dad[p]] == p: self.rson[self.dad[p]] = r
        else: self.lson[self.dad[p]] = r
        self.dad[p] = _LZ_N; self.match_length = ml

    def _deletenode(self, p):
        if self.dad[p] == _LZ_N: return
        if self.rson[p] == _LZ_N: q = self.lson[p]
        elif self.lson[p] == _LZ_N: q = self.rson[p]
        else:
            q = self.lson[p]
            if self.rson[q] != _LZ_N:
                while self.rson[q] != _LZ_N: q = self.rson[q]
                self.rson[self.dad[q]] = self.lson[q]; self.dad[self.lson[q]] = self.dad[q]
                self.lson[q] = self.lson[p]; self.dad[self.lson[p]] = q
            self.rson[q] = self.rson[p]; self.dad[self.rson[p]] = q
        self.dad[q] = self.dad[p]
        if self.rson[self.dad[p]] == p: self.rson[self.dad[p]] = q
        else: self.lson[self.dad[p]] = q
        self.dad[p] = _LZ_N

    # ─── Encode/Decode ───
    def _encode_char(self, c):
        i = 0; j = 0; k = self.prnt[c + _LZ_T]
        while k != _LZ_R:
            i >>= 1
            if k & 1: i += 0x8000
            j += 1; k = self.prnt[k]
        self._putcode(j, i); self._update(c)

    def _encode_position(self, c):
        i = c >> 6; self._putcode(_LZ_PLEN[i], _LZ_PCODE[i] << 8); self._putcode(6, (c & 0x3F) << 10)

    def _decode_char(self):
        c = self.son[_LZ_R]
        while c < _LZ_T: c = self.son[c + self._getbit()]
        c -= _LZ_T; self._update(c); return c

    def _decode_position(self):
        i = self._getbyte(); c = _LZ_DCODE[i] << 6; j = _LZ_DLEN[i] - 2
        while j: i = (i << 1) + self._getbit(); j -= 1
        return c | (i & 0x3F)

    def encode(self, data):
        ts = len(data); self.out = bytearray(struct.pack("<I", ts))
        self.putbuf = 0; self.putlen = 0
        if ts == 0: return bytes(self.out)
        self._starthuff(); self._inittree()
        s = 0; r = _LZ_N - _LZ_F
        for i in range(s, r): self.text_buf[i] = 0x20
        ll = 0
        for i in range(min(_LZ_F, ts)): self.text_buf[r + i] = data[i]; ll += 1
        for i in range(1, _LZ_F + 1): self._insertnode(r - i)
        self._insertnode(r)
        dp = ll
        while ll > 0:
            if self.match_length > ll: self.match_length = ll
            if self.match_length <= _LZ_THRESHOLD: self.match_length = 1; self._encode_char(self.text_buf[r])
            else: self._encode_char(255 - _LZ_THRESHOLD + self.match_length); self._encode_position(self.match_position)
            lm = self.match_length; i = 0
            while i < lm:
                if dp >= ts: break
                self._deletenode(s); c = data[dp]; dp += 1
                self.text_buf[s] = c
                if s < _LZ_F - 1: self.text_buf[s + _LZ_N] = c
                s = (s + 1) & (_LZ_N - 1); r = (r + 1) & (_LZ_N - 1); self._insertnode(r); i += 1
            while i < lm:
                self._deletenode(s); s = (s + 1) & (_LZ_N - 1); r = (r + 1) & (_LZ_N - 1)
                ll -= 1
                if ll: self._insertnode(r)
                i += 1
        if self.putlen: self.out.append((self.putbuf >> 8) & 0xFF)
        return bytes(self.out)

    def decode(self, src):
        if len(src) < 4: return b""
        ts = struct.unpack_from("<I", src, 0)[0]
        if ts == 0 or ts > 256 * 1024 * 1024: return b""
        self.src = src; self.spos = 4; self.slim = len(src); self.bbuf = 0; self.blen = 0
        self._starthuff()
        tb = bytearray(_LZ_N + _LZ_F - 1)
        for i in range(_LZ_N - _LZ_F): tb[i] = 0x20
        r = _LZ_N - _LZ_F; dest = bytearray(); count = 0
        while count < ts:
            c = self._decode_char()
            if c < 256: dest.append(c); tb[r] = c; r = (r + 1) & (_LZ_N - 1); count += 1
            else:
                pos = self._decode_position(); i = (r - pos - 1) & (_LZ_N - 1)
                j = c - 255 + _LZ_THRESHOLD
                for k in range(j):
                    if count >= ts: break
                    b = tb[(i + k) & (_LZ_N - 1)]; dest.append(b); tb[r] = b
                    r = (r + 1) & (_LZ_N - 1); count += 1
        return bytes(dest)

lzhuf = _Lzhuf()  # singleton

def _load_dll():
    """Load embedded LZHUF DLL for exact engine compatibility."""
    import ctypes, os, tempfile
    try:
        dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lzhuf_dll.dll")
        if not os.path.exists(dll_path):
            dll_path = os.path.join(tempfile.gettempdir(), "lzhuf_dll.dll")
            if not os.path.exists(dll_path):
                import base64 as _b64
                _b64_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lzhuf_dll.b64")
                with open(_b64_path, "r", encoding="ascii") as _bf:
                    _data = _b64.b64decode(_bf.read().strip())
                with open(dll_path, "wb") as f: f.write(_data)
        dll = ctypes.CDLL(dll_path)
        dll.lzhuf_decode.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int,
                                      ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
        dll.lzhuf_decode.restype = ctypes.c_int
        dll.lzhuf_encode.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int,
                                      ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
        dll.lzhuf_encode.restype = ctypes.c_int
        _py_enc = lzhuf.encode
        _py_dec = lzhuf.decode
        def _enc(data):
            buf = (ctypes.c_ubyte * (len(data) * 2 + 32))()
            sz = dll.lzhuf_encode((ctypes.c_ubyte * len(data))(*data), len(data), buf, len(buf))
            return bytes(buf[:sz])
        def _dec(src):
            us = int.from_bytes(src[:4], "little")
            if 0 < us <= 256 * 1024 * 1024:
                buf = (ctypes.c_ubyte * us)()
                sz = dll.lzhuf_decode((ctypes.c_ubyte * len(src))(*src), len(src), buf, us)
                if sz > 0: return bytes(buf[:sz])
            return _py_dec(src)
        lzhuf.encode = _enc
        lzhuf.decode = _dec
    except Exception:
        pass  # DLL not available, use pure Python fallback

_load_dll()



# ═══════════════════════════════════════
# Scrambler (2947ru/ww)
# ═══════════════════════════════════════

_SM = 0x8088405

class _Scrambler:
    _CFG = {"2947ru": (0x131A9D3, 0x1329436, 8), "2947ww": (0x16EB2EB, 0x5BBC4B, 4)}
    def __init__(self, variant):
        sv, s0, sm = self._CFG[variant]; self._seed = sv
        enc = list(range(256)); s = s0
        for _ in range(sm * 256):
            s = (1 + s * _SM) & 0xFFFFFFFF; a = (s >> 24) & 0xFF
            while True:
                s = (1 + s * _SM) & 0xFFFFFFFF; b = (s >> 24) & 0xFF
                if a != b: break
            enc[a], enc[b] = enc[b], enc[a]
        self._dec = [0] * 256
        for i, v in enumerate(enc): self._dec[v] = i
        self._enc = enc

    def encrypt(self, data):
        s = self._seed; r = bytearray(len(data))
        for i, b in enumerate(data):
            s = (1 + s * _SM) & 0xFFFFFFFF; r[i] = self._enc[b] ^ ((s >> 24) & 0xFF)
        return bytes(r)

    def decrypt(self, data):
        s = self._seed; r = bytearray(len(data))
        for i, b in enumerate(data):
            s = (1 + s * _SM) & 0xFFFFFFFF; r[i] = self._dec[b ^ ((s >> 24) & 0xFF)]
        return bytes(r)

_scramblers = {"2947ru": _Scrambler("2947ru"), "2947ww": _Scrambler("2947ww")}


# ═══════════════════════════════════════
# Chunk I/O
# ═══════════════════════════════════════

_CHUNK_COMP = 0x80000000
_CHUNK_COMP_V2 = 0x00800000  # original SoC variant
_COMP_MASK = 0x80800000  # either flag bit means compressed

def _read_chunks(raw: bytes) -> dict:
    """Read chunk headers: scan forward from offset 0 for DATA (id=0) and HEADER (id=1)."""
    chunks = {}
    pos = 0
    while pos + 8 <= len(raw):
        rid = struct.unpack_from("<I", raw, pos)[0]
        sz = struct.unpack_from("<I", raw, pos + 4)[0]
        cid = rid & 0x7FFFFFFF  # strip compression flag
        if cid <= 1 and 8 + sz <= len(raw) and sz > 0:
            comp = bool(rid & 0x80800000)
            data = raw[pos + 8:pos + 8 + sz]
            if cid == 0:
                chunks[0] = (comp, data)
            elif cid == 1:
                if _validate_header(data, comp):
                    chunks[1] = (comp, data)
                    if 0 in chunks:
                        return chunks  # both found
            pos += 8 + sz
        else:
            pos += 1  # skip one byte and retry (handles non-chunk-aligned data)
        if pos > len(raw) - 8:
            break
    return chunks


def _validate_header(hdr_data: bytes, comp: bool) -> bool:
    """Try to parse header. Return True if valid entries found."""
    for fmt in ("xdb", "2947ru", "2947ww", "2945", "2215", "11xx"):
        try:
            info = FORMATS[fmt]
            data = hdr_data
            if comp:
                if info["scrambler"]:
                    data = info["scrambler"].decrypt(data)
                data = lzhuf.decode(data)
            elif info["scrambler"]:
                data = info["scrambler"].decrypt(data)
            entries = info["parse"](data)
            if entries:
                for e in entries:
                    if not e["is_dir"]:
                        if 0 <= e["size_real"] < 2000000000:
                            p = e["path"]
                            if len(p) >= 2 and all(32 <= ord(c) < 127 for c in p):
                                if any(c.isalpha() for c in p[:min(8, len(p))]):
                                    return True
        except Exception:
            continue
    return False


# ═══════════════════════════════════════
# Entry builders (6 formats)
# ═══════════════════════════════════════

def _E_xdb(name: str, sr: int, sc: int, crc: int, off: int) -> bytes:
    nb = name.encode("cp1251")
    return struct.pack("<HIII", len(nb) + 16, sr, sc, crc) + nb + struct.pack("<I", off)

def _E_null4(name: str, a: int, b: int, c: int, d: int) -> bytes:
    return name.encode("cp1251") + b"\x00" + struct.pack("<IIII", a, b, c, d)

def _E_null3(name: str, a: int, b: int, c: int) -> bytes:
    return name.encode("cp1251") + b"\x00" + struct.pack("<III", a, b, c)


# ═══════════════════════════════════════
# Entry parsers (6 formats)
# ═══════════════════════════════════════

def _P_xdb(data: bytes) -> list:
    r = []; p = 0
    while p + 2 <= len(data):
        nf = struct.unpack_from("<H", data, p)[0]
        if nf < 16: break
        p += 2; nl = nf - 16
        if p + 12 + nl + 4 > len(data): break
        sr = struct.unpack_from("<I", data, p)[0]; sc = struct.unpack_from("<I", data, p + 4)[0]
        crc = struct.unpack_from("<I", data, p + 8)[0]; p += 12
        nm = data[p:p + nl].decode("cp1251", "replace"); p += nl
        off = struct.unpack_from("<I", data, p)[0]; p += 4
        nm = nm.replace("\\", "/").rstrip("/")
        # Offsets in header are file-absolute (after 8-byte chunk header)
        r.append({"path": nm, "offset": off, "size_real": sr, "size_comp": sc, "crc": crc,
                   "is_dir": (off == 0 and sr == 0 and sc == 0)})
    return r

def _P_null(data: bytes, nf: int) -> list:
    r = []; p = 0
    while p < len(data):
        n = data.find(b"\x00", p)
        if n < 0: break
        nm = data[p:n].decode("cp1251", "replace"); p = n + 1
        if p + nf * 4 > len(data): break
        fs = [struct.unpack_from("<I", data, p + i * 4)[0] for i in range(nf)]
        p += nf * 4
        nm = nm.replace("\\", "/").rstrip("/")
        r.append((nm, *fs))
    return r


# ═══════════════════════════════════════
# Format definitions
# ═══════════════════════════════════════

FORMATS = {
    "xdb": {
        "name": "XDB (CS/CoP)", "key": "-xdb",
        "scrambler": None,
        "pack": True,
        "build_header": lambda files: _build_header_xdb(files),
        "parse": _P_xdb,
    },
    "2947ru": {
        "name": "2947RU (SoC RUS)", "key": "-2947ru",
        "scrambler": _scramblers["2947ru"],
        "pack": True,
        "build_header": lambda files: _build_header_xdb(files),
        "parse": _P_xdb,
    },
    "2947ww": {
        "name": "2947WW (SoC WW)", "key": "-2947ww",
        "scrambler": _scramblers["2947ww"],
        "pack": True,
        "build_header": lambda files: _build_header_xdb(files),
        "parse": _P_xdb,
    },
    "2945": {
        "name": "2945 (Builds 2571-2945)", "key": "-2945",
        "scrambler": None, "pack": True,
        "build_header": lambda files: _build_header_null(files, 4,
            lambda n, off, sz: _E_null4(n, 0, off, sz, sz)),
        "parse": lambda d: _fmt_null(d, 4, (0, 2, 3, 4, 2)),
    },
    "2215": {
        "name": "2215 (Builds 1482-2232)", "key": "-2215",
        "scrambler": None, "pack": True,
        "build_header": lambda files: _build_header_null(files, 3,
            lambda n, off, sz: _E_null3(n, off, sz, sz)),
        "parse": lambda d: _fmt_null(d, 3, (0, 1, 2, 3, 1)),
    },
    "11xx": {
        "name": "11xx (Builds 1096-1472)", "key": "-11xx",
        "scrambler": None, "pack": True,
        "build_header": lambda files: _build_header_11xx(files),
        "parse": lambda d: _fmt_11xx(d),
    },
}


def _build_header_xdb(files: list) -> bytes:
    """files: [(path, data_bytes, is_dir), ...]"""
    h = b""; off = 8  # file-absolute offset (after DATA chunk header)
    for path, content, is_dir in files:
        if is_dir:
            h += _E_xdb(path + "\\", 0, 0, 0, 0)
        else:
            sz = len(content); h += _E_xdb(path, sz, sz, 0, off); off += sz
    return h


def _build_header_null(files: list, nf: int, entry_fn) -> bytes:
    h = b""; off = 8
    for path, content, is_dir in files:
        if is_dir: h += entry_fn(path + "\\", 0, 0)
        else: sz = len(content); h += entry_fn(path, off, sz); off += sz
    return h


def _build_header_11xx(files: list) -> bytes:
    h = b""; off = 8
    for path, content, is_dir in files:
        if is_dir: h += _E_null3(path + "\\", 1, 0, 0)
        else: sz = len(content); h += _E_null3(path, 1, off, sz); off += sz
    return h


def _fmt_null(data: bytes, nf: int, idx: tuple) -> list:
    """Convert null-term parsed entries to standard dict format
    idx: (name, offset, size_real, size_comp, is_dir_zero)"""
    r = []
    for e in _P_null(data, nf):
        r.append({
            "path": e[idx[0]], "offset": e[idx[1]], "size_real": e[idx[2]],
            "size_comp": e[idx[3]], "crc": 0, "is_dir": (e[idx[4]] == 0)
        })
    return r


def _fmt_11xx(data: bytes) -> list:
    """11xx entry: name\0 + uncompressed(4) + offset(4) + size(4)
    uncompressed==0 时文件内容是 LZHUF (前 4 字节是 textsize)。"""
    r = []
    for e in _P_null(data, 3):  # (name, uncompressed, offset, size)
        nm, uncomp, off, sz = e
        r.append({
            "path": nm, "offset": off,
            "size_real": sz if uncomp else 0,
            "size_comp": sz,
            "crc": 0, "is_dir": (off == 0),
            "use_lzhuf": (not uncomp)
        })
    return r


# ═══════════════════════════════════════
# Public API
# ═══════════════════════════════════════

def pack_db(files: list, fmt: str = "xdb") -> bytes:
    """Pack files into a DB archive.
    files: [(path, data_bytes, is_dir), ...]
    Paths use '/' internally; engine format requires backslashes.
    Returns raw db bytes."""
    if fmt in ("auto", "SquashFS", None) or fmt not in FORMATS:
        fmt = "xdb"
    files = [(p.replace("/", "\\"), c, d) for p, c, d in files]
    info = FORMATS[fmt]
    header = info["build_header"](files)
    compressed = lzhuf.encode(header)
    if info["scrambler"]:
        compressed = info["scrambler"].encrypt(compressed)

    data = b"".join(c for _, c, d in files if not d)
    db = struct.pack("<II", 0, len(data)) + data
    db += struct.pack("<I", 0x80000001) + struct.pack("<I", len(compressed)) + compressed
    return db


def unpack_db(raw: bytes, fmt: str = "xdb") -> list:
    """Unpack DB archive, return list of entry dicts."""
    if fmt in ("auto", "SquashFS", None):
        fmt = auto_detect(raw)
        if not fmt: return []
    info = FORMATS.get(fmt)
    if not info: return []
    chunks = _read_chunks(raw)
    if 1 not in chunks: return []
    comp, hdr = chunks[1]
    try:
        if comp:
            if info["scrambler"]:
                hdr = info["scrambler"].decrypt(hdr)
            hdr = lzhuf.decode(hdr)
        elif info["scrambler"]:
            # 2947ru/ww with uncompressed header: descramble then parse
            hdr = info["scrambler"].decrypt(hdr)
        return info["parse"](hdr)
    except Exception:
        return []


def auto_detect(raw: bytes) -> Optional[str]:
    """Try all formats, return first one that produces valid entries."""
    order = ["2947ru", "2947ww", "xdb", "2945", "11xx", "2215"]
    for fmt in order:
        entries = unpack_db(raw, fmt)
        if entries:
            for e in entries:
                if not e["is_dir"] and 0 < e["offset"] < len(raw) and e["size_real"] > 0:
                    return fmt
    return None


def load_db(path: str) -> bytes:
    """Load a DB file. Each part is independent (even for gamedata.db0/db1/...)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "rb") as f:
        return f.read()


def lzo1x_decompress(src: bytes, out_len: int = None) -> bytes:
    """LZO1X-1 解压 (minilzo lzo1x_decompress 直译)。
    out_len (size_real) 用于截断结尾无 eof 标记的 LZO 数据。
    结构必须是双循环: 外层 while (字面量 run) + 内层 match_loop (连续匹配),
    否则无法区分 t<16 的 M1 短匹配和外层字面量 run。"""
    M2_MAX_OFFSET = 0x0800
    n = len(src)
    if n == 0:
        return b""
    out = bytearray()
    ip = 0

    def cpm(m_pos, count):
        for _ in range(count):
            if out_len is not None and len(out) >= out_len:
                return
            out.append(out[m_pos])
            m_pos += 1

    def match_loop(t):
        nonlocal ip
        while True:
            if ip >= n:
                return True
            if t >= 64:  # M4
                if ip >= n:
                    return True
                m_pos = len(out) - 1 - ((t >> 2) & 7) - (src[ip] << 3)
                ip += 1
                t = (t >> 5) - 1
                cpm(m_pos, t + 2)
            elif t >= 32:  # M3
                t &= 31
                if t == 0:
                    while ip < n and src[ip] == 0:
                        t += 255; ip += 1
                    if ip >= n:
                        return True
                    t += 31 + src[ip]; ip += 1
                if ip + 2 > n:
                    return True
                m_pos = len(out) - 1 - ((src[ip] >> 2) + (src[ip + 1] << 6))
                ip += 2
                cpm(m_pos, t + 2)
            elif t >= 16:  # M2
                m_pos = len(out) - ((t & 8) << 11)
                t &= 7
                if t == 0:
                    while ip < n and src[ip] == 0:
                        t += 255; ip += 1
                    if ip >= n:
                        return True
                    t += 7 + src[ip]; ip += 1
                if ip + 2 > n:
                    return True
                m_pos -= (src[ip] >> 2) + (src[ip + 1] << 6)
                ip += 2
                if m_pos == len(out):
                    return True  # eof
                m_pos -= 0x4000
                cpm(m_pos, t + 2)
            else:  # M1 short
                if ip >= n:
                    return True
                m_pos = len(out) - 1 - (t >> 2) - (src[ip] << 2)
                ip += 1
                cpm(m_pos, 2)

            if out_len is not None and len(out) >= out_len:
                return True
            if ip < 2:
                return True
            t = src[ip - 2] & 3
            if t == 0:
                return False  # 回外层 while
            # match_next
            out.extend(src[ip:ip + t]); ip += t
            if out_len is not None and len(out) >= out_len:
                return True
            if ip >= n:
                return True
            t = src[ip]; ip += 1

    # 初始
    t = src[ip]; ip += 1
    if t > 17:
        t -= 17
        if t < 4:
            out.extend(src[ip:ip + t]); ip += t
            if ip >= n:
                return bytes(out)
            t = src[ip]; ip += 1
            match_loop(t)
        else:
            out.extend(src[ip:ip + t]); ip += t
            if ip >= n:
                return bytes(out)
            t = src[ip]; ip += 1
            if t >= 16:
                match_loop(t)
            else:
                m_pos = len(out) - (1 + M2_MAX_OFFSET) - (t >> 2) - (src[ip] << 2)
                ip += 1
                cpm(m_pos, 3)
                if ip < 2:
                    return bytes(out)
                t = src[ip - 2] & 3
                if t != 0:
                    out.extend(src[ip:ip + t]); ip += t
                    if ip >= n:
                        return bytes(out)
                    t = src[ip]; ip += 1
                    match_loop(t)

    # 外层 while
    while ip < n:
        t = src[ip]; ip += 1
        if t >= 16:
            match_loop(t)
            continue
        if t == 0:
            while ip < n and src[ip] == 0:
                t += 255; ip += 1
            if ip >= n:
                return bytes(out)
            t += 15 + src[ip]; ip += 1
        out.extend(src[ip:ip + t + 3]); ip += t + 3
        if out_len is not None and len(out) >= out_len:
            break
        if ip >= n:
            break
        t = src[ip]; ip += 1
        if t >= 16:
            match_loop(t)
        else:
            m_pos = len(out) - (1 + M2_MAX_OFFSET) - (t >> 2) - (src[ip] << 2)
            ip += 1
            cpm(m_pos, 3)
            if ip < 2:
                break
            t = src[ip - 2] & 3
            if t != 0:
                out.extend(src[ip:ip + t]); ip += t
                if ip >= n:
                    break
                t = src[ip]; ip += 1
                match_loop(t)

    if out_len is not None:
        return bytes(out[:out_len])
    return bytes(out)


def extract_file(raw: bytes, entry: dict) -> Optional[bytes]:
    """Extract a single file from a DB archive (LZO decompress if compressed)."""
    if entry["is_dir"]: return None
    # 11xx 的 LZHUF 文件 (comp 前 4 字节是 textsize)
    use_lzhuf = entry.get("use_lzhuf")
    if use_lzhuf is None:
        # 兼容未显式传 use_lzhuf 的调用方: 11xx LZHUF 条目 size_real=0 且 size_comp>0
        use_lzhuf = (entry.get("size_real", 0) == 0 and entry.get("size_comp", 0) > 0)
    if use_lzhuf:
        data = raw[entry["offset"]:entry["offset"] + entry["size_comp"]]
        return lzhuf.decode(data)
    sc = entry.get("size_comp") or entry["size_real"]
    data = raw[entry["offset"]:entry["offset"] + sc]
    if sc != entry["size_real"]:
        data = lzo1x_decompress(data, out_len=entry["size_real"])
    return data


def sqfs_check(path: str) -> str:
    """Classify an .sq file: 'sqfs' (plain), 'nlc' (encrypted ZZZZ), or 'unknown'."""
    if not os.path.exists(path): return "unknown"
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic in (b"hsqs", b"sqsh"): return "sqfs"
    if magic == b"ZZZZ": return "nlc"
    return "unknown"


# Find rdsquashfs from squashfs-tools-ng
_SQFS_TOOL = None
def _find_sqfs_tool():
    """Locate rdsquashfs; uses the external tools directly (no temp copy)."""
    global _SQFS_TOOL
    if _SQFS_TOOL:
        return _SQFS_TOOL
    # PyInstaller onedir：以 _MEIPASS(_internal) 为基准；开发环境：以本文件所在目录为基准。
    if getattr(sys, "frozen", False):
        bases = [getattr(sys, "_MEIPASS", "")]
    else:
        bases = [os.path.dirname(os.path.abspath(__file__))]
    # 同时覆盖上一级目录（开发环境为项目根；发布版为 exe 同目录）
    bases += [os.path.join(b, "..") for b in bases if b]
    sub = os.path.join("squashfs-tools-ng-1.3.2-mingw64", "bin", "rdsquashfs.exe")
    candidates = []
    for b in bases:
        if not b:
            continue
        candidates += [
            os.path.join(b, "rdsquashfs.exe"),
            os.path.join(b, "deps", sub),
            os.path.join(b, "plugins", sub),          # 兼容旧布局
            os.path.join(b, "legacy_sqfs_tools", sub),
        ]
    candidates.append(
        r"E:\Software\Games\STALKER\Localization\Tools\squashfs-tools-ng-1.3.2-mingw64\bin\rdsquashfs.exe"
    )
    for c in candidates:
        c = os.path.normpath(c)
        if os.path.isfile(c):
            _SQFS_TOOL = c
            return c
    return None


def cleanup_sqfs_tools():
    """No-op; kept for interface compatibility (tools are used in place)."""
    pass


def sqfs_list(path: str) -> Optional[list]:
    """List entries in a PLAIN SquashFS image, with real file sizes.
    Structure via rdsquashfs --describe; sizes via sqfs2tar (one pass)."""
    import subprocess, io, tarfile
    if sqfs_check(path) != "sqfs": return None
    tool = _find_sqfs_tool()
    if not tool or not tool.endswith("rdsquashfs.exe"): return None
    try:
        r = subprocess.run([tool, "--describe", path], capture_output=True, text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        if r.returncode != 0: return None
        entries = []
        import re as _re
        for line in r.stdout.strip().split("\n"):
            line = line.strip()
            if not line: continue
            m = _re.match(r'^(\S+)\s+"([^"]+)"', line)
            if m:
                etype, p = m.group(1), m.group(2)
            else:
                parts = line.split(None, 2)
                if len(parts) < 2: continue
                etype, p = parts[0], parts[1]
            p = p.replace("\\", "/")
            entries.append({"path": p, "size_real": 0,
                            "is_dir": (etype == "dir"), "offset": 0})
        # Sizes: one sqfs2tar pass
        base = os.path.dirname(tool)
        t2t = os.path.join(base, "sqfs2tar.exe")
        sizes = {}
        if os.path.exists(t2t):
            try:
                r2 = subprocess.run([t2t, path], capture_output=True, timeout=120,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                if r2.returncode == 0:
                    tar = tarfile.open(fileobj=io.BytesIO(r2.stdout))
                    for m in tar.getmembers():
                        sizes[m.name.replace("\\", "/")] = m.size
            except Exception:
                pass
        for e in entries:
            if not e["is_dir"] and e["path"] in sizes:
                e["size_real"] = sizes[e["path"]]
        return entries
    except Exception:
        return None


def sqfs_extract(path: str, out_dir: str, files: list = None) -> int:
    """Extract from a PLAIN SquashFS image. files: list of dicts with path.
    If files is None, extracts everything. Returns count."""
    import subprocess
    if sqfs_check(path) != "sqfs": return 0
    tool = _find_sqfs_tool()
    if not tool: return 0
    try:
        if files:
            wanted = {f["path"].replace("\\", "/").lstrip("./") for f in files if not f.get("is_dir")}
            if len(wanted) > 8:
                # 批量导出：一次 sqfs2tar 比逐个 rdsquashfs --cat 快得多。
                import io as _io
                import tarfile as _tarfile
                base = os.path.dirname(tool)
                t2t = os.path.join(base, "sqfs2tar.exe")
                if os.path.exists(t2t):
                    r = subprocess.run([t2t, path], capture_output=True, timeout=600,
                                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                    if r.returncode == 0:
                        count = 0
                        with _tarfile.open(fileobj=_io.BytesIO(r.stdout)) as tar:
                            for m in tar:
                                name = m.name.replace("\\", "/").lstrip("./")
                                if name in wanted and m.isfile():
                                    p = os.path.join(out_dir, name.replace("/", os.sep))
                                    os.makedirs(os.path.dirname(p), exist_ok=True)
                                    src = tar.extractfile(m)
                                    if src is not None:
                                        with open(p, "wb") as fh:
                                            fh.write(src.read())
                                        count += 1
                        return count
            count = 0
            for f in files:
                if f.get("is_dir"): continue
                r = subprocess.run([tool, "--cat", f["path"], path],
                                   capture_output=True, timeout=60,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                if r.returncode == 0 and r.stdout:
                    p = os.path.join(out_dir, f["path"].replace("/", os.sep))
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "wb") as fh: fh.write(r.stdout)
                    count += 1
            return count
        else:
            r = subprocess.run([tool, "--unpack-path", "/", "-p", out_dir, path],
                               capture_output=True, text=True, timeout=300,
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            return -1 if r.returncode == 0 else 0
    except Exception:
        return 0


def sqfs_pack(files: list, out_path: str) -> bool:
    """Pack files [(rel, data, is_dir)] into a SquashFS image via tar2sqfs."""
    import subprocess, io, tarfile, tempfile
    if not out_path: return False
    base = os.path.dirname(_find_sqfs_tool() or "")
    tool = os.path.join(base, "tar2sqfs.exe") if base else ""
    if not os.path.exists(tool): return False
    tmp_tar = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    try:
        with tarfile.open(fileobj=tmp_tar, mode="w") as tar:
            for rel, data, is_dir in files:
                ti = tarfile.TarInfo(rel)
                ti.size = len(data)
                tar.addfile(ti, io.BytesIO(data))
        tmp_tar.close()
        with open(tmp_tar.name, "rb") as fh:
            r = subprocess.run([tool, "-q", out_path], stdin=fh,
                               capture_output=True, timeout=120,
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        return r.returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp_tar.name)
        except OSError:
            pass  # best-effort temp file cleanup
