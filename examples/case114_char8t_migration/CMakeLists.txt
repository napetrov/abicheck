cmake_minimum_required(VERSION 3.15)
project(case114_char8t_migration CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(case114_v1 SHARED v1.cpp)
add_library(case114_v2 SHARED v2.cpp)

set_target_properties(case114_v1 PROPERTIES OUTPUT_NAME case114)
set_target_properties(case114_v2 PROPERTIES OUTPUT_NAME case114)
