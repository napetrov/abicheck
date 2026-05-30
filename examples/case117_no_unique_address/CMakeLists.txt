cmake_minimum_required(VERSION 3.15)
project(case117_no_unique_address CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(case117_v1 SHARED v1.cpp)
add_library(case117_v2 SHARED v2.cpp)

set_target_properties(case117_v1 PROPERTIES OUTPUT_NAME case117)
set_target_properties(case117_v2 PROPERTIES OUTPUT_NAME case117)
