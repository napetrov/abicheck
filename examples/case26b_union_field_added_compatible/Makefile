.PHONY: all clean test-compat

CC ?= gcc
CFLAGS_LIB = -shared -fPIC -g

all: libv1.so libv2.so app_v1

libv1.so: old/lib.c old/lib.h
	$(CC) $(CFLAGS_LIB) -Iold -o libv1.so old/lib.c

libv2.so: new/lib.c new/lib.h
	$(CC) $(CFLAGS_LIB) -Inew -o libv2.so new/lib.c

app_v1: app.c old/lib.h libv1.so
	$(CC) -g app.c -Iold -L. -lv1 -Wl,-rpath,. -o app_v1

# Demonstrate ABI compatibility: compile against v1, run with v2
test-compat: all
	cp libv1.so libv1.so.bak
	cp libv2.so libv1.so
	./app_v1; ret=$$?; mv libv1.so.bak libv1.so; echo "EXIT:$$ret"; [ $$ret -eq 0 ]

clean:
	rm -f libv1.so libv2.so app_v1 libv1.so.bak
