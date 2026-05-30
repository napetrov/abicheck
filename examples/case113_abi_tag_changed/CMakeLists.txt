cmake_minimum_required(VERSION 3.15)
project(case113_abi_tag_changed CXX)

add_library(case113_v1 SHARED v1.cpp)
add_library(case113_v2 SHARED v2.cpp)

set_target_properties(case113_v1 PROPERTIES OUTPUT_NAME case113)
set_target_properties(case113_v2 PROPERTIES OUTPUT_NAME case113)
