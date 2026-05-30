abicheck_add_case(case115_bit_int_width_changed
    V1_SOURCES v1.c
    V2_SOURCES v2.c
    V1_HEADERS v1.h
    V2_HEADERS v2.h
    APP_SOURCES app.c
    PLATFORMS linux macos windows
)

# _BitInt(N) is a C23 feature; request the latest C standard the toolchain has.
set_target_properties(case115_bit_int_width_changed_v1 case115_bit_int_width_changed_v2
    PROPERTIES C_STANDARD 23
)
