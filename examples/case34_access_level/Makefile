CXX ?= g++
CXXFLAGS = -shared -fPIC -o

all: libv1.so libv2.so

libv1.so: v1.cpp v1.hpp
	$(CXX) $(CXXFLAGS) $@ $<

libv2.so: v2.cpp v2.hpp
	$(CXX) $(CXXFLAGS) $@ $<

clean:
	rm -f libv1.so libv2.so
