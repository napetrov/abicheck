# Case 09: C++ Vtable Change

**Category:** C++ ABI | **Verdict:** 🟡 ABI CHANGE (exit 4)

> **Note on abidiff 2.4.0:** Returns exit **4** even though this is a hard vtable
> incompatibility. abidiff's text output explicitly notes:
> `"note that this is an ABI incompatible change to the vtable of class Widget"`.

## What breaks
The vtable is a hidden array of function pointers embedded in every `Widget` object.
Old code calls `widget->resize()` via vtable slot 1. After v2 inserts `recolor()` at
slot 1, that same call dispatches to `recolor()` instead — silent wrong behavior or
a crash.

## Why abidiff catches it
Reports `the vtable offset of method virtual int Widget::resize() changed from 1 to 2`
and labels it "ABI incompatible change to the vtable."

## Code diff

| v1.cpp | v2.cpp |
|--------|--------|
| `virtual int draw();` | `virtual int draw();` |
| `virtual int resize();` | `virtual int recolor();`  ← **inserted** |
| | `virtual int resize();` |

## Reproduce manually
```bash
g++ -shared -fPIC -g v1.cpp -o libwidget_v1.so
g++ -shared -fPIC -g v2.cpp -o libwidget_v2.so
abidw --out-file v1.xml libwidget_v1.so
abidw --out-file v2.xml libwidget_v2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 4
```

## How to fix
Only append new virtual methods — never insert them in the middle of the vtable.
Alternatively, use the non-virtual interface (NVI) pattern: make only a few virtual
hooks, add non-virtual public methods that call them.

## Real-world example
Qt's strict "no vtable reordering" rule is documented in their ABI compatibility
policy. Binary-compatible Qt releases never insert virtual methods.
