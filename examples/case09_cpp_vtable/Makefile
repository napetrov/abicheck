.PHONY: all clean

all: libv1.so libv2.so

libv1.so: v1.cpp
	g++ -std=c++17 -shared -fPIC -g -o libv1.so v1.cpp

libv2.so: v2.cpp
	g++ -std=c++17 -shared -fPIC -g -o libv2.so v2.cpp

clean:
	rm -f libv1.so libv2.so
