cmake_minimum_required(VERSION 3.15)
project(case116_atomic_qualifier_changed C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_library(case116_v1 SHARED v1.c)
add_library(case116_v2 SHARED v2.c)

set_target_properties(case116_v1 PROPERTIES OUTPUT_NAME case116)
set_target_properties(case116_v2 PROPERTIES OUTPUT_NAME case116)
