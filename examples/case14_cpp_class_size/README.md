# Case 14: C++ Class Size Change

**Category:** C++ ABI | **Verdict:** 🟡 ABI CHANGE (exit 4)

> **Note on abidiff 2.4.0:** Returns exit **4**. Semantically breaking for any
> code that heap-allocates `Buffer` via operator new or embeds it by value.

## What breaks
Old code allocates `new Buffer()` expecting 64 bytes. v2's `Buffer` needs 128 bytes.
The allocator returns only 64 bytes; writing to `data[64..127]` corrupts heap memory.
Any consumer that inherits from or embeds `Buffer` by value is also broken.

## Why abidiff catches it
Reports `type size changed from 512 to 1024 (in bits)` (64 bytes → 128 bytes).

## Code diff

| v1.cpp | v2.cpp |
|--------|--------|
| `char data[64];` | `char data[128];` |

## Reproduce manually
```bash
g++ -shared -fPIC -g v1.cpp -o libbuf_v1.so
g++ -shared -fPIC -g v2.cpp -o libbuf_v2.so
abidw --out-file v1.xml libbuf_v1.so
abidw --out-file v2.xml libbuf_v2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 4
```

## How to fix
Use the PIMPL idiom: the public `Buffer` class stores only a pointer to a private
`BufferImpl` struct whose layout can change freely without affecting `sizeof(Buffer)`.

## Real-world example
Qt's "binary compatibility" rule explicitly forbids changing `sizeof` of any public
class. Every Qt class that needs to grow uses a `d_ptr` PIMPL to keep the public
class size constant across minor releases.
