CC ?= gcc
CFLAGS_LIB = -shared -fPIC -g

.PHONY: all clean

all: libv1.so libv2.so

libv1.so: v1.c v1.h
	$(CC) $(CFLAGS_LIB) -o $@ $<

libv2.so: v2.c v2.h
	$(CC) $(CFLAGS_LIB) -o $@ $<

clean:
	rm -f libv1.so libv2.so
