CC ?= gcc
CFLAGS = -shared -fPIC -o

all: libv1.so libv2.so

libv1.so: v1.c v1.h
	$(CC) $(CFLAGS) $@ $< -include v1.h

libv2.so: v2.c v2.h
	$(CC) $(CFLAGS) $@ $< -include v2.h

clean:
	rm -f libv1.so libv2.so
