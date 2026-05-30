#pragma once
// v1: get_id() carries an explicit Itanium ABI tag "cxx11".
// The mangled name contains the B5cxx11 tag component, e.g. _Z6get_idB5cxx11v
[[gnu::abi_tag("cxx11")]] int get_id();
