.PHONY: all clean test-break

CXX ?= g++
CXXFLAGS = -shared -fPIC -g -std=c++17

all: libv1.so libv2.so app_v1

libv1.so: old/lib.cpp old/lib.h
	$(CXX) $(CXXFLAGS) -Iold -o libv1.so old/lib.cpp

libv2.so: new/lib.cpp new/lib.h
	$(CXX) $(CXXFLAGS) -Inew -o libv2.so new/lib.cpp

app_v1: app.cpp old/lib.h libv1.so
	$(CXX) -g -std=c++17 app.cpp -Iold -L. -lv1 -Wl,-rpath,. -o app_v1

test-break: all
	cp libv1.so libv1.so.bak
	cp libv2.so libv1.so
	./app_v1; ret=$$?; mv libv1.so.bak libv1.so; echo "EXIT:$$ret"; exit $$ret

clean:
	rm -f libv1.so libv2.so app_v1 libv1.so.bak
