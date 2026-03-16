# case53: symbol versioning missing.
# v1 (bad) has no symbol versioning.
# v2 (good) uses .symver + version script to establish MYLIB_1.0 baseline.
abicheck_add_case(case53_symbol_versioning_missing
    V1_SOURCES bad.c
    V2_SOURCES good.c
    V2_LINK_OPTIONS
        -Wl,--version-script=${CMAKE_CURRENT_SOURCE_DIR}/version.map
    PLATFORMS linux
)
