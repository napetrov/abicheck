abicheck_add_case(case116_atomic_qualifier_changed
    V1_SOURCES v1.c
    V2_SOURCES v2.c
    V1_HEADERS v1.h
    V2_HEADERS v2.h
    APP_SOURCES app.c
    PLATFORMS linux macos windows
)

# _Atomic is C11; ensure at least C11 even if the toolchain default is older.
set_target_properties(case116_atomic_qualifier_changed_v1 case116_atomic_qualifier_changed_v2
    PROPERTIES C_STANDARD 11
)
