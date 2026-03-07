.PHONY: all clean

all: libv1.so libv2.so

libv1.so: bad.c
	gcc -shared -fPIC -g -o libv1.so bad.c

libv2.so: good.c
	gcc -shared -fPIC -g -Wl,-soname,libv2.so -o libv2.so good.c

clean:
	rm -f libv1.so libv2.so
