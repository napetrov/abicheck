#pragma once
// v2: the same function loses the ABI tag. The demangled declaration is
// identical, but the mangled symbol is now _Z6get_idv — a distinct symbol.
int get_id();
