CC ?= gcc
CFLAGS = -shared -fPIC -o

all: libv1.so libv2.so app_v1

libv1.so: v1.c v1.h
	$(CC) $(CFLAGS) $@ $< -include v1.h

libv2.so: v2.c v2.h
	$(CC) $(CFLAGS) $@ $< -include v2.h

clean:
	rm -f libv1.so libv2.so app_v1

app_v1: app.c v1.h libv1.so
	$(CC) -g app.c -I. -L. -Wl,-rpath,. -lv1 -o app_v1
