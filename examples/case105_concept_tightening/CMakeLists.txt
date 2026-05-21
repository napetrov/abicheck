abicheck_add_case(case105_concept_tightening
    V1_SOURCES v1.cpp
    V2_SOURCES v2.cpp
    V1_HEADERS v1.h
    V2_HEADERS v2.h
    APP_SOURCES app.cpp
    # Concepts require C++20 — override the examples-wide C++17 default.
    V1_COMPILE_OPTIONS -std=c++20
    V2_COMPILE_OPTIONS -std=c++20
    PLATFORMS linux macos windows
)
