CXX ?= g++
CXXFLAGS_LIB = -shared -fPIC -g

.PHONY: all clean

all: libv1.so libv2.so

libv1.so: v1.cpp v1.hpp
	$(CXX) $(CXXFLAGS_LIB) -o $@ $<

libv2.so: v2.cpp v2.hpp
	$(CXX) $(CXXFLAGS_LIB) -o $@ $<

clean:
	rm -f libv1.so libv2.so
