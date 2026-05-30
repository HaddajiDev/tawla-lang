"""A little garbage collector for Tawla programs, written in Python but called
straight from the JIT'd machine code.

Anything that lands on the heap (objects, arrays, joined strings) goes through
`gc_alloc`, which keeps a record of the block so the collector can find it later.
`collect()` does a conservative mark-sweep: the roots are exact (a shadow stack of
local variable slots that the generated code registers as it goes), but when we
walk *inside* a block we play it safe — any 8-byte word that happens to match a
live block's address is treated as a pointer. Being conservative means we never
free something that's still reachable (worst case we hang onto a little junk), so
it's safe.

These functions are handed to the JIT'd code as symbols via llvmlite's
`add_symbol`, and codegen emits calls to them. Collection only runs when you ask
for it with `collect()` — doing it automatically mid-expression could free a value
that's only being held in a temporary nobody registered as a root.
"""

import ctypes

import llvmlite.binding as llvm

WORD = 8


class GCHeap:
    def __init__(self):
        self.blocks: dict[int, list] = {}
        self.roots: list[tuple[int, int]] = []

    def reset(self) -> None:
        self.blocks.clear()
        self.roots.clear()


    def alloc(self, size: int) -> int:
        size = max(int(size), WORD)
        buf = (ctypes.c_char * size)()
        addr = ctypes.addressof(buf)
        self.blocks[addr] = [buf, size, False]
        return addr


    def root_push(self, slot_addr: int, nwords: int) -> None:
        self.roots.append((slot_addr, nwords))

    def root_depth(self) -> int:
        return len(self.roots)

    def root_settop(self, depth: int) -> None:
        del self.roots[depth:]


    def _scan(self, addr: int, nwords: int, worklist: list) -> None:
        for k in range(nwords):
            word = ctypes.c_uint64.from_address(addr + k * WORD).value
            block = self.blocks.get(word)
            if block is not None and not block[2]:
                block[2] = True
                worklist.append(word)

    def collect(self) -> None:
        worklist: list[int] = []
        for slot_addr, nwords in self.roots:
            self._scan(slot_addr, nwords, worklist)
        while worklist:
            addr = worklist.pop()
            self._scan(addr, self.blocks[addr][1] // WORD, worklist)

        for addr in [a for a, b in self.blocks.items() if not b[2]]:
            del self.blocks[addr]
        for block in self.blocks.values():
            block[2] = False

    def live(self) -> int:
        return len(self.blocks)


HEAP = GCHeap()

_alloc = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_uint64)(lambda n: HEAP.alloc(n))
_push = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int32)(
    lambda p, n: HEAP.root_push(p, n)
)
_depth = ctypes.CFUNCTYPE(ctypes.c_int32)(lambda: HEAP.root_depth())
_settop = ctypes.CFUNCTYPE(None, ctypes.c_int32)(lambda d: HEAP.root_settop(d))
_collect = ctypes.CFUNCTYPE(None)(lambda: HEAP.collect())
_live = ctypes.CFUNCTYPE(ctypes.c_int32)(lambda: HEAP.live())

_CALLBACKS = [_alloc, _push, _depth, _settop, _collect, _live]
_registered = False


def install() -> None:
    """Hand our runtime functions to llvmlite as symbols, then clear the heap for a fresh run."""
    global _registered
    if not _registered:
        addr = ctypes.cast
        llvm.add_symbol("gc_alloc", addr(_alloc, ctypes.c_void_p).value)
        llvm.add_symbol("gc_root_push", addr(_push, ctypes.c_void_p).value)
        llvm.add_symbol("gc_root_depth", addr(_depth, ctypes.c_void_p).value)
        llvm.add_symbol("gc_root_settop", addr(_settop, ctypes.c_void_p).value)
        llvm.add_symbol("gc_collect", addr(_collect, ctypes.c_void_p).value)
        llvm.add_symbol("gc_live", addr(_live, ctypes.c_void_p).value)
        _registered = True
    HEAP.reset()
