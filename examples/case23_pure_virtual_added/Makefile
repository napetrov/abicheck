.PHONY: all clean

CXX ?= g++
CXXFLAGS = -shared -fPIC -g -std=c++17

all: libv1.so libv2.so

libv1.so: old/lib.cpp old/lib.h
	$(CXX) $(CXXFLAGS) -Iold -o libv1.so old/lib.cpp

libv2.so: new/lib.cpp new/lib.h
	$(CXX) $(CXXFLAGS) -Inew -o libv2.so new/lib.cpp

clean:
	rm -f libv1.so libv2.so
