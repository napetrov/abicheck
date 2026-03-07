.PHONY: all clean

all: libv1.so libv2.so

libv1.so: v1.c
	gcc -shared -fPIC -g -o libv1.so v1.c

libv2.so: libv1.so
	cp libv1.so libv2.so

clean:
	rm -f libv1.so libv2.so
