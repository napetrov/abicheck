.PHONY: all clean test-break

CXX ?= g++
CXXFLAGS = -shared -fPIC -g

all: libv1.so libv2.so app_v1

libv1.so: v1.cpp v1.hpp
	$(CXX) $(CXXFLAGS) -o libv1.so v1.cpp

libv2.so: v2.cpp v2.hpp
	$(CXX) $(CXXFLAGS) -o libv2.so v2.cpp

app_v1: app.cpp v1.hpp
	$(CXX) -g -std=c++17 app.cpp -L. -lv1 -Wl,-rpath,. -o app_v1

test-break: all
	cp libv1.so libv1.so.bak
	cp libv2.so libv1.so
	./app_v1; echo "EXIT:$$?"
	mv libv1.so.bak libv1.so

clean:
	rm -f libv1.so libv2.so app_v1 libv1.so.bak
