.PHONY: all clean app_v1 test-break

CC ?= gcc
CFLAGS = -shared -fPIC -g

all: libv1.so libv2.so app_v1

libv1.so: v1.c v1.h
	$(CC) $(CFLAGS) -o libv1.so v1.c -include v1.h

libv2.so: v2.c v2.h
	$(CC) $(CFLAGS) -o libv2.so v2.c -include v2.h

app_v1: app.c v1.h libv1.so
	$(CC) -g app.c -I. -L. -lv1 -Wl,-rpath,. -o app_v1

test-break: all
	cp libv1.so libv1.so.bak
	cp libv2.so libv1.so
	./app_v1; echo "EXIT:$$?"
	mv libv1.so.bak libv1.so

clean:
	rm -f libv1.so libv2.so app_v1 libv1.so.bak
