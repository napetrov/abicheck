abicheck_add_case(case05_soname
    V1_SOURCES bad.c
    V2_SOURCES good.c
    V2_LINK_OPTIONS $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wl,-soname,libv2.so>
    PLATFORMS linux
)
