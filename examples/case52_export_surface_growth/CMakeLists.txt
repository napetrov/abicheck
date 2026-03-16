# case52: uncontrolled export surface growth.
# v1 (good) has a clean export surface — only public_api.
# v2 (bad) adds internal functions that leak into .dynsym.
# NOTE: v1=good.c, v2=bad.c — the "bad" state is the newer version.
abicheck_add_case(case52_export_surface_growth
    V1_SOURCES good.c
    V2_SOURCES bad.c
    APP_SOURCES app.c
    APP_LINK_LIBRARIES ${CMAKE_DL_LIBS}
    PLATFORMS linux macos
)
