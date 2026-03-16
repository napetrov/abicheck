# case50: SONAME present but inconsistent — v1 has SONAME=libv1.so.0
# (wrong major), v2 has SONAME=libv2.so.1 (correct).
# Both libraries have the same ABI surface; the issue is metadata policy.
abicheck_add_case(case50_soname_inconsistent
    V1_SOURCES bad.c
    V1_LINK_OPTIONS $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wl,-soname,libfoo.so.0>
    V2_SOURCES good.c
    V2_LINK_OPTIONS $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wl,-soname,libfoo.so.1>
    PLATFORMS linux
)
