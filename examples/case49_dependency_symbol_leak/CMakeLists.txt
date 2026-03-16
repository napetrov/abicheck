# case49: dependency symbol leak via static archive linkage.
# v1 (bad) links dep.a without hiding dependency symbols.
# v2 (good) uses -fvisibility=hidden + version script to export only core_api.

# Build the dependency as a static archive
add_library(case49_dep STATIC dep.c)
set_target_properties(case49_dep PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/case49_dependency_symbol_leak
)

abicheck_add_case(case49_dependency_symbol_leak
    V1_SOURCES bad.c
    V2_SOURCES good.c
    V2_COMPILE_OPTIONS -fvisibility=hidden
    V2_LINK_OPTIONS
        -Wl,--version-script=${CMAKE_CURRENT_SOURCE_DIR}/exports.map
    APP_SOURCES app.c
    APP_LINK_LIBRARIES ${CMAKE_DL_LIBS}
    PLATFORMS linux
)

# Link the static archive into both v1 and v2
target_link_libraries(case49_dependency_symbol_leak_v1 PRIVATE case49_dep)
target_link_libraries(case49_dependency_symbol_leak_v2 PRIVATE case49_dep)
