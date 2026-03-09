.PHONY: all clean

CC ?= gcc
CFLAGS = -shared -fPIC -g  # use CFLAGS += to append env flags (e.g. -fsanitize=address)

all: libv1.so libv2.so

libv1.so: old/lib.c old/lib.h
	$(CC) $(CFLAGS) -Iold -o libv1.so old/lib.c

libv2.so: new/lib.c new/lib.h
	$(CC) $(CFLAGS) -Inew -o libv2.so new/lib.c

clean:
	rm -f libv1.so libv2.so
