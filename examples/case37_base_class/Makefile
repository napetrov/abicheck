CXX ?= g++
CXXFLAGS_LIB = -shared -fPIC -g
CXXFLAGS_APP = -g

.PHONY: all clean test-break

all: libv1.so libv2.so

libv1.so: v1.cpp v1.hpp
	$(CXX) $(CXXFLAGS_LIB) -o $@ $<

libv2.so: v2.cpp v2.hpp
	$(CXX) $(CXXFLAGS_LIB) -o $@ $<

app_v1: app.cpp v1.cpp v1.hpp
	$(CXX) $(CXXFLAGS_APP) app.cpp -L. -Wl,-rpath,. -o $@ -lv1

# Demonstrate runtime break: compile against v1 headers, run with v2 .so
test-break: all app_v1
	LD_PRELOAD=./libv2.so ./app_v1; echo "EXIT:$$?"

clean:
	rm -f libv1.so libv2.so app_v1
