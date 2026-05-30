cmake_minimum_required(VERSION 3.15)
project(case115_bit_int_width_changed C)

set(CMAKE_C_STANDARD 23)

add_library(case115_v1 SHARED v1.c)
add_library(case115_v2 SHARED v2.c)

set_target_properties(case115_v1 PROPERTIES OUTPUT_NAME case115)
set_target_properties(case115_v2 PROPERTIES OUTPUT_NAME case115)
