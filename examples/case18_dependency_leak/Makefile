.PHONY: all clean

all: libv1.so libv2.so

libv1.so: libfoo_v1.c foo_v1.h thirdparty_v1.h
	gcc -shared -fPIC -g -o libv1.so libfoo_v1.c

libv2.so: libfoo_v2.c foo_v2.h thirdparty_v2.h
	gcc -shared -fPIC -g -o libv2.so libfoo_v2.c

clean:
	rm -f libv1.so libv2.so
