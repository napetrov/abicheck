cmake_minimum_required(VERSION 3.15)
project(abicheck_examples C CXX)

# ---------------------------------------------------------------------------
# Cross-platform defaults
# ---------------------------------------------------------------------------
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Debug info on all platforms (gcc/clang: -g, MSVC: /Zi)
if(MSVC)
  add_compile_options(/Zi)
else()
  add_compile_options(-g)
endif()

# Export all symbols by default so examples behave like the old -fPIC builds.
# Individual cases override this when testing visibility / dllexport.
set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS ON)

# Place all binaries in the per-case build directory so tests can find them
# next to each other (libv1 + libv2 + app in the same folder).
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})

# ---------------------------------------------------------------------------
# Helper function: add a standard v1/v2 shared-library pair
#
# Usage:
#   abicheck_add_case(<case_name>
#       V1_SOURCES v1.c          V2_SOURCES v2.c
#      [V1_HEADERS v1.h]        [V2_HEADERS v2.h]
#      [V1_INCLUDE_DIRS dir]    [V2_INCLUDE_DIRS dir]
#      [V1_FORCE_INCLUDE v1.h]  [V2_FORCE_INCLUDE v2.h]
#      [V1_COMPILE_OPTIONS ..]  [V2_COMPILE_OPTIONS ..]
#      [V1_LINK_OPTIONS ..]     [V2_LINK_OPTIONS ..]
#      [LANG CXX]
#      [APP_SOURCES app.c]
#      [APP_INCLUDE_DIRS dir]
#      [APP_LINK_LIBRARIES lib]
#      [PLATFORMS linux macos windows]
#   )
# ---------------------------------------------------------------------------
function(abicheck_add_case CASE_NAME)
  cmake_parse_arguments(PARSE_ARGV 1 ARG
    ""
    "LANG"
    "V1_SOURCES;V2_SOURCES;V1_HEADERS;V2_HEADERS;V1_INCLUDE_DIRS;V2_INCLUDE_DIRS;V1_FORCE_INCLUDE;V2_FORCE_INCLUDE;V1_COMPILE_OPTIONS;V2_COMPILE_OPTIONS;V1_LINK_OPTIONS;V2_LINK_OPTIONS;APP_SOURCES;APP_INCLUDE_DIRS;APP_LINK_LIBRARIES;PLATFORMS"
  )

  # --- Platform filter ---
  if(ARG_PLATFORMS)
    set(_dominated FALSE)
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
      list(FIND ARG_PLATFORMS "linux" _idx)
    elseif(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
      list(FIND ARG_PLATFORMS "macos" _idx)
    elseif(CMAKE_SYSTEM_NAME STREQUAL "Windows")
      list(FIND ARG_PLATFORMS "windows" _idx)
    else()
      set(_idx -1)
    endif()
    if(_idx EQUAL -1)
      message(STATUS "Skipping ${CASE_NAME} (not supported on ${CMAKE_SYSTEM_NAME})")
      return()
    endif()
  endif()

  # --- Output directory per case ---
  set(_out ${CMAKE_BINARY_DIR}/${CASE_NAME})
  file(MAKE_DIRECTORY ${_out})

  # --- v1 library ---
  set(_v1 ${CASE_NAME}_v1)
  add_library(${_v1} SHARED ${ARG_V1_SOURCES})
  set_target_properties(${_v1} PROPERTIES
    OUTPUT_NAME v1
    PREFIX "lib"
    LIBRARY_OUTPUT_DIRECTORY ${_out}
    RUNTIME_OUTPUT_DIRECTORY ${_out}
    ARCHIVE_OUTPUT_DIRECTORY ${_out}
  )
  if(ARG_V1_INCLUDE_DIRS)
    target_include_directories(${_v1} PRIVATE ${ARG_V1_INCLUDE_DIRS})
  endif()
  if(ARG_V1_FORCE_INCLUDE)
    foreach(_hdr IN LISTS ARG_V1_FORCE_INCLUDE)
      if(MSVC)
        target_compile_options(${_v1} PRIVATE /FI${_hdr})
      else()
        target_compile_options(${_v1} PRIVATE -include ${_hdr})
      endif()
    endforeach()
  endif()
  if(ARG_V1_COMPILE_OPTIONS)
    target_compile_options(${_v1} PRIVATE ${ARG_V1_COMPILE_OPTIONS})
  endif()
  if(ARG_V1_LINK_OPTIONS)
    target_link_options(${_v1} PRIVATE ${ARG_V1_LINK_OPTIONS})
  endif()

  # --- v2 library ---
  set(_v2 ${CASE_NAME}_v2)
  add_library(${_v2} SHARED ${ARG_V2_SOURCES})
  set_target_properties(${_v2} PROPERTIES
    OUTPUT_NAME v2
    PREFIX "lib"
    LIBRARY_OUTPUT_DIRECTORY ${_out}
    RUNTIME_OUTPUT_DIRECTORY ${_out}
    ARCHIVE_OUTPUT_DIRECTORY ${_out}
  )
  if(ARG_V2_INCLUDE_DIRS)
    target_include_directories(${_v2} PRIVATE ${ARG_V2_INCLUDE_DIRS})
  endif()
  if(ARG_V2_FORCE_INCLUDE)
    foreach(_hdr IN LISTS ARG_V2_FORCE_INCLUDE)
      if(MSVC)
        target_compile_options(${_v2} PRIVATE /FI${_hdr})
      else()
        target_compile_options(${_v2} PRIVATE -include ${_hdr})
      endif()
    endforeach()
  endif()
  if(ARG_V2_COMPILE_OPTIONS)
    target_compile_options(${_v2} PRIVATE ${ARG_V2_COMPILE_OPTIONS})
  endif()
  if(ARG_V2_LINK_OPTIONS)
    target_link_options(${_v2} PRIVATE ${ARG_V2_LINK_OPTIONS})
  endif()

  # --- Consumer app (optional) ---
  if(ARG_APP_SOURCES)
    set(_app ${CASE_NAME}_app)
    add_executable(${_app} ${ARG_APP_SOURCES})
    set_target_properties(${_app} PROPERTIES
      OUTPUT_NAME app_v1
      RUNTIME_OUTPUT_DIRECTORY ${_out}
    )
    target_link_libraries(${_app} PRIVATE ${_v1})
    if(ARG_APP_INCLUDE_DIRS)
      target_include_directories(${_app} PRIVATE ${ARG_APP_INCLUDE_DIRS})
    endif()
    if(ARG_APP_LINK_LIBRARIES)
      target_link_libraries(${_app} PRIVATE ${ARG_APP_LINK_LIBRARIES})
    endif()
    if(NOT MSVC)
      set_target_properties(${_app} PROPERTIES
        BUILD_RPATH "$ORIGIN"
        INSTALL_RPATH "$ORIGIN"
      )
    endif()
  endif()
endfunction()

# ---------------------------------------------------------------------------
# Include all case subdirectories
# ---------------------------------------------------------------------------
file(GLOB _case_dirs RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} case*)
list(SORT _case_dirs)
foreach(_dir IN LISTS _case_dirs)
  if(IS_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/${_dir}
     AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/${_dir}/CMakeLists.txt)
    add_subdirectory(${_dir})
  endif()
endforeach()
