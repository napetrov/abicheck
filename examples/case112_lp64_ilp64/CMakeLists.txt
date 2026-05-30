cmake_minimum_required(VERSION 3.15)
project(case112_lp64_ilp64 C)

add_library(case112_v1 SHARED v1.c)
add_library(case112_v2 SHARED v2.c)

set_target_properties(case112_v1 PROPERTIES OUTPUT_NAME case112)
set_target_properties(case112_v2 PROPERTIES OUTPUT_NAME case112)
