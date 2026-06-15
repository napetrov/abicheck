# Reference build for the abicheck Clang facts plugin (ADR-035 D5).
# Optional optimization — not part of the abicheck CI build.
cmake_minimum_required(VERSION 3.20)
project(abicheck_facts_plugin CXX)

find_package(LLVM REQUIRED CONFIG)
find_package(Clang REQUIRED CONFIG)

add_library(abicheck-facts MODULE AbicheckFactsPlugin.cpp)
target_include_directories(abicheck-facts SYSTEM PRIVATE ${LLVM_INCLUDE_DIRS} ${CLANG_INCLUDE_DIRS})
target_compile_definitions(abicheck-facts PRIVATE ${LLVM_DEFINITIONS})
target_compile_features(abicheck-facts PRIVATE cxx_std_17)

# Clang plugins link against the loading clang's symbols; do not bundle LLVM.
set_target_properties(abicheck-facts PROPERTIES PREFIX "lib")
